"""Хранилище Obsidian: карточки, свойства, теги, страница выделений, журнал, CLI (поддельный)."""
import stat
from types import SimpleNamespace

from muninhall import folder_scan, vault
from muninhall.highlights import HighlightStore
from muninhall.model import Library
from muninhall.obsidian import BLOCK_END, BLOCK_START, ObsidianExport
from tests.test_folder_library import bid_of, make_lib

CARD = """---
type: source
kind: book
title: "B"
file: "Books/sub/b.pdf"
status: indexed
created: 2026-10-08
updated: 2026-10-08
---
# B

#ml/сжатие в тексте
"""


def make_vault(tmp_path):
    root = tmp_path / "vault"
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("схема")
    (root / "wiki" / "log.md").write_text("# Журнал\n\n## [2026-10-08] index | Каталог\n")
    (root / "wiki" / "sources" / "B.md").write_text(CARD)
    return root


def setup(tmp_path):
    root = make_vault(tmp_path)
    folder = make_lib(root / "Books")
    lib = Library()
    folder_scan.scan_folders(lib, [folder])
    book = lib.books[bid_of(lib, "sub/b.pdf")]
    app = SimpleNamespace(settings={"obsidianVault": str(root), "obsidianExport": True}, library=lib)
    app.highlights = HighlightStore(lib)
    return root, app, book


def test_file_vault_cards_props_tags(tmp_path):
    root, app, book = setup(tmp_path)
    v = vault.connect(app.settings)
    assert v.kind in ("files", "cli")
    v = vault.FileVault(root)
    card = v.find_card(app.library.file_path(book))
    assert card == root / "wiki" / "sources" / "B.md" and v.card_link(card) == "[[sources/B]]"
    v.set_props(card, tags=["ml/сжатие", "книги"], status="read")
    text = card.read_text()
    assert 'title: "B"' in text and "created: 2026-10-08" in text        # прочие строки как были
    assert v.card_props(card)["tags"] == ["ml/сжатие", "книги"] and v.card_props(card)["status"] == "read"
    assert v.all_tags()[0] == "ml/сжатие"                                  # из шапки и из текста — 2 раза
    assert v.find_card(tmp_path / "elsewhere.pdf") is None


def test_export_highlights_page_keeps_user_text(tmp_path):
    root, app, book = setup(tmp_path)
    ex = ObsidianExport(app)
    h1 = app.highlights.add(book, section=2, text="Первая  цитата", color="advice", chapter="Глава 1",
                            note="применить завтра")
    app.highlights.add(book, section=5, text="Вторая", color="question", chapter="Глава 2")
    ex.export_pending()
    page = root / "wiki" / "highlights" / "B.md"
    text = page.read_text()
    props = vault.parse_frontmatter(text)
    assert props["type"] == "highlights" and props["sources"] == ["[[sources/B]]"]
    assert props["file"] == "Books/sub/b.pdf"
    assert "> Первая цитата" in text and "#совет" in text and "#вопрос" in text and "применить завтра" in text
    assert f"muninhall://open?book={book['id']}&hl={h1['id']}" in text
    assert text.index("## Глава 1") < text.index("## Глава 2")
    # свои мысли пользователя вне блока сохраняются при следующей выгрузке
    page.write_text(text.replace(BLOCK_START, "Мои мысли о книге\n\n" + BLOCK_START) + "\nПосле блока\n")
    app.highlights.remove(book, h1["id"])
    ex.export_pending()
    text = page.read_text()
    assert "Мои мысли о книге" in text and "После блока" in text and "Первая" not in text and "Вторая" in text
    assert text.count(BLOCK_START) == 1 and text.count(BLOCK_END) == 1
    log = (root / "wiki" / "log.md").read_text()
    assert log.count("highlights | B") == 1 and log.endswith("highlights | B\n")
    assert "## [2026-10-08] index | Каталог" in log                     # журнал только дописан
    assert ex.export_book(book) is False                                  # ничего не изменилось


def test_reading_status_goes_to_card(tmp_path, monkeypatch):
    root, app, book = setup(tmp_path)
    monkeypatch.setattr(vault, "in_background", lambda fn, *a, **k: fn(*a, **k))
    ex = ObsidianExport(app)
    card = root / "wiki" / "sources" / "B.md"
    ex.on_reading(book)
    assert vault.parse_frontmatter(card.read_text())["reading"] is True
    ex.on_finished(book, True)
    props = vault.parse_frontmatter(card.read_text())
    assert props["status"] == "read" and "reading" not in props
    ex.on_reading(book)                                                   # прочитанную не трогаем
    assert "reading" not in vault.parse_frontmatter(card.read_text())
    ex.on_finished(book, False)
    assert vault.parse_frontmatter(card.read_text())["status"] == "indexed"
    assert ex.set_book_tags(book, ["#ml/сжатие ", "свои заметки", "ml/сжатие"])
    assert ex.book_tags(book) == ["ml/сжатие", "свои-заметки"]


def test_cli_vault_uses_obsidian_cli(tmp_path, monkeypatch):
    root, app, book = setup(tmp_path)
    calls = tmp_path / "calls.txt"
    fake = tmp_path / "obsidian"
    fake.write_text(f"""#!/bin/sh
printf '%s\\n' "$*" >> {calls}
case "$2" in
  tags) echo '[{{"tag": "#проекты/ии", "count": 3}}, {{"tag": "#ml", "count": 1}}]' ;;
  property:set) exit 0 ;;
  *) exit 1 ;;
esac
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(vault, "find_cli", lambda: [str(fake)])
    monkeypatch.setattr(vault, "obsidian_running", lambda: True)
    v = vault.connect(app.settings)
    assert v.kind == "cli" and vault.status(app.settings)[0] == "cli"
    assert v.all_tags() == ["проекты/ии", "ml"]
    card = v.find_card(app.library.file_path(book))
    v.set_props(card, tags=["a", "b"], reading=True)
    log = calls.read_text()
    assert "vault=vault property:set name=tags value=a, b type=list path=wiki/sources/B.md" in log
    assert "name=reading value=true type=checkbox" in log
    assert card.read_text() == CARD                       # CLI справился — файл приложение не трогало
    monkeypatch.setattr(vault, "obsidian_running", lambda: False)
    assert vault.connect(app.settings).kind == "files" and vault.status(app.settings)[0] == "cli-closed"


def test_focus_page_in_wiki(tmp_path):
    from muninhall.focus import FocusStore
    root, app, book = setup(tmp_path)
    book["tags"] = ["квантование"]
    app.focus = FocusStore(app.library, path=tmp_path / "focus.json")
    ex = ObsidianExport(app)
    app.focus.set_focus("Квантование", [("tag", "квантование")])
    ex.export_focus()
    page = root / "wiki" / "plans" / "Фокус — Квантование.md"
    text = page.read_text()
    props = vault.parse_frontmatter(text)
    assert props["type"] == "plan" and props["horizon"] == "focus" and props["status"] == "active"
    assert "[[sources/B|" in text and "прочитано 0 из 1" in text and "## Дальше (по релевантности)" in text
    assert (root / "wiki" / "log.md").read_text().count("plan | Фокус — Квантование") == 1
    app.focus.set_focus("Другое", [("tag", "квантование")], replace=app.focus.active["id"])   # замена фокуса
    ex.export_focus()
    assert vault.parse_frontmatter(page.read_text())["status"] == "archived"
    assert vault.parse_frontmatter((root / "wiki" / "plans" / "Фокус — Другое.md").read_text())["status"] == "active"
