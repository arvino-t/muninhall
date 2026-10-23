"""Выделения на установленной сборке: EPUB и PDF, подсветка, повторное открытие, выгрузка, ссылка.

Запуск — через tools/flow_check.sh (временный профиль с копией данных):
    bash tools/flow_check.sh highlights
Хранилище Obsidian — временная папка VAULT (карточки нужных книг копируются туда из настоящего
хранилища); настоящая вики и `.library` папок книг не меняются.
"""
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

STORES = Path(sys.argv[1])
REAL_VAULT = Path(sys.argv[2])            # настоящее хранилище (~/Documents) — только читаем
VAULT = STORES.parent / "vault"

import muninhall.core as core  # noqa: E402

core.folder_store_dir = lambda root, lib_id, create=False: (STORES / lib_id)
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox  # noqa: E402

import muninhall.app as A  # noqa: E402
from muninhall import vault as vault_mod  # noqa: E402

# Пути книг считаем от настоящего хранилища (книги лежат там), а страницы пишем во временное
vault_mod.FileVault.rel_of = lambda self, p: (Path(p).resolve().relative_to(REAL_VAULT.resolve()).as_posix()
                                             if Path(p).resolve().is_relative_to(REAL_VAULT.resolve()) else None)
errors = []
sys.excepthook = lambda *e: (errors.append(1), print("EXC", "".join(traceback.format_exception(*e))))
QMessageBox.exec = lambda self: 0
QMenu.exec = lambda self, *a, **k: None
QMenu.popup = lambda self, *a, **k: None
QDialog.exec = lambda self: (QTimer.singleShot(0, self.accept), 1)[1]
results = []
holder = {}


def stage(name):
    print(f"  · {name}", flush=True)


def ok(name, cond, extra=""):
    results.append(f"{'ok  ' if cond else 'FAIL'} {name}" + (f" — {extra}" if extra else ""))


def js(code, cb):
    holder["a"].reader.page.runJavaScript(code, 0, cb)


SELECT = """(() => {
  // PDF показывается разворотом: первая страница бывает пустой (about:blank) — берём документ с текстом
  const cs = document.querySelector('foliate-view').renderer.getContents()
  const c = cs.find(x => x.doc?.body?.textContent.trim().length > 20) ?? cs[0]
  const doc = c.doc
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  let n
  for (n = walker.nextNode(); n; n = walker.nextNode()) if (n.nodeValue.trim().length > 12) break
  if (!n) return 'no text'
  const r = doc.createRange()
  const start = n.nodeValue.search(/\\S/)
  r.setStart(n, start); r.setEnd(n, Math.min(n.nodeValue.trimEnd().length, start + 30))
  const sel = doc.getSelection(); sel.removeAllRanges(); sel.addRange(r)
  doc.dispatchEvent(new Event('selectionchange'))
  return r.toString()
})()"""
CLICK_DOT = """(() => { const d = document.querySelectorAll('#hl-bar .dot')[%d];
  if (!d) return 'no bar'; d.dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); return 'clicked' })()"""
PAINTED = """(() => { const out = []
  for (const c of document.querySelector('foliate-view').renderer.getContents())
    for (const k of ['important', 'advice', 'concept', 'question'])
      if (c.doc.defaultView.CSS.highlights.has('mh-' + k))
        out.push(k + ':' + c.doc.defaultView.CSS.highlights.get('mh-' + k).size)
  return out.join(',') })()"""


def scenario():
    a = holder["a"]
    books = a.library.ordered()

    def pick(fmt):
        """Своя книга этого формата; с карточкой в вики — если такая есть."""
        own = [b for b in books if b.get("format") in (fmt, "ios." + fmt) and a.library.file_path(b)]
        return next((b for b in own if a.obsidian.card_of(b)[0] is not None), own[0] if own else None)
    epub, pdf = pick("epub"), pick("pdf")
    with_card = [b for b in (epub, pdf) if b and a.obsidian.card_of(b)[0] is not None]
    ok("книги для проверки", epub and pdf, f"epub={epub and epub['title'][:30]} pdf={pdf and pdf['title'][:30]}, "
       f"с карточкой: {len(with_card)}")
    yield 0
    for book, color_idx in ((epub, 1), (pdf, 3)):
        if not book:
            continue
        name = book["format"]
        a.open_book(book, a.library.file_path(book))
        yield 9000                                  # книга открылась и встала на место
        if name == "epub":                          # первая страница бывает обложкой-картинкой — уходим к тексту
            a.reader.js("window.reader.goToFraction(0.06)")
            yield 3000
        state = {}
        js(SELECT, lambda r: state.update(sel=r))
        yield 900
        js(CLICK_DOT % color_idx, lambda r: state.update(click=r))
        yield 1200
        hs = a.highlights.for_book(book)
        want = "advice" if color_idx == 1 else "question"
        ok(f"{name}: выделение сохранено", len(hs) == 1 and hs[0]["color"] == want,
           f"выделено «{state.get('sel')}», {state.get('click')}, записей {len(hs)}")
        js(PAINTED, lambda r: state.update(painted=r))
        yield 600
        shots = os.environ.get("HL_SHOTS")
        if shots:                                       # снимок окна: подсветка видна?
            a.window.grab().save(f"{shots}/{name}-highlight.png")
            js(SELECT, lambda r: None)                  # и панель цветов над новым выделением
            yield 900
            a.window.grab().save(f"{shots}/{name}-bar.png")
            js("document.querySelector('foliate-view').renderer.getContents()"
               ".forEach(c => c.doc?.getSelection()?.removeAllRanges())", lambda r: None)
            yield 300
        ok(f"{name}: подсветка нарисована", bool(state.get("painted")), state.get("painted") or "нет")
        if not state.get("painted"):
            js("window.reader.debugHighlights()", lambda r: None)
            yield 1500
            js("window.__hlDebug", lambda r: print("  диагностика:", r, flush=True))
            yield 500
        if hs:
            stage("меню выделения")
            a.reader.highlights.on_menu({"id": hs[0]["id"]})            # меню строится без ошибок
            stage("окно заметки")
            a.reader.highlights.edit_note(hs[0]["id"])                  # окно заметки (принимается сразу)
            stage("заметка закрыта")
            a.highlights.update(book, hs[0]["id"], note="проверка заметки")
            a.reader.highlights.fill()
            ok(f"{name}: список выделений", a.reader.highlights.list.count() == 1)
        stage("назад")
        a.go_back()
        yield 800
        stage("открываю снова")
        a.open_book(book, a.library.file_path(book))                  # снова: подсветка находится заново
        yield 9000
        js(PAINTED, lambda r: state.update(again=r))
        yield 600
        ok(f"{name}: подсветка после повторного открытия", bool(state.get("again")), state.get("again") or "нет")
        if hs:
            a.go_back()
            yield 500
            a.open_link(f"muninhall://open?book={book['id']}&hl={hs[0]['id']}")
            yield 9000
            ok(f"{name}: ссылка muninhall:// открыла книгу", a.reader is not None and a.reader.book["id"] == book["id"])
        a.go_back()
        yield 800
    a.obsidian.export_pending()
    pages = sorted((VAULT / "wiki" / "highlights").glob("*.md"))
    ok("страницы в хранилище", len(pages) == 2, ", ".join(p.name[:40] for p in pages))
    if pages:
        text = pages[0].read_text()
        with_src = [p.read_text() for p in pages if "sources:" in p.read_text()]
        ok("на странице цитата, заметка и ссылка", "> " in text and "проверка заметки" in text
           and "muninhall://open" in text, f"страниц со ссылкой на карточку: {len(with_src)}")
    log = (VAULT / "wiki" / "log.md").read_text()
    ok("запись в журнале", log.count("highlights |") == len(pages))
    if with_card:
        a.set_finished(with_card[0], True)
        yield 1500
        card = a.obsidian.card_of(with_card[0])[0]
        ok("«Прочитано» → status: read", vault_mod.parse_frontmatter(card.read_text()).get("status") == "read")
    yield 0


def run_steps():
    gen = scenario()

    def watchdog():                    # что-то повисло — печатаем то, что успели проверить
        results.append("FAIL сторожевой таймер: сценарий не закончился за 200 с")
        print("\n".join(results))
        print("uncaught:", len(errors))
        QApplication.instance().quit()
    QTimer.singleShot(200_000, watchdog)

    def step():
        try:
            delay = next(gen)
        except StopIteration:
            print("\n".join(results))
            print("uncaught:", len(errors))
            QApplication.instance().quit()
            return
        except Exception:
            results.append("FAIL сценарий\n" + traceback.format_exc())
            delay = None
        if delay is None:
            print("\n".join(results))
            QApplication.instance().quit()
            return
        QTimer.singleShot(delay, step)
    step()


class P(A.App):
    def __init__(self, q):
        # временное хранилище с копиями карточек книг из настоящего
        (VAULT / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
        (VAULT / "CLAUDE.md").write_text("temp")
        (VAULT / "wiki" / "log.md").write_text("# Журнал\n")
        for card in (REAL_VAULT / "wiki" / "sources").glob("*.md"):
            shutil.copy2(card, VAULT / "wiki" / "sources" / card.name)
        super().__init__(q)
        self.settings["obsidianVault"] = str(VAULT)
        self.settings["obsidianExport"] = True
        holder["a"] = self
        QTimer.singleShot(5000, run_steps)


A.App = P
A.main(["muninhall"])
print(json.dumps({"vault": str(VAULT)}))
