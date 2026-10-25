"""Главное окно и логика приложения: библиотека, вход в ЛитРес, синхронизация, скачивание."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, backup, core, folder_scan, libraries, singularity, style
from .i18n import tr
from .core import (APP_ICON, APP_ID, APP_NAME, APP_SLUG, OLD_APP_IDS, AUDIO_FORMATS, READABLE, books_dir,
                   log, set_books_dir)
from .graph import GraphPage
from .settings import SettingsPage
from .litres import LitresSession
from .player import AudioPlayer, PlayerPage, audio_tracks
from .reader import ReaderPage
from .litres_connector import LitresConnector
from .singularity import SingularitySync
from .appearance import SHORTCUTS, Appearance
from .config import Settings
from .highlights import HighlightStore
from .focus_page import FocusPage
from .obsidian import HighlightPages, VaultLink
from .wiki_cards import WikiCards
from .focus import FocusStore
from .review import DailyReview
from .library import LibraryView
from .model import Library
from .widgets import confirm, HeaderBar, IconButton, label, Toast

EBOOK_PATTERNS = "*.epub *.fb2 *.fb2.zip *.fbz *.mobi *.azw3"


class EdgeGrip(QWidget):
    """Невидимая полоска у края окна без рамки: тянет окно системным растягиванием."""

    CURSORS = {
        Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
        Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, window, edges):
        super().__init__(window)
        self.edges = edges
        self.setCursor(self.CURSORS[edges])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.window().windowHandle().startSystemResize(self.edges)


class MainWindow(QMainWindow):
    """Окно без системной рамки: заголовок рисуем сами, края тянутся за невидимые полоски."""

    BORDER = 6

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.resize(1100, 760)
        E = Qt.Edge
        self._grips = [EdgeGrip(self, e) for e in (
            E.LeftEdge, E.RightEdge, E.TopEdge, E.BottomEdge,
            E.LeftEdge | E.TopEdge, E.RightEdge | E.TopEdge,
            E.LeftEdge | E.BottomEdge, E.RightEdge | E.BottomEdge)]

    def _place_grips(self):
        b, w, h = self.BORDER, self.width(), self.height()
        E = Qt.Edge
        rects = {
            E.LeftEdge: (0, b, b, h - 2 * b), E.RightEdge: (w - b, b, b, h - 2 * b),
            E.TopEdge: (b, 0, w - 2 * b, b), E.BottomEdge: (b, h - b, w - 2 * b, b),
            E.LeftEdge | E.TopEdge: (0, 0, b, b), E.RightEdge | E.TopEdge: (w - b, 0, b, b),
            E.LeftEdge | E.BottomEdge: (0, h - b, b, b), E.RightEdge | E.BottomEdge: (w - b, h - b, b, b),
        }
        resizable = not (self.isMaximized() or self.isFullScreen())
        for g in self._grips:
            g.setGeometry(*rects[g.edges])
            g.setVisible(resizable)
            g.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_grips()
        view = getattr(self.app, "library_view", None)
        if view is not None and hasattr(view, "recent_panel"):    # окно уже собрано
            view.update_recent_panel()
        for t in self.findChildren(Toast):
            t.reposition()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._place_grips()

    def closeEvent(self, e):
        self.app.on_close()
        super().closeEvent(e)


class App(QObject, Appearance):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.library_view = LibraryView(self)      # страница библиотеки
        self._init_data()
        self._init_theme()
        self._init_player()
        self._init_integrations()
        self._init_window()
        self._init_shortcuts()
        self._start()

    def _init_data(self):
        """Настройки, папка книг, модель библиотеки, автокопии, коннектор ЛитРес."""
        self.settings = Settings(parent=self)
        core.set_debug(self.settings.get("debugLog"))
        if libraries.ensure_registry(self.settings):      # первый запуск с библиотеками — перенос настроек
            self.settings.save_now()
        try:
            set_books_dir(self.settings.get("booksDir"))
        except OSError:
            # выбранная папка недоступна (например, отключён диск) — берём папку по умолчанию
            set_books_dir(None)
        self.library = Library()
        self.library.chars_per_min = int(self.settings.get("readingCharsPerMin") or 1300)
        # Выделения и заметки; выгрузка их, статуса чтения и тегов в хранилище Obsidian (второй мозг)
        self.highlights = HighlightStore(self.library, parent=self)
        # Хранилище Obsidian (второй мозг): связь, страницы выделений, свойства карточек книг
        self.obsidian = VaultLink(self.settings, self.library)
        self.highlight_pages = HighlightPages(self.obsidian, self.library, self.highlights, parent=self)
        self.wiki_cards = WikiCards(self.obsidian, self.library, parent=self)
        self.focus = FocusStore(self.library)                        # «Фокус»
        self.review = DailyReview(self.library, self.highlights, focus=self.focus)     # «Просмотр дня»
        self.focus_page = FocusPage(self.obsidian, self.library, self.focus, self.highlight_pages)
        self.wiki_cards.on_tags_loaded.append(self.on_focus_changed)  # теги вики: книги фокуса, граф
        # Автоматические резервные копии: проверка через минуту после запуска и раз в час
        self._backup_timer = QTimer(self, interval=3600_000)
        self._backup_timer.timeout.connect(self.auto_backup)
        self._backup_timer.start()
        QTimer.singleShot(60_000, self.auto_backup)
        self.litres_lib = LitresConnector(self)   # подключаемая библиотека ЛитРес
        self.reader: ReaderPage | None = None
        self.graph_page: GraphPage | None = None
        self.settings_page: SettingsPage | None = None
        self.player_page: PlayerPage | None = None
        self.net = QNetworkAccessManager(self)

    def _init_theme(self):
        """Тема и акцент: системные (портал) или свои из настроек."""
        style.read_portal_scheme()
        style.set_overrides(self.settings.get("uiTheme"), self.settings.get("accent"))
        style.apply_palette(self.qapp)
        self.qapp.styleHints().colorSchemeChanged.connect(self._on_theme_changed)
        # Портал не шлёт сигнал в Qt — проверяем смену темы и акцента раз в 2 секунды
        self._scheme = (style.is_dark(), style.ACCENT)
        self._theme_timer = QTimer(self, interval=2000)
        self._theme_timer.timeout.connect(self._poll_theme)
        self._theme_timer.start()

    def _init_player(self):
        self.player = AudioPlayer(self)
        self.player.finished.connect(self._on_audio_finished)
        self.player.error.connect(lambda msg: self.toast(tr('Ошибка воспроизведения: {0}', msg)))
        self.player.state_changed.connect(self._on_player_state)
        # Место прослушивания сохраняем раз в 5 секунд
        self._audio_timer = QTimer(self, interval=5000)
        self._audio_timer.timeout.connect(self.save_audio_progress)
        self._audio_timer.start()

    def _init_integrations(self):
        """Сессия ЛитРес и Singularity; учёт времени чтения."""
        self.litres = LitresSession(self)
        self.litres.state_changed.connect(self.litres_lib.on_login_state)

        # Singularity: задачи книг, прогресс, «Хочу прочитать», привычка «Чтение N минут»
        self.singularity = SingularitySync(self)
        self._last_activity = 0.0
        self._activity_timer = QTimer(self, interval=30_000)
        self._activity_timer.timeout.connect(self._count_reading_time)
        self._activity_timer.start()
        QTimer.singleShot(10_000, self.singularity.sync)

    def _init_window(self):
        self.window = MainWindow(self)
        self.apply_app_icon(self.settings.get("appIcon"))
        self.stack = QStackedWidget()
        self.window.setCentralWidget(self.stack)
        self.history: list[QWidget] = []

        self.library_page = self.library_view._build_library_page()
        self.login_page = self._build_login_page()
        self.push(self.library_page)

    def _init_shortcuts(self):
        # горячие клавиши — настраиваются в «Настройки → Внешний вид»
        self.shortcuts: dict[str, QShortcut] = {}
        for action, _title, _keys, slot in SHORTCUTS:
            sc = QShortcut(self.window)
            sc.activated.connect(getattr(self, slot, None) or getattr(self.library_view, slot))
            self.shortcuts[action] = sc
        self.apply_shortcuts()

    def _start(self):
        """Первое заполнение библиотеки и отложенные задачи после показа окна."""
        self._apply_litres_ui()
        if self.has_litres():
            # встроенный Chromium для ЛитРес — когда окно уже на экране
            QTimer.singleShot(400, self.litres.start)
        folder_scan.scan_folders(self.library, self.local_folders())
        self.library_view.refresh_library()
        QTimer.singleShot(0, self._open_last_book)
        QTimer.singleShot(2500, self.wiki_cards.load_tags)     # теги карточек книг из хранилища — для графа
        QTimer.singleShot(1800, self.library_view.refresh_review)   # «Просмотр дня» — когда окно уже на экране
        QTimer.singleShot(1700, self.library_view.refresh_focus)
        QTimer.singleShot(1500, self.library_view._make_pdf_covers)
        # Пока окно открыто — тихо подтягиваем с ЛитРес прочитанное на других устройствах
        self.litres_lib.apply_remote_sync()

    def show_settings(self):
        if self.settings_page is None:
            self.settings_page = SettingsPage(self)
        self.push(self.settings_page)

    def _open_last_book(self):
        """Автопереход: открыть последнюю текстовую книгу на месте, где остановились.

        Берётся самая свежая из начатых и не дочитанных — с учётом чтения на ЛитРес —
        среди скачанных; аудиокниги при запуске сами не открываются.
        """
        if not self.settings.get("openLastBook", True):
            return
        for book in self.library.recent(len(self.library.books), self.settings.get("lastBook")):
            if book.get("is_audio") or book.get("format") in AUDIO_FORMATS:
                continue
            path = self.library.file_path(book)
            if path:
                self.open_book(book, path)
                return

    # --- навигация между экранами (как Adw.NavigationView)

    def push(self, page):
        if self.stack.indexOf(page) < 0:
            self.stack.addWidget(page)
        if page in self.history:
            self.history.remove(page)
        self.history.append(page)
        self.stack.setCurrentWidget(page)
        page.setFocus()

    def go_back(self):
        if len(self.history) <= 1:
            return
        page = self.history.pop()
        self.stack.setCurrentWidget(self.history[-1])
        self._on_page_left(page)

    def pop_to_library(self):
        while len(self.history) > 1:
            self.go_back()

    def current(self):
        return self.history[-1] if self.history else None

    def _on_page_left(self, page):
        if page is self.reader:
            self.reader.close_page()
            self.stack.removeWidget(page)
            page.deleteLater()
            self.reader = None
            self.library.flush()
        elif page is self.settings_page:
            self.stack.removeWidget(page)
            page.deleteLater()
            self.settings_page = None
        elif page is self.graph_page:
            self.stack.removeWidget(page)
            page.deleteLater()
            self.graph_page = None
        elif page is self.login_page:
            pass
        elif getattr(page, "transient", False):     # страница на один показ (например, карта освоения)
            self.stack.removeWidget(page)
            page.deleteLater()
        self.library_view.refresh_library()

    def toggle_fullscreen(self):
        w = self.window
        w.showNormal() if w.isFullScreen() else w.showFullScreen()

    def toast(self, text, button=None, on_button=None, timeout=4000):
        t = Toast(self.window, text, button, on_button, timeout)
        t.show_in()

    # --- экран библиотеки

    def _build_login_page(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.login_header = HeaderBar(self.window, tr("Вход в ЛитРес"), tr("Пароль вводится на сайте ЛитРес"))
        back = IconButton("go-previous", tr("Назад"))
        back.clicked.connect(self.go_back)
        self.login_header.pack_start(back)
        reload_btn = IconButton("view-refresh", tr("Обновить страницу"))
        reload_btn.clicked.connect(lambda: self.litres.view and self.litres.view.reload())
        self.login_header.pack_end(reload_btn)
        lay.addWidget(self.login_header)
        lay.addWidget(self._build_login_problem())
        # браузер ЛитРес создаётся по требованию — страница входа получит его, когда он появится
        self.litres.view_holder.append(lambda view: lay.addWidget(view, 1))
        return page

    def _build_login_problem(self):
        """Строка над страницей входа, когда ЛитРес не открылся: вместо пустого окна — что делать."""
        self.login_problem = QWidget(visible=False)
        h = QHBoxLayout(self.login_problem)
        h.setContentsMargins(16, 10, 16, 10)
        self.login_problem_text = label("", wrap=True)
        h.addWidget(self.login_problem_text, 1)
        retry = QPushButton(tr("Обновить"))
        retry.clicked.connect(self.retry_login_page)
        h.addWidget(retry)
        # не дождались страницы — показываем подсказку; дождались — прячем
        self._login_wait = QTimer(self, singleShot=True, interval=12_000)
        self._login_wait.timeout.connect(lambda: self.litres.page_ready or self.login_problem.isVisible()
                                         or self.show_login_problem(tr("ЛитРес долго не отвечает.")))
        return self.login_problem

    def watch_login_page(self):
        """Вызывается при открытии страницы входа: следим, дошла ли страница ЛитРес."""
        self.login_problem.setVisible(False)
        self._login_wait.start()
        page = self.litres.page
        if page is not None and not getattr(page, "_login_watched", False):
            page._login_watched = True
            page.loadFinished.connect(lambda ok: ok or self.show_login_problem(tr("Не удалось открыть ЛитРес.")))
            page.loadStarted.connect(lambda: self.login_problem.setVisible(False))
            page.renderProcessTerminated.connect(
                lambda *_: self.show_login_problem(tr("Встроенный браузер остановился.")))

    def show_login_problem(self, what: str):
        if self.stack.currentWidget() is not self.login_page or self.litres.logged_in:
            return
        self.login_problem_text.setText(what + " " + tr(
            "Проверьте интернет. Если включён VPN — ЛитРес открывается только с российских адресов: "
            "отключите VPN или добавьте litres.ru в его исключения, затем нажмите «Обновить»."))
        self.login_problem.setVisible(True)

    def retry_login_page(self):
        self.login_problem.setVisible(False)
        self._login_wait.start()
        if self.litres.page is not None:
            self.litres.page.load(QUrl(core.LOGIN_URL))

    # --- фильтры

    # --- сетка книг

    # --- аккаунт

    def has_litres(self) -> bool:
        return libraries.has_kind(self.settings, "litres")

    def connect_litres(self):
        if self.has_litres():
            return
        libraries.set_litres(self.settings, True)
        self.save_settings()
        self.litres.start()
        self.apply_libraries()
        if self.litres.logged_in:
            self.litres_lib.sync()
        else:
            self.litres_lib.show_login()

    def disconnect_litres(self):
        if not confirm(self.window, tr("Отключить ЛитРес?"), tr("<b>Отключить библиотеку ЛитРес?</b>"),
                       tr("Книги ЛитРес пропадут из программы. Скачанные файлы, отметки и вход "
                          "сохранятся — библиотеку можно подключить снова."), tr("Отключить")):
            return
        libraries.set_litres(self.settings, False)
        self.save_settings()
        self.apply_libraries()

    def apply_libraries(self):
        """Реестр библиотек изменился: что показывать про ЛитРес, фильтры, сетка, настройки."""
        self._apply_litres_ui()
        self.rescan_local()
        if self.settings_page is not None:
            self.settings_page.rebuild_later()

    def _apply_litres_ui(self):
        """ЛитРес отключён — в интерфейсе нет ничего про него (данные и вход сохраняются)."""
        on = self.has_litres()
        self.library.hidden_sources = set() if on else {"litres"}
        self.library_view.account_action.setVisible(on)
        self.library_view.download_all_action.setVisible(on)
        self.library_view.sync_btn.setToolTip(tr("Обновить список книг с ЛитРес (F5)") if on
                                              else tr("Обновить список книг (F5)"))
        self.library_view.empty_login_btn.setVisible(on)
        self.update_account_ui()

    def update_account_ui(self):
        """Подзаголовок библиотеки и пункт меню «Войти/Выйти» по состоянию ЛитРес."""
        view = self.library_view
        if not self.has_litres():
            subtitle = tr("Библиотек: {0} · книг: {1}", len(libraries.all_libraries(self.settings)),
                          len(self.library.ordered()))
        elif self.litres_lib.bulk:
            b = self.litres_lib.bulk
            subtitle = tr('Скачиваю книги: {0} из {1}', b['done'] + b['failed'], b['total'])
        elif self.litres.logged_in:
            view.account_action.setText(tr("Выйти из ЛитРес"))
            subtitle = (tr('ЛитРес: {0}', self.litres.user_name) if self.litres.user_name
                        else tr("ЛитРес: вход выполнен"))
        else:
            view.account_action.setText(tr("Войти в ЛитРес"))
            subtitle = tr("Вход в ЛитРес не выполнен")
        view.lib_header.set_title(tr("Библиотека"), subtitle)

    # --- синхронизация

    def set_syncing(self, on):
        self.litres_lib.syncing = on
        self.library_view.sync_btn.setVisible(not on)
        self.library_view.sync_spinner.setVisible(on)

    def set_finished(self, book, finished: bool, auto=False):
        """Отметка «прочитано»: локально и на ЛитРес (сразу или при следующей синхронизации)."""
        book["finished"] = finished
        self.singularity.schedule(soon=True)
        if book.get("source") == "litres":
            book["finished_pending"] = finished
        self.library.save()
        self.library_view.refresh_card(book["id"])
        if finished:
            self.library.reading.mark_finished(book["id"])
        self.wiki_cards.on_finished(book, finished)
        self.on_focus_changed(export_only=False)
        if auto:
            self._toast_finished(book, tr("Книга дочитана — отмечена прочитанной"))
        if book.get("source") != "litres" or not self.litres.logged_in:
            return

        def done(ok):
            if ok:
                book.pop("finished_pending", None)
                self.library.save()
            else:
                self.toast(tr("Не удалось обновить отметку на ЛитРес — повторю при синхронизации"))
        self.litres.set_finished(book["id"], finished, done)

    def _toast_finished(self, book, text):
        """Уведомление о дочитанной книге; следующая в серии или по фокусу — кнопка «Открыть»."""
        nxt = self.library.next_in_series(book)
        fb = self.focus.focus_of(book)
        if not nxt and fb:
            p = self.focus.progress(fb)
            if p["enough"]:
                self.toast(tr("{0}. По фокусу «{1}» прочитано достаточно — пора закрепить и сменить фокус",
                              text, fb["name"]), button=tr("Фокус"),
                           on_button=self.show_focus, timeout=12000)
                return
            nxt = p["next"]
            if nxt:
                self.toast(tr("{0}. Дальше по фокусу: «{1}»", text, nxt.get("title")), button=tr("Открыть"),
                           on_button=lambda: self.on_book_activated(nxt["id"]), timeout=10000)
                return
        if nxt:
            self.toast(tr('{0}. Следующая в серии: «{1}»', text, nxt.get('title')), button=tr("Открыть"),
                       on_button=lambda: self.on_book_activated(nxt["id"]), timeout=10000)
        else:
            self.toast(text)

    # --- книги

    def on_book_activated(self, bid):
        book = self.library.books.get(bid)
        if not book:
            return
        path = self.library.file_path(book)
        if path:
            self.open_book(book, path)
        elif book.get("source") == "litres":
            self.litres_lib.download_book(book, open_after=True)

    def open_book(self, book, path: Path):
        fmt = book.get("format") or ""
        if fmt in AUDIO_FORMATS or fmt in READABLE:
            self.settings["lastBook"] = book["id"]
            self.save_settings()
        if fmt in AUDIO_FORMATS:
            self.open_player(book, path)
            return
        if fmt not in READABLE:
            # PDF и прочее — в приложении по умолчанию
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        self.pop_to_library()
        self.reader = ReaderPage(self, book, path)
        self.push(self.reader)

    # --- фокус на развитии

    def toggle_focus_book(self, book, inside: bool, fid: str | None = None):
        self.focus.toggle_book(book, inside, fid)
        self.on_focus_changed()

    def on_focus_changed(self, export_only=False):
        """Фокус или его книги изменились: панель, фильтр, граф, страница фокуса в вики."""
        view = self.library_view
        if not self.focus.active and view.focus_only:
            view.set_focus_only(False)
        elif view.focus_only:
            view.refresh_filters()
        view.refresh_focus()
        view.update_recent_panel()
        if self.graph_page is not None:
            self.graph_page.refresh()
        if getattr(self.current(), "follows_focus", False):
            self.current().refresh()
        self.focus_page.export()

    def open_link(self, url: str):
        """Ссылка muninhall://open?book=<id>&hl=<id выделения> (из Obsidian): книга на этом месте."""
        from urllib.parse import parse_qs, urlparse
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        book = self.library.books.get(q.get("book", ""))
        if u.scheme != "muninhall" or not book:
            self.toast(tr("Книга по ссылке не найдена в библиотеке"))
            return
        if not (self.reader and self.reader.book["id"] == book["id"] and self.current() is self.reader):
            self.on_book_activated(book["id"])
        if q.get("hl") and self.reader and self.reader.book["id"] == book["id"]:
            self.reader.go_to_highlight(q["hl"])

    # --- скачивание всех книг разом

    def remove_book_file(self, bid):
        if self.player.book_id == bid:
            # Удаляем то, что сейчас звучит — сначала останавливаем плеер
            if self.player_page:
                if self.player_page in self.history:
                    self.pop_to_library()
                self.player_page.close_page()
                self.stack.removeWidget(self.player_page)
                self.player_page.deleteLater()
                self.player_page = None
            self.player.unload()
            self.library_view.now_playing_btn.setVisible(False)
        self.library.remove_file(bid)
        self.library_view.refresh_library()

    # --- папки

    # --- аудиокниги

    def open_player(self, book, path: Path, autoplay=True):
        self.settings["lastBook"] = book["id"]
        self.save_settings()
        if self.player.book_id != book["id"]:
            tracks = audio_tracks(path)
            if not tracks:
                self.toast(tr("В аудиокниге не найдено звуковых файлов"))
                return
            self.save_audio_progress()
            saved = self.library.progress.get(book["id"], {})
            if (saved.get("fraction") or 0) >= 0.999:
                saved = {}   # прослушанную книгу начинаем сначала
            self.player.rate = self.settings.get("audioRate", 1.0)
            self.player.load(book["id"], tracks, saved.get("track", 0), saved.get("pos", 0.0), play=autoplay)
            if self.player_page:
                self.player_page.close_page()
                self.stack.removeWidget(self.player_page)
                self.player_page.deleteLater()
            self.player_page = PlayerPage(self, book)
            QTimer.singleShot(1500, lambda: self.litres_lib.apply_remote_position(book))
        elif not self.player.playing and autoplay:
            self.player.play()
        self.show_player()

    def show_player(self):
        if not self.player_page:
            return
        if self.current() is not self.player_page:
            self.pop_to_library()
            self.push(self.player_page)

    def save_audio_progress(self):
        bid = self.player.book_id
        if not bid or not self.player.tracks:
            return
        ch = self.player.chapters[self.player.current_chapter()]["title"] if self.player.chapters else ""
        self.library.set_audio_progress(bid, self.player.index, self.player.position(),
                                        self.player.fraction(), ch)
        if bid in self.library_view.cards and not self.player.playing:
            self.library_view.refresh_card(bid)

    def _on_player_state(self):
        book = self.library.books.get(self.player.book_id or "")
        if not book:
            return
        name = "media-playback-start" if self.player.playing else "media-playback-pause"
        self.library_view.now_playing_btn.setIcon(style.icon(name))
        title = book.get("title") or ""
        self.library_view.now_playing_btn.setText(" " + self.library_view.now_playing_btn.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, 200))
        self.library_view.now_playing_btn.setVisible(True)
        self.save_audio_progress()

    def _on_audio_finished(self):
        book = self.library.books.get(self.player.book_id or "")
        if not book:
            return
        self.library.set_audio_progress(book["id"], len(self.player.tracks) - 1, 0.0, 1.0)
        if not book.get("finished"):
            self.set_finished(book, True)
            self._toast_finished(book, tr("Аудиокнига прослушана — отмечена прочитанной"))

    # --- открытие своих файлов

    def import_and_open(self, path: Path):
        try:
            bid = self.library.add_local(path)
        except OSError as e:
            self.toast(tr('Не удалось открыть файл: {0}', e.strerror))
            return
        self.library_view.refresh_library()
        book = self.library.books[bid]
        self.open_book(book, self.library.file_path(book))

    def choose_books_dir(self):
        """Выбор папки для скачанных книг; уже скачанные переносятся туда же."""
        current = books_dir()
        path = QFileDialog.getExistingDirectory(self.window, tr('Папка для книг (сейчас: {0})', current), str(current))
        if not path:
            return
        new_dir = Path(path)
        if new_dir.resolve() == current.resolve():
            return
        moved, errors = self.library.move_files(new_dir)
        self.library.save()
        self.settings["booksDir"] = str(new_dir)
        self.save_settings()
        self.library_view.refresh_library()
        if errors:
            self.toast(tr('Книги теперь в {0}. Перенесено: {1}, не удалось: {2} — ', new_dir, moved, len(errors))
                       + errors[0], timeout=10000)
        else:
            self.toast(tr('Книги теперь в {0}', new_dir) + (tr(' — перенесено файлов: {0}', moved) if moved else ""))

    # --- граф книг

    def show_focus(self):
        """Страница «Фокус»: текущие фокусы и карта освоения."""
        from .focus_view import FocusView
        self.push(FocusView(self))

    def show_graph(self):
        """Граф библиотеки, выбранной в фильтре «Источник» (или всех)."""
        scope = libraries.scope_from_filter(self.settings.get("libraryType", "all"))
        if self.graph_page is None:
            self.graph_page = GraphPage(self)
        self.graph_page.fill_scopes(scope)
        self.push(self.graph_page)
        if self.has_litres():
            self.litres_lib.fetch_details()

    # --- свои книги и статьи

    def local_folders(self) -> list[dict]:
        """Свои библиотеки: [{"id", "path", "name"}] — корневые папки из реестра библиотек."""
        return libraries.folder_libraries(self.settings)

    def rescan_local(self, report=False):
        n = folder_scan.scan_folders(self.library, self.local_folders())
        self.library_view._fill_type_combo()
        self.library_view.refresh_library()
        QTimer.singleShot(500, self.library_view._make_pdf_covers)
        QTimer.singleShot(600, self.wiki_cards.load_tags)
        if report:
            self.toast(tr('Своих книг и статей: {0}', n))

    def _ask_section(self, path, current=""):
        """Название раздела для папки; None — отменили."""
        name, ok = QInputDialog.getText(self.window, tr("Раздел"),
                                        tr("Название раздела для папки\n{0}", path),
                                        text=current or Path(path).name.capitalize())
        name = name.strip()
        return name if ok and name else None

    def _save_local_folders(self, folders):
        libraries.set_folder_libraries(self.settings, folders)
        self.save_settings()
        self.rescan_local(report=True)

    def add_local_folder(self):
        folders = self.local_folders()
        start = folders[0]["path"] if folders else str(Path.home())
        path = QFileDialog.getExistingDirectory(self.window, tr("Папка со своими книгами и статьями"), start)
        if not path:
            return
        if any(Path(f["path"]) == Path(path) for f in folders):
            self.toast(tr("Эта папка уже добавлена"))
            return
        name = self._ask_section(path)
        if name:
            self._save_local_folders(folders + [{"path": path, "name": name}])

    def rename_local_folder(self, path):
        folders = self.local_folders()
        current = next((f["name"] for f in folders if f["path"] == path), "")
        name = self._ask_section(path, current)
        if name and name != current:
            self._save_local_folders([{**f, "name": name} if f["path"] == path else f for f in folders])

    def remove_local_folder(self, path):
        self._save_local_folders([f for f in self.local_folders() if f["path"] != path])

    def on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self.window, tr("Открыть книгу"), str(Path.home()),
                                              tr('Электронные книги ({0})', EBOOK_PATTERNS))
        if path:
            self.import_and_open(Path(path))

    # --- Singularity

    def note_activity(self):
        """Читатель листает книгу — для учёта времени чтения и отправки прогресса."""
        self._last_activity = time.monotonic()
        self.singularity.schedule()

    def _count_reading_time(self):
        reading = (self.reader is not None and self.current() is self.reader
                   and self.window.isActiveWindow() and time.monotonic() - self._last_activity < 180)
        tts = self.reader is not None and getattr(self.reader, "tts_active", False)
        if reading or tts or self.player.playing:
            bid = self.reader.book["id"] if (reading or tts) else self.player.book_id
            self.library.reading.add_reading_time(bid, 30)
            self.singularity.add_reading_time(30)
            if self.player.playing:
                self.singularity.schedule()

    def show_stats_dialog(self):
        from .stats import show_stats
        show_stats(self)

    def show_singularity_dialog(self):
        singularity.show_dialog(self)

    # --- прочее

    # --- ЛитРес: подключаемая библиотека (litres_connector.py); делегаты для других модулей

    def sync(self, *args, **kwargs):
        if not self.has_litres():
            return self.rescan_local(report=not kwargs.get("quiet"))
        return self.litres_lib.sync(*args, **kwargs)

    def download_book(self, *args, **kwargs):
        return self.litres_lib.download_book(*args, **kwargs)

    def show_login(self, *args, **kwargs):
        return self.litres_lib.show_login(*args, **kwargs)

    def apply_remote_position(self, *args, **kwargs):
        return self.litres_lib.apply_remote_position(*args, **kwargs)

    def apply_remote_sync(self, *args, **kwargs):
        return self.litres_lib.apply_remote_sync(*args, **kwargs)

    def download_all(self, *args, **kwargs):
        return self.litres_lib.download_all(*args, **kwargs)

    def toggle_account(self, *args, **kwargs):
        return self.litres_lib.toggle_account(*args, **kwargs)

    def save_settings(self):
        """Настройки сохраняются сами (config.Settings); здесь — применить их к открытой книге."""
        if self.reader:
            self.reader.apply_settings()
        self.settings.schedule_save()

    # --- внешний вид: тема, акцент, значок, горячие клавиши

    def on_about(self):
        box = QMessageBox(self.window)
        box.setWindowTitle(tr("О приложении"))
        box.setIconPixmap(QIcon(str(core.app_icon_path(self.settings.get("appIcon")))).pixmap(96, 96))
        box.setText(tr('<h3>{0}</h3><p>Версия {1}</p>', APP_NAME, __version__))
        libs = libraries.all_libraries(self.settings)
        box.setInformativeText(
            tr("Своя библиотека книг и статей: создавайте, читайте, организуйте и обслуживайте её. "
               "Библиотеки — папки на диске; у каждой свой граф и свои резервные копии, а все вместе "
               "они просматриваются как одна большая.<br><br>"
               "ЛитРес — подключаемая библиотека купленных книг и аудиокниг; вход выполняется на сайте "
               "ЛитРес, приложение не хранит пароль.")
            + "<br><br>" + tr("Библиотек: {0} · книг: {1}", len(libs), len(self.library.ordered()))
            + "<br><br>" + tr("Лицензия MIT. Движок чтения — foliate-js (MIT), PDF — pdf.js (Apache 2.0), "
                              "граф — d3-force (ISC), значки — Adwaita.")
            + "<br>" + tr("Документация и исходный код: {0}", "github.com/arvino-t/muninhall"))
        site = box.addButton(tr("Открыть на GitHub"), QMessageBox.ButtonRole.ActionRole)
        site.clicked.disconnect()          # кнопка не закрывает окно
        site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/arvino-t/muninhall")))
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()

    # --- резервные копии

    def make_backup(self, reason="", scope="all") -> Path | None:
        """Копия всех библиотек (scope="all") или одной: "litres" / id своей."""
        self.library.save()
        self.library.flush()
        self.highlights.flush()
        try:
            path = backup.create(self.settings, reason, scope)
        except (OSError, ValueError) as e:
            print(f"muninhall: резервная копия не создана: {e}", file=sys.stderr, flush=True)
            return None
        if scope == "all":
            self.settings["backupLast"] = datetime.now().isoformat(timespec="seconds")
            self.save_settings()
        log("backup", path)
        return path

    def auto_backup(self):
        if backup.due(self.settings):
            self.make_backup()

    def restart(self):
        """Перезапуск приложения (после восстановления из копии)."""
        if getattr(sys, "frozen", False):          # собранная программа (Windows): сама себя
            QProcess.startDetached(sys.executable, ["--restarted"])
        else:
            QProcess.startDetached(sys.executable, ["-m", "muninhall", "--restarted"])
        self.window.close()
        self.qapp.quit()

    def on_close(self):
        self.save_audio_progress()
        self.player.unload()
        self.library.flush()
        self.highlights.flush()
        self.highlight_pages.export_pending()
        self.settings.save_now()
        if self.reader:
            self.reader.close_page()
        self.litres.shutdown()


# ─────────────────────────────────────────────────────────────── запуск

def _server_name(app_id=APP_ID):
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return f"{app_id}-{user}"


def _old_version_running() -> bool:
    """Открыта прежняя версия — данные переносить нельзя, она пишет в старые каталоги."""
    for app_id in OLD_APP_IDS:
        sock = QLocalSocket()
        sock.connectToServer(_server_name(app_id))
        running = sock.waitForConnected(300)
        sock.abort()
        if running:
            return True
    return False


def _wait_for_previous():
    """Перезапуск: ждём, пока прежний экземпляр закроется (до 15 с)."""
    for _ in range(50):
        probe = QLocalSocket()
        probe.connectToServer(_server_name())
        if not probe.waitForConnected(100):
            break
        probe.abort()
        time.sleep(0.3)


def _hand_off(files) -> bool:
    """Уже запущено — передаём файлы открытому окну."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(("\n".join(map(str, files)) or "\n").encode())
    sock.flush()
    sock.waitForBytesWritten(1000)
    return True


def _create_qapp(argv) -> QApplication:
    from .reader import register_scheme
    register_scheme()
    QApplication.setApplicationName(APP_SLUG)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(APP_ID)
    qapp = QApplication(argv)
    qapp.setStyle("Fusion")
    qapp.setFont(style.app_font())
    qapp.setWindowIcon(QIcon(str(APP_ICON)))
    return qapp


def _migrate() -> bool:
    """Переименование «Читалка ЛитРес» → Muninhall: данные переезжают в новые каталоги (один раз).
    False — прежняя версия ещё открыта, запускаться нельзя."""
    if core.migration_needed() and _old_version_running():
        QMessageBox.information(None, APP_NAME, tr("Закройте прежнюю версию приложения («Читалка ЛитРес» "
                                                   "или Shelfwise) и запустите Muninhall снова: её данные "
                                                   "перенесутся."))
        return False
    moved = core.migrate_old_dirs()
    backup.migrate_default_dir()
    if moved:
        log("данные прежней версии перенесены:", moved)
    return True


def _listen(app) -> QLocalServer:
    """Файлы, открытые вторым запуском, приходят сюда."""
    server = QLocalServer(app)
    QLocalServer.removeServer(_server_name())
    server.listen(_server_name())

    def on_connection():
        conn = server.nextPendingConnection()

        def read():
            for line in bytes(conn.readAll()).decode().splitlines():
                line = line.strip()
                if line.startswith("muninhall:"):
                    app.open_link(line)
                elif line:
                    app.import_and_open(Path(line))
            app.window.showNormal() if app.window.isMinimized() else None
            app.window.raise_()
            app.window.activateWindow()
        conn.readyRead.connect(read)
    server.newConnection.connect(on_connection)
    return server


def _smoke_test(app, qapp):
    """Проверка сборки (CI): окно поднялось, библиотека построена — выходим с кодом 0.

    С MUNINHALL_SMOKE_TEST_WEB=1 — ещё и встроенный Chromium: открываем страницу входа ЛитРес и ждём
    загрузки (до MUNINHALL_SMOKE_TEST_WEB_MS); в отчёт — дошла ли страница и что в ней."""
    lines = []

    def say(line):
        lines.append(line)
        print(line, flush=True)
        if os.environ.get("MUNINHALL_SMOKE_TEST_FILE"):    # у оконной сборки Windows нет консоли
            Path(os.environ["MUNINHALL_SMOKE_TEST_FILE"]).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def smoke():
        say(f"MUNINHALL_SMOKE_TEST ok: {APP_NAME} {__version__}, books: {len(app.library.ordered())}")
        app.window.close()
        qapp.quit()

    if not os.environ.get("MUNINHALL_SMOKE_TEST_WEB"):
        QTimer.singleShot(int(os.environ.get("MUNINHALL_SMOKE_TEST_MS", "4000")), smoke)
        return
    from PySide6 import __version__ as pyside_version
    say(f"web: PySide6 {pyside_version}, chromium flags: {os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')!r}")
    loads = []

    def web_started():
        app.litres.start()
        page = app.litres.page
        page.loadFinished.connect(lambda ok: (loads.append(ok), say(f"web: loadFinished ok={ok} url={page.url().toString()}")))
        page.renderProcessTerminated.connect(
            lambda status, code: say(f"web: render process terminated status={status} code={code}"))
        app.show_login()

    def web_report():
        page = app.litres.page

        def got(text):
            say(f"web: page_ready={app.litres.page_ready} loads={loads} title={page.title()!r} "
                f"text chars={len(text or '')}")
            # текст страницы входа React-приложения toPlainText может не отдать — достаточно заголовка
            say("MUNINHALL_SMOKE_TEST web " + ("ok" if any(loads) and page.title() else "FAILED"))
            if os.environ.get("MUNINHALL_SMOKE_TEST_SHOT"):      # снимок окна — что видит пользователь
                app.window.grab().save(os.environ["MUNINHALL_SMOKE_TEST_SHOT"])
            smoke()
        page.toPlainText(got)
        QTimer.singleShot(5000, lambda: lines[-1].startswith("MUNINHALL_SMOKE_TEST") or got(""))  # страница мертва
    QTimer.singleShot(1000, web_started)
    QTimer.singleShot(int(os.environ.get("MUNINHALL_SMOKE_TEST_WEB_MS", "45000")), web_report)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    links = [a for a in argv[1:] if a.startswith("muninhall:")]      # из Obsidian: место в книге
    # ярлык передаёт %U: файлы могут прийти как file:///…
    args = [QUrl(a).toLocalFile() if a.startswith("file://") else a for a in argv[1:]]
    files = [Path(a).resolve() for a in args if not a.startswith(("-", "muninhall:")) and Path(a).exists()]
    if "--restarted" in argv:
        _wait_for_previous()
    if _hand_off([*files, *links]):
        return 0
    qapp = _create_qapp(argv)
    if not _migrate():
        return 0
    restored = backup.apply_pending()     # восстановление из копии — до чтения данных
    app = App(qapp)
    app.window.show()
    if restored:
        QTimer.singleShot(800, lambda: app.toast(tr("Данные восстановлены из резервной копии"), timeout=6000))
    server = _listen(app)
    for f in files:
        QTimer.singleShot(0, lambda f=f: app.import_and_open(f))
    for link in links:
        QTimer.singleShot(300, lambda link=link: app.open_link(link))
    if os.environ.get("MUNINHALL_SMOKE_TEST"):
        _smoke_test(app, qapp)
    code = qapp.exec()
    server.close()
    return code
