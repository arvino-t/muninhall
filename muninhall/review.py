"""«Просмотр дня»: одна ваша цитата (интервальное повторение) и один случайный отрывок из книги.

Выбор держится весь день (review.json в данных приложения) и меняется на следующий.
- Моя цитата — из выделений всех книг: сначала те, чей срок повторения подошёл, потом ещё не показанные.
  «Помню» — следующий показ через интервал ×2,5 (3, 8, 20… дней), «Позже» — завтра.
- Случайный отрывок — абзац из EPUB или PDF книги, которую читаете или прочитали; известен его раздел
  (для EPUB — элемент spine, для PDF — страница), поэтому его можно открыть в книге и сохранить как выделение.
"""
from __future__ import annotations

import html
import random
import re
import subprocess
import zipfile
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

from .core import DATA_DIR, load_json, log, save_json

REVIEW_FILE = DATA_DIR / "review.json"
PREFER = ("advice", "important", "concept", "question")     # советы и важное — в первую очередь


class _Paragraphs(HTMLParser):
    """Абзацы текста из XHTML главы."""

    def __init__(self):
        super().__init__()
        self.out, self.cur, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        if tag in ("p", "div", "br", "li", "blockquote", "h1", "h2", "h3"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        if tag in ("p", "div", "li", "blockquote", "h1", "h2", "h3"):
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if text:
            self.out.append(text)
        self.cur = []


def good_passage(paragraphs: list[str], rnd: random.Random) -> tuple[str, str, str] | None:
    """(отрывок, 32 знака до, 32 после): законченный абзац 160–600 знаков, не заголовок и не служебный текст."""
    cands = [i for i, p in enumerate(paragraphs) if 160 <= len(p) <= 600 and p[-1] in ".!?…»\"" and
             not re.search(r"©|ISBN|www\.|http|litres|ЛитРес", p, re.I)]
    if not cands:
        return None
    i = rnd.choice(cands)
    before = " ".join(paragraphs[max(0, i - 2):i])[-32:]
    after = " ".join(paragraphs[i + 1:i + 3])[:32]
    return paragraphs[i], before, after


def epub_passage(path: Path, rnd: random.Random) -> dict | None:
    try:
        with zipfile.ZipFile(path) as z:
            container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
            opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
            opf = z.read(opf_path).decode("utf-8", "ignore")
            base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
            manifest = {m.group(1): m.group(2) for m in
                        re.finditer(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf)}
            manifest.update({m.group(2): m.group(1) for m in
                             re.finditer(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
            spine = [manifest.get(m.group(1)) for m in re.finditer(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)]
            # середина книги: без обложки, оглавления и послесловий
            order = list(range(len(spine)))[len(spine) // 10: max(len(spine) // 10 + 1, len(spine) * 9 // 10)]
            rnd.shuffle(order)
            for index in order[:12]:
                href = spine[index]
                if not href:
                    continue
                try:
                    raw = z.read(base + html.unescape(href).split("#")[0]).decode("utf-8", "ignore")
                except KeyError:
                    continue
                parser = _Paragraphs()
                parser.feed(raw)
                parser._flush()
                found = good_passage(parser.out, rnd)
                if found:
                    return {"section": index, "text": found[0], "prefix": found[1], "suffix": found[2]}
    except (OSError, KeyError, AttributeError, zipfile.BadZipFile) as e:
        log("просмотр дня: EPUB не прочитан", path, e)
    return None


def pdf_passage(path: Path, rnd: random.Random) -> dict | None:
    try:
        info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=20).stdout
        pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        return None                                   # нет pdftotext/pdfinfo (например, Windows)
    pool = list(range(max(1, pages // 10), max(2, pages * 9 // 10)))
    rnd.shuffle(pool)
    for page in pool[:8]:
        try:
            text = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), str(path), "-"],
                                  capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        # абзацы PDF: строки, склеенные до пустой строки; переносы слов убираем
        text = re.sub(r"-\n(\w)", r"\1", text)
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
        found = good_passage(paras, rnd)
        if found:
            return {"section": page - 1, "text": found[0], "prefix": found[1], "suffix": found[2]}
    return None


class DailyReview:
    def __init__(self, library, highlights, path=REVIEW_FILE):
        self.library = library
        self.highlights = highlights
        self.path = path
        self.data = load_json(path, {})
        self.data.setdefault("srs", {})               # {id выделения: {"due", "interval", "shown"}}

    def save(self):
        save_json(self.path, self.data)

    # --- моя цитата

    def _all_highlights(self) -> list[tuple[dict, dict]]:
        return [(b, h) for b in self.highlights.books_with_highlights() for h in self.highlights.for_book(b)]

    def pick_mine(self, today: date) -> tuple[dict, dict] | None:
        items = self._all_highlights()
        if not items:
            return None
        srs = self.data["srs"]
        t = today.isoformat()

        def key(item):
            _book, h = item
            st = srs.get(h["id"])
            rank = PREFER.index(h.get("color")) if h.get("color") in PREFER else len(PREFER)
            if st is None:                            # ещё не показывали: после подошедших по сроку
                return (1, rank, -(h.get("created") or 0))
            if st["due"] <= t:
                return (0, st["due"], rank)
            return (2, st["due"], rank)
        return min(items, key=key)

    def mine(self, today: date | None = None) -> tuple[dict, dict] | None:
        """(книга, выделение) на сегодня."""
        today = today or date.today()
        day = self.data.get("day")
        if day == today.isoformat() and self.data.get("mine"):
            m = self.data["mine"]
            book = self.library.books.get(m["book"])
            h = self.highlights.get(book, m["hid"]) if book else None
            if h:
                return book, h
        picked = self.pick_mine(today)
        if picked:
            self._new_day(today)
            self.data["mine"] = {"book": picked[0]["id"], "hid": picked[1]["id"], "done": None}
            st = self.data["srs"].setdefault(picked[1]["id"], {"interval": 0, "due": today.isoformat()})
            st["shown"] = today.isoformat()
            self.save()
        return picked

    def answer(self, hid: str, remembered: bool, today: date | None = None) -> int:
        """«Помню» (интервал ×2,5) или «Позже» (завтра). → дней до следующего показа."""
        today = today or date.today()
        st = self.data["srs"].setdefault(hid, {"interval": 0})
        st["interval"] = max(3, round(st.get("interval", 0) * 2.5)) if remembered else 1
        st["due"] = (today + timedelta(days=st["interval"])).isoformat()
        if self.data.get("mine", {}).get("hid") == hid:
            self.data["mine"]["done"] = "remembered" if remembered else "later"
        self.save()
        return st["interval"]

    # --- случайный отрывок

    def candidates(self) -> list[dict]:
        """Книги для отрывка: начатые и прочитанные EPUB/PDF (если таких нет — любые скачанные)."""
        books = [b for b in self.library.ordered() if b.get("format") in ("epub", "ios.epub", "pdf")
                 and self.library.file_path(b) and not b.get("is_audio")]
        read = [b for b in books if self.library.status(b) in ("reading", "finished")]
        return read or books

    def random_passage(self, today: date | None = None) -> tuple[dict, dict] | None:
        """(книга, {"section", "text", "prefix", "suffix"}) на сегодня."""
        today = today or date.today()
        if self.data.get("day") == today.isoformat() and self.data.get("random"):
            r = self.data["random"]
            book = self.library.books.get(r["book"])
            if book:
                return book, r
        rnd = random.Random(today.toordinal())
        books = self.candidates()
        rnd.shuffle(books)
        for book in books[:6]:
            path = self.library.file_path(book)
            found = pdf_passage(path, rnd) if book.get("format") == "pdf" else epub_passage(path, rnd)
            if found:
                self._new_day(today)
                self.data["random"] = {"book": book["id"], **found}
                self.save()
                return book, self.data["random"]
        return None

    def _new_day(self, today: date):
        if self.data.get("day") != today.isoformat():
            self.data["day"] = today.isoformat()
            self.data.pop("mine", None)
            self.data.pop("random", None)

    def save_random(self) -> dict | None:
        """Случайный отрывок — в выделения книги (цвет «Важное»)."""
        r = self.data.get("random")
        book = self.library.books.get(r["book"]) if r else None
        if not book:
            return None
        if r.get("hid") and self.highlights.get(book, r["hid"]):
            return self.highlights.get(book, r["hid"])
        h = self.highlights.add(book, section=r["section"], text=r["text"], prefix=r["prefix"],
                                suffix=r["suffix"], color="important", note="", chapter="", fraction=None)
        r["hid"] = h["id"]
        self.save()
        return h
