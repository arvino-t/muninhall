"""Хранилище Obsidian — «второй мозг»: вики по схеме LLM Wiki Карпаты (`<хранилище>/CLAUDE.md`, `wiki/`).

Приложение находит карточку книги (`wiki/sources/*.md` с полем `file:` — путь книги от корня хранилища),
читает и меняет её свойства (статус чтения, теги), пишет свои страницы (выделения) и журнал `wiki/log.md`.

Два способа доступа с одним интерфейсом:
- CliVault — официальный Obsidian CLI (Obsidian 1.12+), когда Obsidian запущен: свойства и теги меняются
  так, как их видит сам Obsidian (его кэш метаданных сразу актуален);
- FileVault — сами Markdown-файлы, когда CLI нет или Obsidian закрыт (Obsidian подхватит изменения).
Страницы целиком в обоих случаях пишутся файлами (атомарно): так надёжнее для больших страниц.
Файлы-источники (книги) не меняются никогда.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .core import log

FM_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
INLINE_TAG = re.compile(r"(?<![\w/#&])#([^\s#.,;:!?()\[\]{}\"'`<>|]+)")


# --- шапка (frontmatter) Markdown: простой YAML — строки, числа, списки [a, b] и «- пункт»

def _unquote(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].replace('\\"', '"') if v[0] == '"' else v[1:-1].replace("''", "'")
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_unquote(x) for x in _split_flow(inner)] if inner else []
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _split_flow(s: str) -> list[str]:
    """Разбивает «a, "b, c", d» по запятым вне кавычек."""
    out, cur, quote = [], "", ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def parse_frontmatter(text: str) -> dict:
    m = FM_RE.match(text)
    if not m:
        return {}
    props: dict = {}
    key = None
    for line in m.group(1).split("\n"):
        item = re.match(r"^\s+-\s*(.*)$", line) or re.match(r"^-\s+(.*)$", line)
        if item and key:
            if not isinstance(props.get(key), list):
                props[key] = []
            props[key].append(_unquote(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            props[key] = _unquote(kv.group(2)) if kv.group(2).strip() else []
    return props


def _yaml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{},&*!|>'\"%@`]", s) or s.strip() != s or s in ("true", "false") \
            or re.fullmatch(r"-?\d+(\.\d+)?", s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def set_frontmatter(text: str, **props) -> str:
    """Меняет только названные свойства (None — удалить); остальные строки шапки остаются как были."""
    m = FM_RE.match(text)
    lines = m.group(1).split("\n") if m else []
    body = text[m.end():] if m else text
    for key, value in props.items():
        start = next((i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}:", ln)), None)
        end = start
        if start is not None:
            end = start + 1
            while end < len(lines) and re.match(r"^\s+-|^-\s", lines[end]):
                end += 1
        new = [] if value is None else [f"{key}: {_yaml_value(value)}"]
        if start is None:
            lines += new
        else:
            lines[start:end] = new
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def norm_title(title: str) -> str:
    """Название для сравнения: без регистра, знаков и лишних пробелов."""
    return re.sub(r"[\W_]+", " ", (title or "").lower()).strip()


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.muninhall-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --- хранилище

def default_vault() -> Path | None:
    """Документы, если там вики по схеме (CLAUDE.md или AGENTS.md и wiki/)."""
    from PySide6.QtCore import QStandardPaths
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    for cand in (Path(docs) if docs else None, Path.home() / "Documents"):
        if cand and looks_like_vault(cand):
            return cand
    return None


def looks_like_vault(root: Path) -> bool:
    return (root / "wiki").is_dir() and any((root / n).exists() for n in ("CLAUDE.md", "AGENTS.md", ".obsidian"))


class FileVault:
    kind = "files"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.wiki = self.root / "wiki"
        self._cards: dict[str, Path] | None = None     # {путь книги от корня: карточка}
        self._by_name: dict[str, Path] = {}             # {имя файла книги: карточка} — если имя уникально
        self._by_title: dict[str, Path] = {}            # {нормализованное название: карточка}
        self._cards_at = 0.0
        self._tags: list[str] | None = None

    @property
    def name(self) -> str:
        return self.root.name

    def valid(self) -> bool:
        return looks_like_vault(self.root)

    def rel_of(self, path) -> str | None:
        """Путь файла от корня хранилища (или None, если файл вне хранилища)."""
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except (ValueError, OSError):
            return None

    # --- карточки книг

    def _scan_cards(self):
        cards, names, titles, dup = {}, {}, {}, set()
        for card in sorted((self.wiki / "sources").glob("*.md")):
            try:
                props = parse_frontmatter(card.read_text(encoding="utf-8")[:4000])
            except OSError:
                continue
            f = props.get("file")
            if isinstance(f, str) and f:
                cards[f] = card
                name = Path(f).name
                if name in names:
                    dup.add(name)
                names[name] = card
            if props.get("title"):
                titles.setdefault(norm_title(str(props["title"])), card)
        self._cards, self._cards_at = cards, time.monotonic()
        self._by_name = {k: v for k, v in names.items() if k not in dup}
        self._by_title = titles

    def find_card(self, book_path, title: str | None = None) -> Path | None:
        """Карточка книги: по пути файла в хранилище, иначе по имени файла (книги ЛитРес лежат в данных
        приложения, а в хранилище — их копии с теми же именами), иначе по названию."""
        rel = self.rel_of(book_path) if book_path else None
        if self._cards is None or (rel and rel not in self._cards and time.monotonic() - self._cards_at > 60):
            self._scan_cards()
        if rel and rel in self._cards:
            return self._cards[rel]
        if book_path and Path(book_path).name in self._by_name:
            return self._by_name[Path(book_path).name]
        return self._by_title.get(norm_title(title)) if title else None

    def card_link(self, card: Path) -> str:
        """Вики-ссылка на карточку: [[sources/Имя]]."""
        return f"[[{card.relative_to(self.wiki).with_suffix('').as_posix()}]]"

    def card_props(self, card: Path) -> dict:
        try:
            return parse_frontmatter(card.read_text(encoding="utf-8"))
        except OSError:
            return {}

    def set_props(self, card: Path, **props):
        text = card.read_text(encoding="utf-8")
        new = set_frontmatter(text, **props)
        if new != text:
            atomic_write(card, new)

    # --- теги

    def all_tags(self) -> list[str]:
        """Теги хранилища (из шапок и #тегов в тексте вики), частые первыми."""
        if self._tags is None:
            counts: dict[str, int] = {}
            for md in self.wiki.rglob("*.md"):
                try:
                    text = md.read_text(encoding="utf-8")
                except OSError:
                    continue
                tags = parse_frontmatter(text).get("tags") or []
                tags = [tags] if isinstance(tags, str) else tags
                body = FM_RE.sub("", text)
                body = re.sub(r"```.*?```|`[^`]*`", "", body, flags=re.S)
                for t in [str(x).lstrip("#") for x in tags] + INLINE_TAG.findall(body):
                    if t and not t.isdigit():
                        counts[t] = counts.get(t, 0) + 1
            self._tags = [t for t, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
        return self._tags

    def forget_tags(self):
        self._tags = None

    # --- свои страницы и журнал

    def read_page(self, rel: str) -> str | None:
        try:
            return (self.root / rel).read_text(encoding="utf-8")
        except OSError:
            return None

    def write_page(self, rel: str, text: str):
        atomic_write(self.root / rel, text)

    def append_log(self, entry: str):
        """Журнал вики: только дописывать в конец."""
        path = self.wiki / "log.md"
        prev = path.read_text(encoding="utf-8") if path.exists() else ""
        sep = "" if not prev or prev.endswith("\n\n") else ("\n" if prev.endswith("\n") else "\n\n")
        with path.open("a", encoding="utf-8") as f:
            f.write(sep + entry.rstrip("\n") + "\n")

    def obsidian_uri(self, rel: str) -> str:
        from urllib.parse import quote
        return f"obsidian://open?vault={quote(self.name)}&file={quote(rel)}"


# --- Obsidian CLI

def find_cli() -> list[str] | None:
    """Команда Obsidian CLI: зарегистрированный бинарь (Linux: ~/.local/bin/obsidian), PATH, Windows: Obsidian.com."""
    for cand in (Path.home() / ".local/bin/obsidian", shutil.which("obsidian"), shutil.which("Obsidian.com")):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return [str(cand)]
    return None


def obsidian_running() -> bool:
    """Запущен ли Obsidian: CLI без него сам открывает окно — этого при чтении книги не нужно."""
    if sys.platform.startswith("linux"):
        for comm in Path("/proc").glob("[0-9]*/comm"):
            try:
                if comm.read_text().strip().lower() == "obsidian":
                    return True
            except OSError:
                continue
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"], capture_output=True,
                                 text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "obsidian.exe" in out.stdout.lower()
        return subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class CliVault(FileVault):
    kind = "cli"

    def __init__(self, root: Path, command: list[str]):
        super().__init__(root)
        self.command = command

    def cli(self, *args: str, timeout=8) -> str | None:
        """Вызов CLI для этого хранилища; None — ошибка (тогда работаем с файлами)."""
        try:
            out = subprocess.run([*self.command, f"vault={self.name}", *args], capture_output=True, text=True,
                                 timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as e:
            log("obsidian cli:", e)
            return None
        if out.returncode != 0 or out.stdout.lstrip().lower().startswith("error"):
            log("obsidian cli:", args[:1], out.returncode, (out.stderr or out.stdout)[:200])
            return None
        return out.stdout

    def set_props(self, card: Path, **props):
        rel = self.rel_of(card)
        for key, value in props.items():
            if value is None:
                ok = self.cli("property:remove", f"name={key}", f"path={rel}")
            else:
                kind = ("list" if isinstance(value, (list, tuple)) else "checkbox" if isinstance(value, bool)
                        else "number" if isinstance(value, (int, float)) else "text")
                text = ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else _yaml_value(value) \
                    if isinstance(value, bool) else str(value)
                ok = self.cli("property:set", f"name={key}", f"value={text}", f"type={kind}", f"path={rel}")
            if ok is None:
                super().set_props(card, **{key: value})

    def all_tags(self) -> list[str]:
        if self._tags is None:
            out = self.cli("tags", "counts", "sort=count", "format=json")
            tags = _parse_cli_tags(out) if out else None
            if tags is None:
                return super().all_tags()
            self._tags = tags
        return self._tags


def _parse_cli_tags(out: str) -> list[str] | None:
    try:
        data = json.loads(out)
    except ValueError:
        return None
    items = data.items() if isinstance(data, dict) else data if isinstance(data, list) else []
    tags = []
    for it in items:
        if isinstance(it, tuple):
            tags.append(str(it[0]))
        elif isinstance(it, dict):
            name = it.get("tag") or it.get("name")
            if name:
                tags.append(str(name))
        elif isinstance(it, str):
            tags.append(it)
    return [t.lstrip("#") for t in tags]


# --- подключение

def connect(settings) -> FileVault | None:
    """Хранилище из настроек (или Документы с вики); CLI — если он есть и Obsidian запущен."""
    root = Path(settings.get("obsidianVault")).expanduser() if settings.get("obsidianVault") else default_vault()
    if not root or not looks_like_vault(root):
        return None
    command = find_cli()
    if command and obsidian_running():
        return CliVault(root, command)
    return FileVault(root)


def status(settings) -> tuple[str, str]:
    """(состояние, путь хранилища) для настроек: none / invalid / files / cli / cli-closed."""
    configured = settings.get("obsidianVault")
    root = Path(configured).expanduser() if configured else default_vault()
    if not root:
        return "none", ""
    if not looks_like_vault(root):
        return "invalid", str(root)
    if not find_cli():
        return "files", str(root)
    return ("cli" if obsidian_running() else "cli-closed"), str(root)


def in_background(fn, *args, **kwargs):
    """Вызов CLI может занять секунды — не держим окно."""
    def run():
        try:
            fn(*args, **kwargs)
        except Exception as e:          # ошибка хранилища не должна ронять приложение
            log("хранилище Obsidian:", e)
    threading.Thread(target=run, daemon=True).start()
