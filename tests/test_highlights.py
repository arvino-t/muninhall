"""Выделения: где хранятся, порядок, изменение и удаление, резервные копии."""
import json
import zipfile

from muninhall import backup, core, folder_scan
from muninhall.highlights import HighlightStore
from muninhall.model import Library
from tests.test_folder_library import bid_of, make_lib


def test_own_book_highlights_go_to_library_store(clean_data, tmp_path):
    folder = make_lib(tmp_path / "articles")
    lib = Library()
    folder_scan.scan_folders(lib, [folder])
    book = lib.books[bid_of(lib, "sub/b.pdf")]
    hs = HighlightStore(lib)
    seen = []
    hs.changed.connect(seen.append)
    late = hs.add(book, section=3, text="вторая", color="advice", fraction=0.5)
    early = hs.add(book, section=1, text="первая", color="nonsense", note=None)
    assert [h["text"] for h in hs.for_book(book)] == ["первая", "вторая"]       # порядок чтения
    assert early["color"] == "important" and early["note"] == ""
    assert seen == [book["id"], book["id"]]
    hs.update(book, late["id"], note="применить", color="question", id="hack")
    assert hs.get(book, late["id"])["note"] == "применить" and hs.get(book, late["id"])["id"] == late["id"]
    hs.flush()
    stored = json.loads((tmp_path / "articles" / ".library" / "highlights.json").read_text())
    assert [h["text"] for h in stored["books"]["sub/b.pdf"]] == ["вторая", "первая"]
    assert not core.HIGHLIGHTS_FILE.exists()                 # своё не уходит в данные приложения
    # после перезапуска (новая модель и хранилище) — те же выделения
    lib2 = Library()
    folder_scan.scan_folders(lib2, [folder])
    hs2 = HighlightStore(lib2)
    assert [h["text"] for h in hs2.for_book(lib2.books[book["id"]])] == ["первая", "вторая"]
    assert hs2.remove(lib2.books[book["id"]], early["id"]) and not hs2.remove(lib2.books[book["id"]], "нет")
    assert len(hs2.books_with_highlights()) == 1


def test_litres_highlights_and_backup(clean_data, tmp_path):
    lib = Library()
    lib.books["42"] = {"id": "42", "source": "litres", "title": "Книга"}
    hs = HighlightStore(lib)
    h = hs.add(lib.books["42"], text="цитата", color="concept")
    hs.flush()
    assert json.loads(core.HIGHLIGHTS_FILE.read_text())["books"]["42"][0]["id"] == h["id"]
    path = backup.create({"backupDir": str(tmp_path)}, scope="litres")
    assert "highlights.json" in zipfile.ZipFile(path).namelist()
    hs.remove(lib.books["42"], h["id"])
    hs.flush()
    assert json.loads(core.HIGHLIGHTS_FILE.read_text())["books"] == {}
