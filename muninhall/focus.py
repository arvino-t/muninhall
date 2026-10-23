"""«Фокус на развитии»: текущий приоритет в чтении.

Фокус — тема (название) и набор тегов: жанры, теги ЛитРес и вики, темы, серии, авторы; книги с этими тегами
попадают в фокус сами, отдельные можно добавить или исключить вручную. Активный фокус один, прежние — в
архиве. Фокус подсказывает следующую книгу (начатые, затем самые релевантные), похожие книги вне фокуса и —
чтобы не застрять в одной теме — предлагает закрепить знания и сменить фокус, когда прочитано достаточно.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter

from .core import DATA_DIR, load_json, save_json

FOCUS_FILE = DATA_DIR / "focus.json"
ENOUGH_DEFAULT = 5            # столько прочитанных книг обычно хватает, чтобы разобраться в теме
SHARE_ENOUGH = 0.7            # …или прочитана такая доля книг фокуса (если их хотя бы 3)

KIND_NAMES = ("genre", "tag", "wiki", "wtopic", "topic", "folder", "series", "author")


def book_labels(lib, book) -> set[tuple[str, str]]:
    """Теги книги как в графе: {(вид, подпись)}; вложенный тег вики «ml/сжатие» даёт и «ml»."""
    out = set()

    def add(kind, name):
        name = (name or "").strip()
        if name:
            out.add((kind, name))
    for g in book.get("genres") or []:
        add("genre", g)
    for t in book.get("tags") or []:
        add("tag", t)
    for t in book.get("vault_tags") or []:
        parts = t.split("/")
        for i in range(1, len(parts) + 1):
            add("wiki", "/".join(parts[:i]))
    add("wtopic", book.get("vault_topic"))
    for fid in book.get("folders") or []:
        add("folder", lib.folders.get(fid))
    if book.get("series"):
        add("series", book["series"].get("name"))
    for a in book.get("authors") or []:
        add("author", a)
    if book.get("collection"):
        parts = [p.strip() for p in book["collection"].split("/") if p.strip()]
        add("topic", parts[1] if len(parts) > 1 else parts[0])
    return out


def norm(labels) -> set[tuple[str, str]]:
    """Для сравнения — без регистра."""
    return {(k, n.lower()) for k, n in labels}


class FocusStore:
    def __init__(self, library, path=FOCUS_FILE):
        self.library = library
        self.path = path
        self.data = load_json(path, {})
        self.data.setdefault("items", {})

    def save(self):
        save_json(self.path, self.data)

    # --- фокусы

    @property
    def active(self) -> dict | None:
        return self.data["items"].get(self.data.get("active"))

    def archive(self) -> list[dict]:
        return sorted((f for fid, f in self.data["items"].items() if fid != self.data.get("active")),
                      key=lambda f: -(f.get("updated") or 0))

    def set_focus(self, name: str, labels, enough: int = ENOUGH_DEFAULT, fid: str | None = None) -> dict:
        """Создать фокус (или изменить fid) и сделать его активным; прежний активный — в архив."""
        now = time.time()
        item = self.data["items"].get(fid) if fid else None
        if item is None:
            item = {"id": uuid.uuid4().hex[:10], "created": now, "include": [], "exclude": []}
            self.data["items"][item["id"]] = item
        item.update(name=name.strip() or "—", labels=sorted([list(x) for x in set(map(tuple, labels))]),
                    enough=max(1, int(enough)), updated=now, status="active")
        prev = self.active
        if prev and prev is not item:
            prev["status"] = "archived"
            prev["archived"] = now
        self.data["active"] = item["id"]
        self.save()
        return item

    def activate(self, fid: str):
        if fid in self.data["items"]:
            prev = self.active
            if prev:
                prev["status"] = "archived"
                prev["archived"] = time.time()
            self.data["active"] = fid
            self.data["items"][fid]["status"] = "active"
            self.save()

    def finish(self, done: bool = True):
        """Закончить активный фокус (в архив как пройденный или отложенный)."""
        f = self.active
        if f:
            f["status"] = "done" if done else "archived"
            f["archived"] = time.time()
            self.data["active"] = None
            self.save()

    def delete(self, fid: str):
        self.data["items"].pop(fid, None)
        if self.data.get("active") == fid:
            self.data["active"] = None
        self.save()

    def toggle_book(self, book, inside: bool):
        """Книгу — в фокус или из фокуса вручную (поверх тегов)."""
        f = self.active
        if not f:
            return
        bid = book["id"]
        f["include"] = [b for b in f["include"] if b != bid]
        f["exclude"] = [b for b in f["exclude"] if b != bid]
        if inside and not self._matches(f, book):
            f["include"].append(bid)
        elif not inside and self._matches(f, book):
            f["exclude"].append(bid)
        f["updated"] = time.time()
        self.save()

    # --- книги фокуса

    def _matches(self, f, book) -> bool:
        return bool(norm(book_labels(self.library, book)) & norm(f.get("labels") or []))

    def contains(self, book, f: dict | None = None) -> bool:
        f = f or self.active
        if not f:
            return False
        if book["id"] in f.get("exclude", []):
            return False
        return book["id"] in f.get("include", []) or self._matches(f, book)

    def books(self, f: dict | None = None) -> list[dict]:
        f = f or self.active
        return [b for b in self.library.ordered() if self.contains(b, f)] if f else []

    def score(self, book, f: dict, finished_labels: Counter) -> float:
        """Релевантность книги фокусу: совпавшие теги фокуса и общие теги с уже прочитанными книгами фокуса."""
        labels = norm(book_labels(self.library, book))
        own = len(labels & norm(f.get("labels") or []))
        near = sum(finished_labels[x] for x in labels) / max(1, sum(finished_labels.values()) ** 0.5)
        return own * 3 + near + (5 if book["id"] in f.get("include", []) else 0)

    def progress(self, f: dict | None = None) -> dict:
        """{"total", "finished", "reading", "unread", "next": книга или None, "enough": bool}."""
        f = f or self.active
        books = self.books(f)
        st = {"finished": [], "reading": [], "unread": []}
        for b in books:
            st[self.library.status(b)].append(b)
        finished_labels = Counter(x for b in st["finished"] for x in norm(book_labels(self.library, b)))
        recent = {b["id"]: i for i, b in enumerate(self.library.recent(50))}
        nxt = None
        if st["reading"]:
            nxt = min(st["reading"], key=lambda b: recent.get(b["id"], 999))
        elif st["unread"]:
            nxt = max(st["unread"], key=lambda b: self.score(b, f, finished_labels))
        n_fin, total = len(st["finished"]), len(books)
        enough = bool(f) and (n_fin >= f.get("enough", ENOUGH_DEFAULT)
                              or (total >= 3 and n_fin / total >= SHARE_ENOUGH))
        return {"total": total, "finished": n_fin, "reading": len(st["reading"]), "unread": len(st["unread"]),
                "next": nxt, "enough": enough, "books": books}

    def ranked(self, f: dict | None = None, limit: int = 0) -> list[dict]:
        """Непрочитанные книги фокуса по релевантности (начатые первыми)."""
        f = f or self.active
        if not f:
            return []
        books = [b for b in self.books(f) if self.library.status(b) != "finished"]
        fin = Counter(x for b in self.books(f) if self.library.status(b) == "finished"
                      for x in norm(book_labels(self.library, b)))
        books.sort(key=lambda b: (self.library.status(b) != "reading", -self.score(b, f, fin)))
        return books[:limit] if limit else books

    def related(self, limit: int = 3) -> list[dict]:
        """Похожие книги вне фокуса: больше всего общих тегов с книгами фокуса (не прочитанные)."""
        f = self.active
        if not f:
            return []
        inside = self.books(f)
        common = Counter(x for b in inside for x in norm(book_labels(self.library, b)))
        out = []
        for b in self.library.ordered():
            if self.contains(b, f) or self.library.status(b) == "finished" or b.get("id") in f.get("exclude", []):
                continue
            s = sum(common[x] for x in norm(book_labels(self.library, b)))
            if s >= 2:
                out.append((s, b))
        out.sort(key=lambda x: -x[0])
        return [b for _s, b in out[:limit]]

    def next_topics(self, limit: int = 3) -> list[tuple[str, str, int]]:
        """Кандидаты в следующий фокус: теги, у которых больше всего непрочитанных книг, кроме текущего фокуса
        и прежних фокусов. → [(вид, подпись, книг)]."""
        used = set()
        for f in self.data["items"].values():
            used |= norm(f.get("labels") or [])
        in_focus = {b["id"] for b in self.books()} if self.active else set()
        counts: Counter = Counter()
        overlap: Counter = Counter()                  # сколько книг темы уже в текущем фокусе
        all_books: Counter = Counter()
        shown: dict = {}
        for b in self.library.ordered():
            for kind, name in book_labels(self.library, b):
                if kind in ("author", "series"):
                    continue
                key = (kind, name.lower())
                if key in used:
                    continue
                all_books[key] += 1
                overlap[key] += b["id"] in in_focus
                if self.library.status(b) != "finished":
                    counts[key] += 1
                    shown[key] = name
        total = max(1, len(self.library.ordered()))
        # тема, большая часть книг которой уже в фокусе, — не смена фокуса, а то же самое
        return [(k, shown[(k, n)], c) for (k, n), c in counts.most_common(limit * 6)
                if 3 <= c <= total * 0.5 and overlap[(k, n)] <= all_books[(k, n)] * 0.3
                and overlap[(k, n)] <= len(in_focus) * 0.5][:limit]         # и не «зонтик» над фокусом

    def all_labels(self) -> list[tuple[str, str, int]]:
        """Все теги библиотеки с числом книг — для выбора в окне фокуса."""
        counts: Counter = Counter()
        shown: dict = {}
        for b in self.library.ordered():
            for kind, name in book_labels(self.library, b):
                counts[(kind, name.lower())] += 1
                shown[(kind, name.lower())] = name
        return [(k, shown[(k, n)], c) for (k, n), c in counts.most_common()]
