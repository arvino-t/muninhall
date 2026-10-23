"""Граф вики Obsidian для графа книг: страницы (темы, понятия, сущности, сравнения, синтез, проекты), ссылки
между ними и связь карточек книг (wiki/sources) с этими страницами; плюс возможные теги — то, чего в графе
ещё нет, но что связало бы книги.

Ссылки берутся так, как их видит Obsidian (CLI: metadataCache.resolvedLinks), а без CLI — из самих файлов.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .vault import FM_RE, parse_frontmatter

# папка вики → вид узла в графе
FOLDER_KINDS = {"topics": "wtopic", "concepts": "wconcept", "entities": "wentity", "comparisons": "wcompare",
                "synthesis": "wsynth", "projects": "wproject"}
LINK_RE = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
SKIP = ("sources/", "highlights/", "plans/", "_tools/")


class WikiGraph:
    def __init__(self):
        self.pages: dict[str, dict] = {}          # ключ «папка/имя» → {title, kind}
        self.links: set[tuple[str, str]] = set()  # (откуда, куда) между страницами вики (не карточками)
        self.card_links: dict[str, set[str]] = defaultdict(set)   # карточка «sources/Имя» → страницы
        self.missing: dict[str, set[str]] = defaultdict(set)      # «concepts/X» без страницы → кто ссылается


def _resolve(target: str, keys: dict[str, str], by_name: dict[str, str]) -> str | None:
    t = target.strip().removesuffix(".md").removeprefix("wiki/")
    if t in keys:
        return t
    return by_name.get(t.split("/")[-1].lower())


def load(root: Path, resolved_links: dict | None = None) -> WikiGraph:
    """Граф вики хранилища root. resolved_links — ответ Obsidian CLI ({путь: {путь: число}}), если есть."""
    g = WikiGraph()
    wiki = root / "wiki"
    files = {p.relative_to(wiki).with_suffix("").as_posix(): p for p in wiki.rglob("*.md")
             if not any(p.relative_to(wiki).as_posix().startswith(s) for s in ("_tools/",))}
    by_name = {k.split("/")[-1].lower(): k for k in files}
    texts = {}
    for key, path in files.items():
        folder = key.split("/")[0]
        if folder in FOLDER_KINDS:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            texts[key] = text
            title = parse_frontmatter(text).get("title") or key.split("/")[-1]
            g.pages[key] = {"title": str(title), "kind": FOLDER_KINDS[folder]}
        elif folder == "sources":
            try:
                texts[key] = path.read_text(encoding="utf-8")
            except OSError:
                continue
    # исходящие ссылки: из Obsidian (как он их разрешил) или из текста страниц
    outgoing: dict[str, list[str]] = {}
    if resolved_links:
        for src, targets in resolved_links.items():
            if not src.startswith("wiki/"):
                continue
            key = src.removeprefix("wiki/").removesuffix(".md")
            outgoing[key] = [t.removeprefix("wiki/").removesuffix(".md") for t in targets if t.endswith(".md")]
    for key, text in texts.items():
        if key not in outgoing:
            outgoing[key] = []
            for target in LINK_RE.findall(FM_RE.sub(lambda m: m.group(0), text)):
                r = _resolve(target, files, by_name)
                if r:
                    outgoing[key].append(r)
                else:
                    t = target.strip().removesuffix(".md")
                    folder = t.split("/")[0]
                    if folder in FOLDER_KINDS:              # «[[concepts/X]]» без страницы — возможная страница
                        g.missing[t].add(key)
    for src, targets in outgoing.items():
        for dst in targets:
            if dst == src or any(dst.startswith(s) for s in SKIP):
                continue
            if dst not in g.pages:
                continue
            if src.startswith("sources/"):
                g.card_links[src].add(dst)
            elif src in g.pages:
                g.links.add((src, dst))
    return g


def load_via_cli(vault) -> dict | None:
    """resolvedLinks из запущенного Obsidian (через официальный CLI) или None."""
    cli = getattr(vault, "cli", None)
    if not cli:
        return None
    out = cli("eval", "code=JSON.stringify(app.metadataCache.resolvedLinks)", timeout=15)
    if not out:
        return None
    try:
        data = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return data if isinstance(data, dict) else None


# --- возможные теги: общие слова книг, которые ещё не стали тегами

STOP = set("""
и в во на по с со к ко о об от до из за для при про без над под или но а же ли не ни что как это то так
все всё его её их они она оно мы вы ты я быть был была были есть будет книга книги книге руководство
издание том часть глава введение основы основ полное практическое практика самоучитель новое новая
как-то когда где кто чем тем этот эта эти тот та те свой своя свои очень более менее также уже ещё
the a an and or of for to in on with by from at as is are be this that these those your you we our
book books guide introduction edition handbook vol volume part chapter new using how what why
have has had such other many which more most some any each than then them their there here into over
under also only very can could would should will may might must been being were was its it's not
about after before between through while where when who whom whose both all one two three first second
paper papers present presents presented propose proposed approach approaches method methods based
work works result results show shows shown use used uses study studies problem problems well large
high low make makes made provide provides set sets way ways part parts like even much
суть ключевые идеи связи заметки аннотация источник
slides slide lecture lectures notes course courses research university institute department school
microsoft google intel ibm johns hopkins draft version preprint report technical tutorial tutorials
лекция лекции курс слайды доклад конспект efficient fast applications application
epub pdf fb2 mobi djvu zip txt docx pptx полный полная полное базовый базовые
самому самой самим себя себе собой свою своей своих ваша ваш вашей вашу ваши наш наша нам вам тебя тебе
люди людей людям человек человека жизни жизнь каждый каждого всегда никогда можно нужно надо
""".split())


def stem(word: str) -> str:
    """Грубая основа слова: без частых окончаний (русские и английские), чтобы «квантование» и
    «квантования» считались одним словом."""
    w = word.lower().replace("ё", "е")
    if re.search(r"[а-я]", w):
        for end in ("ированию", "ирование", "ования", "ование", "ениями", "ениях", "ениям", "ением", "ения",
                    "ение", "ости", "ость", "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя",
                    "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ых", "их", "ов", "ев", "ам", "ям", "ах", "ях",
                    "а", "я", "ы", "и", "е", "у", "ю", "о"):
            if w.endswith(end) and len(w) - len(end) >= 4:
                return w[: -len(end)]
        return w
    for end in ("ations", "ation", "ings", "ing", "ies", "es", "ed", "s"):
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[: -len(end)]
    return w


WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{3,}")


def _terms(text: str) -> list[tuple[str, str]]:
    """(основа, слово) и пары соседних значимых слов (их основы через пробел) — «data structures»."""
    words = []
    for w in WORD_RE.findall(text):
        lw = w.lower()
        if lw in STOP or (w.isupper() and len(w) > 6):
            words.append(None)                           # стоп-слово разрывает пару
            continue
        st = stem(w)
        words.append(None if st in STOP or len(st) < 4 else (st, lw))
    out = [x for x in words if x]
    out += [(f"{a[0]} {b[0]}", f"{a[1]} {b[1]}") for a, b in zip(words, words[1:]) if a and b]
    return out


def suggest_tags(texts: dict[str, str], existing: list[str], min_books=2, limit=25) -> list[tuple[str, list[str]]]:
    """texts: {id книги: название, суть, ключевые идеи}. Слова и пары слов, общие для min_books+ книг, но
    не у всех подряд (не больше 15%), которых нет среди тегов и страниц (existing — их подписи).
    → [(подпись, [id книг])]: пары и более редкие слова — выше (они конкретнее)."""
    taken = {stem(w) for label in existing for w in WORD_RE.findall(label)}
    taken |= {" ".join(stem(w) for w in WORD_RE.findall(label)) for label in existing}
    books_by: dict[str, set[str]] = defaultdict(set)
    forms: dict[str, Counter] = defaultdict(Counter)
    for bid, text in texts.items():
        for st, form in _terms(text):
            books_by[st].add(bid)
            forms[st][form] += 1
    n = max(1, len(texts))
    cap = max(min_books + 1, int(n * 0.15))        # в маленькой библиотеке 15% — слишком строго
    out = []
    for st, bids in books_by.items():
        if st in taken or not (min_books <= len(bids) <= cap):
            continue
        if " " in st and any(part in taken for part in st.split()):
            continue                                     # «квантование llm» при теге «квантование» — лишнее
        out.append((st, forms[st].most_common(1)[0][0], sorted(bids)))
    # пары с одним и тем же набором книг и общим словом («современных десктопных» и «десктопных
    # процессоров») — одна фраза, оставляем одну пару
    seen_sets: dict[tuple, set[str]] = {}
    kept = []
    for x in sorted(out, key=lambda x: -len(x[0])):
        key = tuple(x[2])
        words = set(x[0].split())
        if " " in x[0] and key in seen_sets and seen_sets[key] & words:
            continue
        if " " in x[0]:
            seen_sets.setdefault(key, set()).update(words)
        kept.append(x)
    out = kept
    # пара, покрывающая те же книги, что и её слово, — понятнее слова: слово убираем
    pairs = [x for x in out if " " in x[0]]
    drop = {w for p in pairs for w in p[0].split() for x in out if x[0] == w and set(x[2]) <= set(p[2]) | set()}
    out = [x for x in out if x[0] not in drop]
    out.sort(key=lambda x: (-(" " in x[0]), -len(x[2]), x[1]))
    return [(label, bids) for _st, label, bids in out[:limit]]


def card_text(path: Path, limit=1500) -> str:
    """Название, «Суть» и «Ключевые идеи» карточки — для поиска общих слов (сырые аннотации из PDF шумят)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    props = parse_frontmatter(text)
    body = FM_RE.sub("", text)
    parts = re.findall(r"^## (?:Суть|Ключевые идеи)\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    clean = re.sub(r"\[\[[^\]]*\]\]", " ", " ".join(parts))
    return f"{props.get('title', '')}\n{clean}"[:limit]
