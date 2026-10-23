"""Граф книг по тегам (как граф в Obsidian): книги и теги — узлы, связь «книга — тег» — ребро.

Теги: жанры и теги ЛитРес, ваши папки на ЛитРес, серии, авторы, папки своих книг и статей.
Рисует web/graph.html (d3-force + canvas), здесь — данные и страница приложения.
"""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import libraries, style
from .book_tags import book_labels, norm
from .core import SCHEME, STORE_GRAPH, folder_store_dir, load_json, save_json
from .reader import BridgePage, reader_profile
from .widgets import (HeaderBar, IconButton, LibraryScopeCombo)
from .i18n import tr, web_strings

# (вид тега, название, цвет, включён по умолчанию)
# Все виды связей включены по умолчанию; страницы вики (темы, понятия…) — из хранилища Obsidian
KINDS = (
    ("wiki", tr("Теги вики"), "#26a269", True),
    ("wtopic", tr("Темы вики"), "#c01c28", True),
    ("wconcept", tr("Понятия"), "#1a5fb4", True),
    ("wentity", tr("Сущности"), "#613583", True),
    ("wcompare", tr("Сравнения"), "#986a44", True),
    ("wsynth", tr("Синтез"), "#0b8e8e", True),
    ("wproject", tr("Проекты"), "#d4a20a", True),
    ("genre", tr("Жанры"), "#3584e4", True),
    ("folder", tr("Мои папки на ЛитРес"), "#e5a50a", True),
    ("topic", tr("Темы своих книг и статей"), "#c061cb", True),
    ("series", tr("Серии"), "#9141ac", True),
    ("tag", tr("Теги ЛитРес"), "#2ec27e", True),
    ("author", tr("Авторы"), "#e66100", True),
)
GHOST_COLOR = "#9a9996"


def in_scope(book, scope: str) -> bool:
    """scope: "all" — все библиотеки, "litres" — ЛитРес, иначе id своей библиотеки."""
    if scope == "all":
        return True
    if scope == "litres":
        return book.get("source") == "litres"
    return book.get("library") == scope


def build_graph(lib, scope: str = "all", wiki: dict | None = None, focus=None) -> dict:
    """Узлы и рёбра для всех видов тегов выбранной библиотеки; фильтрует уже страница.

    wiki — граф хранилища Obsidian: {"graph": WikiGraph, "cards": {id книги: «sources/Имя»},
    "texts": {id книги: текст карточки}} (см. wiki_graph.py)."""
    dark = style.is_dark()
    nodes, links, tags = [], [], {}

    def tag(kind, name, bid):
        name = (name or "").strip()
        if not name:
            return
        tid = f"{kind}:{name.lower()}"
        tags.setdefault(tid, {"id": tid, "kind": kind, "label": name})
        links.append({"source": bid, "target": tid})

    for book in lib.ordered():
        if not in_scope(book, scope):
            continue
        bid = book["id"]
        nodes.append(_book_node(lib, book, dark))
        for kind, name in sorted(book_labels(lib, book)):   # правила — в book_tags.py, общие с фокусом
            if kind != "wtopic":                     # темы вики — страницами со ссылками (_add_wiki)
                tag(kind, name, bid)

    pagelinks, ghosts, ghostlinks = [], [], []
    if wiki:
        _add_wiki(wiki, nodes, links, tags, pagelinks, ghosts, ghostlinks)
    focus_info = _mark_focus(focus, lib, nodes, tags) if focus is not None and focus.active else None
    return {
        "nodes": nodes + list(tags.values()),
        "links": links,
        "pagelinks": pagelinks,          # страница вики ↔ страница вики
        "ghosts": ghosts,                # возможные теги и страницы, которых ещё нет
        "ghostlinks": ghostlinks,
        "focus": focus_info,
        "kinds": [{"id": k, "label": label, "color": color, "on": on} for k, label, color, on in KINDS],
        "single": scope != "all",          # одна библиотека — переключатель «ЛитРес / Мои» не нужен
        "i18n": web_strings(),
        "theme": {
            "dark": dark,
            "accent": style.ACCENT,
            "bg": "#1d1d20" if dark else "#fafafb",
            "text": "#f0eff3" if dark else "#241f31",
            "link": "#7d7a86" if dark else "#a8a5b0",
        },
    }


def _book_node(lib, book, dark: bool) -> dict:
    """Узел книги: подпись, авторы, источник, процент; цвет — по статусу (читаю, прочитано, не начата)."""
    status = lib.status(book)
    color = {"reading": style.ACCENT, "finished": "#57e389" if dark else "#26a269"}.get(
        status, "#8f8d96" if dark else "#9a98a3")
    authors = book.get("authors") or []
    return {"id": book["id"], "kind": "book", "label": book.get("title") or book["id"], "status": status,
            "sub": ", ".join(authors[:2]) or book.get("collection", ""),
            "src": "mine" if book.get("source") in ("folder", "local") else "litres",
            "pct": lib.percent(book) or 0, "color": color}


def _mark_focus(focus, lib, nodes, tags) -> dict:
    """«Фокус»: его книги и теги отмечены на графе (кольцом); → {"name": названия активных фокусов}."""
    wanted = set().union(*(norm(f.get("labels") or []) for f in focus.actives))
    for n in nodes:
        if focus.contains(lib.books[n["id"]]):
            n["focus"] = True
    for t in tags.values():
        if (t["kind"], t["label"].lower()) in wanted:
            t["focus"] = True
    return {"name": " · ".join(f["name"] for f in focus.actives)}


class GraphPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.setObjectName("page")
        self.app = app
        self.ready = False
        self._layout_done = False
        self._fetch = None      # (готово, всего) — подгрузка жанров с ЛитРес
        app.litres_lib.details_progress.connect(self.set_fetch_progress)
        app.litres_lib.details_changed.connect(self.refresh)

        self.header = HeaderBar(app.window, tr("Граф книг"))
        back = IconButton("go-previous", tr("Назад"))
        back.clicked.connect(app.go_back)
        self.header.pack_start(back)
        # у каждой библиотеки свой граф; «Все» — общий
        self.scope = "all"
        self.scope_combo = LibraryScopeCombo(app.settings)
        self.scope_combo.scope_changed.connect(self.set_scope)
        self.header.pack_end(self.scope_combo)

        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.web = QWebEngineView(self)
        self.page = BridgePage(reader_profile(), self._on_message, self)
        self.web.setPage(self.page)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.web, 1)
        self.page.load(QUrl(f"{SCHEME}://app/graph.html"))
        self._sync_subtitle()

    def _data_js(self) -> str:
        return json.dumps(build_graph(self.app.library, self.scope, self._wiki(), getattr(self.app, "focus", None)),
                          ensure_ascii=False)

    def _wiki(self) -> dict | None:
        """Граф хранилища Obsidian и карточки книг выбранной библиотеки (None — хранилища нет)."""
        exporter = getattr(self.app, "obsidian", None)
        v = exporter.vault() if exporter else None
        if not v:
            return None
        from . import wiki_graph
        try:
            resolved = wiki_graph.load_via_cli(v) if v.kind == "cli" else None   # ссылки так, как видит Obsidian
            g = wiki_graph.load(v.root, resolved)
        except OSError:
            return None
        lib = self.app.library
        cards, texts = {}, {}
        for book in lib.ordered():
            if not in_scope(book, self.scope):
                continue
            card = v.find_card(lib.file_path(book), book.get("title"))
            if card:
                cards[book["id"]] = f"sources/{card.stem}"
                texts[book["id"]] = wiki_graph.card_text(card)
            else:
                texts[book["id"]] = book.get("title") or ""
        return {"graph": g, "cards": cards, "texts": texts}

    # --- выбор библиотеки и состояние графа по библиотекам

    def fill_scopes(self, scope=None):
        self.scope_combo.refill(scope if scope else self.scope)
        if self.scope_combo.scope() != self.scope:
            self.set_scope(self.scope_combo.scope())

    def set_scope(self, scope):
        self.scope = scope
        self._layout_done = False
        self._sync_subtitle()
        if self.ready:
            self.page.runJavaScript(f"window.graph.load({self._data_js()}, {json.dumps(self._load_state())})")

    def _state_file(self):
        """Своя библиотека — graph.json в её .library; ЛитРес и «Все» — в настройках."""
        lib = next((l for l in libraries.folder_libraries(self.app.settings) if l["id"] == self.scope), None)
        return folder_store_dir(lib["path"], lib["id"]) / STORE_GRAPH if lib else None

    def _load_state(self) -> dict:
        path = self._state_file()
        if path:
            return load_json(path, {})
        states = self.app.settings.get("graphStates") or {"all": self.app.settings.get("graph") or {}}
        return states.get(self.scope) or {}

    def _save_state(self, state):
        path = self._state_file()
        if path:
            try:
                save_json(path, state)
            except OSError:
                pass
            return
        states = dict(self.app.settings.get("graphStates") or {"all": self.app.settings.get("graph") or {}})
        states[self.scope] = state
        self.app.settings["graphStates"] = states
        self.app.save_settings()

    def _on_message(self, msg):
        t = msg.get("type")
        if t == "ready":
            self.ready = True
            self.page.runJavaScript(f"window.graph.load({self._data_js()}, {json.dumps(self._load_state())})")
        elif t == "open":
            self.app.on_book_activated(msg.get("id"))
        elif t == "state":
            self._save_state(msg.get("state") or {})
        elif t == "escape":
            self.app.go_back()
        elif t == "layout-done":
            self._layout_done = True
            self._sync_subtitle()
        elif t == "suggest":
            self._add_suggested_tag(msg.get("label") or "", msg.get("books") or [])
        elif t == "open-page":
            exporter = getattr(self.app, "obsidian", None)
            v = exporter.vault() if exporter else None
            if v and msg.get("page"):
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(v.obsidian_uri(msg["page"])))

    def _add_suggested_tag(self, label: str, book_ids: list[str]):
        """Предложенный тег — в карточки книг (вложенный тег можно поправить потом в «Теги…»)."""
        from .widgets import confirm
        exporter = self.app.wiki_cards
        books = [self.app.library.books[b] for b in book_ids if b in self.app.library.books]
        with_cards = [b for b in books if exporter.book_tags(b) is not None]
        tag = re.sub(r"\s+", "-", label.strip().lower())
        if not with_cards:
            self.app.toast(tr("У этих книг нет карточек в хранилище Obsidian"))
            return
        if not confirm(self.app.window, tr("Добавить тег?"), tr("<b>Добавить тег «{0}»?</b>", tag),
                       tr("Тег добавится в карточки {0} книг в вики (без карточки: {1}).",
                          len(with_cards), len(books) - len(with_cards)), tr("Добавить")):
            return
        for b in with_cards:
            current = exporter.book_tags(b) or []
            if tag not in current:
                exporter.set_book_tags(b, current + [tag])
        self.app.toast(tr("Тег «{0}» добавлен: {1} книг", tag, len(with_cards)))
        self.refresh()

    def set_fetch_progress(self, done: int, total: int):
        """Подгрузка жанров и тегов с ЛитРес: показываем в странице и в заголовке."""
        self._fetch = (done, total) if done < total else None
        if self.ready:
            if self._fetch:
                text = tr('Загружаю жанры и теги с ЛитРес: {0} из {1}', done, total)
                self.page.runJavaScript(f"window.graph.status({json.dumps(text)}, {done / total:.3f})")
            else:
                self.page.runJavaScript("window.graph.status(null)")
        self._sync_subtitle()

    def _sync_subtitle(self):
        parts = []
        if not self._layout_done:
            parts.append(tr("строю граф…"))
        if self._fetch:
            parts.append(tr('жанры с ЛитРес: {0} из {1}', self._fetch[0], self._fetch[1]))
        text = " · ".join(parts)
        self.header.set_title(tr("Граф книг"), text[:1].upper() + text[1:])

    def refresh(self):
        """Данные поменялись (подгрузились жанры, обновилась библиотека)."""
        self._layout_done = False
        self._sync_subtitle()
        if self.ready:
            self.page.runJavaScript(f"window.graph.update({self._data_js()})")


def _add_wiki(wiki, nodes, links, tags, pagelinks, ghosts, ghostlinks):
    """Страницы вики, связи книг с ними (через карточки), связи страниц между собой и возможные теги."""
    from . import wiki_graph
    g = wiki["graph"]
    book_ids = {n["id"] for n in nodes}
    used_pages = set()

    def page_node(key):
        info = g.pages[key]
        pid = f"{info['kind']}:{key}"
        tags.setdefault(pid, {"id": pid, "kind": info["kind"], "label": info["title"], "page": f"wiki/{key}.md"})
        used_pages.add(key)
        return pid

    for bid, card in wiki["cards"].items():
        if bid not in book_ids:
            continue
        for key in sorted(g.card_links.get(card, ())):
            links.append({"source": bid, "target": page_node(key)})
    for key in g.pages:                                  # страницы без книг тоже часть вики
        page_node(key)
    for src, dst in sorted(g.links):
        pagelinks.append({"source": page_node(src), "target": page_node(dst)})
    # возможные теги: общие слова книг, которых нет среди тегов и страниц
    existing = [t["label"] for t in tags.values()]
    texts = {bid: t for bid, t in wiki.get("texts", {}).items() if bid in book_ids}
    for label, bids in wiki_graph.suggest_tags(texts, existing, min_books=2, limit=25):
        gid = f"ghost:{label}"
        ghosts.append({"id": gid, "kind": "ghost", "label": label, "ghost": "tag", "color": GHOST_COLOR})
        ghostlinks += [{"source": bid, "target": gid} for bid in bids]
    # страницы, на которые ссылаются, но которых нет (кандидаты в понятия, сущности…)
    for target, sources in sorted(g.missing.items()):
        gid = f"ghost:{target}"
        ghosts.append({"id": gid, "kind": "ghost", "label": target.split("/")[-1], "ghost": "page",
                       "page": f"wiki/{target}.md", "color": GHOST_COLOR})
        for src in sorted(sources):
            if src in g.pages:
                ghostlinks.append({"source": page_node(src), "target": gid})
            else:                                        # ссылается карточка — связь от её книги
                ghostlinks += [{"source": bid, "target": gid} for bid, card in wiki["cards"].items()
                               if card == src and bid in book_ids]
