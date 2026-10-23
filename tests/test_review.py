"""«Просмотр дня»: выбор цитаты по сроку повторения, интервалы, выбор на весь день, отрывок из EPUB."""
import random
import zipfile
from datetime import date, timedelta

from muninhall import review
from muninhall.highlights import HighlightStore
from muninhall.model import Library

P = ("Это законченный абзац из середины книги, в котором автор подробно объясняет мысль, ради которой "
     "стоило открыть эту главу, и приводит пример из жизни, чтобы её было легче запомнить и применить.")


def make_epub(path, chapters=10):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/>'
                                             '</rootfiles></container>')
        items = "".join(f'<item id="c{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>'
                        for i in range(chapters))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(chapters))
        z.writestr("OEBPS/c.opf", f"<package><manifest>{items}</manifest><spine>{spine}</spine></package>")
        for i in range(chapters):
            body = "<h1>Глава</h1><p>Короткий.</p>" + (f"<p>Глава {i}. {P}</p>" if 2 <= i <= 7 else "<p>© ISBN 123</p>")
            z.writestr(f"OEBPS/ch{i}.xhtml", f"<html><head><style>p{{}}</style></head><body>{body}</body></html>")


def setup(tmp_path):
    lib = Library()
    epub = tmp_path / "book.epub"
    make_epub(epub)
    lib.books["b1"] = {"id": "b1", "source": "local", "format": "epub", "title": "Книга", "file": str(epub)}
    lib.order.append("b1")
    lib.file_path = lambda b: epub if b["id"] == "b1" else None
    hs = HighlightStore(lib)
    return lib, hs


def test_epub_passage_and_filters(tmp_path):
    lib, _hs = setup(tmp_path)
    p = review.epub_passage(tmp_path / "book.epub", random.Random(1))
    assert p and 2 <= p["section"] <= 7 and p["text"].startswith(f"Глава {p['section']}. Это законченный")
    assert review.good_passage(["коротко.", "© ISBN " + "x" * 200 + "."], random.Random(1)) is None


def test_mine_spaced_repetition(clean_data, tmp_path):
    lib, hs = setup(tmp_path)
    book = lib.books["b1"]
    old = hs.add(book, text="старое важное", color="important")
    advice = hs.add(book, text="совет", color="advice")
    r = review.DailyReview(lib, hs, path=tmp_path / "review.json")
    today = date(2026, 10, 24)
    first = r.mine(today)[1]
    assert first["id"] == advice["id"]                       # советы — первыми среди новых
    assert r.mine(today)[1]["id"] == advice["id"]            # весь день — тот же выбор
    assert r.answer(advice["id"], True, today) == 3 and r.data["mine"]["done"] == "remembered"
    tomorrow = today + timedelta(days=1)
    assert r.mine(tomorrow)[1]["id"] == old["id"]            # совет отложен на 3 дня, теперь другое
    assert r.answer(old["id"], False, tomorrow) == 1         # «Позже» — завтра
    day4 = today + timedelta(days=3)
    assert r.mine(day4)[1]["id"] in (advice["id"], old["id"])
    r.data["srs"][advice["id"]]["interval"] = 3
    assert r.answer(advice["id"], True, day4) == 8           # 3 × 2,5 ≈ 8
    r2 = review.DailyReview(lib, hs, path=tmp_path / "review.json")   # состояние сохраняется
    assert r2.data["srs"][advice["id"]]["interval"] == 8


def test_random_passage_saved_as_highlight(clean_data, tmp_path):
    lib, hs = setup(tmp_path)
    lib.status = lambda b: "reading"
    r = review.DailyReview(lib, hs, path=tmp_path / "review.json")
    today = date(2026, 10, 24)
    book, passage = r.random_passage(today)
    assert book["id"] == "b1" and "Это законченный" in passage["text"]
    assert r.random_passage(today)[1] is passage or r.random_passage(today)[1]["text"] == passage["text"]
    h = r.save_random()
    assert h["section"] == passage["section"] and h["text"] == passage["text"] and h["color"] == "important"
    assert r.save_random()["id"] == h["id"]                  # повторно не дублируется
    assert len(hs.for_book(book)) == 1
