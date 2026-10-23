"""Окно «Фокус»: тема, теги (книги с ними попадают в фокус), порог «достаточно», архив."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .book_tags import kind_names
from .i18n import tr
from .widgets import cls, exec_dialog, frameless_dialog, label

CHANGED_ELSEWHERE = 2          # результат окна: активный фокус сменили из архива или завершили


class FocusDialog:
    """fid — изменить этот фокус; new — новый (вторым или вместо самого давнего);
    preset — (название, [(вид, подпись)]) для нового фокуса (например, из подсказки)."""

    def __init__(self, app, preset: tuple[str, list] | None = None, fid: str | None = None, new: bool = False):
        self.app = app
        self.store = app.focus
        self.focus = None if (preset or new) else (self.store.data["items"].get(fid) if fid else self.store.active)
        name0, labels0 = preset if preset else ((self.focus["name"], self.focus["labels"]) if self.focus
                                                else ("", []))
        self.dlg, v = frameless_dialog(app.window, tr("Фокус"), 520)
        body = QWidget()
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(18, 14, 18, 18)
        self.box.setSpacing(10)
        self.box.addWidget(label(tr("Текущий приоритет в чтении: тема и её теги. Книги с этими тегами попадают в "
                                    "фокус сами; отдельные книги можно добавить или убрать в меню книги."), "dim",
                                 wrap=True))
        self.name = QLineEdit(name0)
        self.name.setPlaceholderText(tr("Например: Коммуникация, Квантование LLM, Финансы"))
        self.box.addWidget(self.name)
        self._build_labels({(k, n.lower()) for k, n in labels0})
        self._build_enough()
        self._build_archive()
        self._build_buttons()
        v.addWidget(body)
        self.update_count()

    # --- части окна

    def _build_labels(self, chosen: set):
        """Поиск и список всех тегов библиотеки с числом книг; отмеченные — теги фокуса."""
        search = QLineEdit()
        search.setPlaceholderText(tr("Найти тег, жанр, тему…"))
        self.box.addWidget(search)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        kinds = kind_names()
        for kind, text, count in self.store.all_labels():
            it = QListWidgetItem(f"{text}  ·  {kinds.get(kind, kind)} · {count}")
            it.setData(Qt.ItemDataRole.UserRole, (kind, text))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if (kind, text.lower()) in chosen else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.box.addWidget(self.list, 1)
        self.list.itemChanged.connect(self.update_count)
        search.textChanged.connect(self._filter)

    def _build_enough(self):
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Достаточно, чтобы разобраться:")))
        self.enough = QSpinBox()
        self.enough.setRange(1, 50)
        self.enough.setValue(int((self.focus or {}).get("enough", 5)))
        self.enough.setSuffix(tr(" книг"))
        row.addWidget(self.enough)
        row.addStretch()
        self.count = label("", "dim", "caption")
        row.addWidget(self.count)
        self.box.addLayout(row)

    def _build_archive(self):
        """Прежние фокусы: любой можно снова сделать текущим."""
        archive = self.store.archive()
        if not archive:
            return
        self.box.addWidget(label(tr("Прежние фокусы"), "heading"))
        for f in archive[:6]:
            row = QHBoxLayout()
            p = self.store.progress(f)
            state = tr("пройден") if f.get("status") == "done" else tr("отложен")
            row.addWidget(label(f"{f['name']} — {state} · {tr('прочитано {0} из {1}', p['finished'], p['total'])}",
                                "caption", wrap=True), 1)
            again = QPushButton(tr("Сделать текущим"))
            again.clicked.connect(lambda _=False, fid=f["id"]: (self.store.activate(fid),
                                                                 self.dlg.done(CHANGED_ELSEWHERE)))
            row.addWidget(again)
            self.box.addLayout(row)

    def _build_buttons(self):
        row = QHBoxLayout()
        if self.focus:
            finish = QPushButton(tr("Завершить фокус"))
            finish.clicked.connect(lambda: (self.store.finish(self.focus["id"], True),
                                            self.dlg.done(CHANGED_ELSEWHERE)))
            row.addWidget(finish)
        row.addStretch()
        cancel = QPushButton(tr("Отмена"))
        save = QPushButton(tr("Сохранить"))
        cls(save, "suggested")
        cancel.clicked.connect(self.dlg.reject)
        save.clicked.connect(self.dlg.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        self.box.addLayout(row)

    # --- состояние

    def checked(self) -> list[tuple[str, str]]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def update_count(self, *_):
        f = self.focus or {}
        probe = {"labels": [list(x) for x in self.checked()], "include": f.get("include", []),
                 "exclude": f.get("exclude", [])}
        self.count.setText(tr("Книг в фокусе: {0}", len(self.store.books(probe))))

    def _filter(self, text):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    # --- показать и сохранить

    def exec(self) -> bool:
        """True — фокусы изменены."""
        self.name.setFocus()
        result = exec_dialog(self.dlg)
        if result == CHANGED_ELSEWHERE:
            self.app.on_focus_changed()
            return True
        if not result:
            return False
        labels = self.checked()
        if not labels and not (self.focus and self.focus.get("include")):
            self.app.toast(tr("Выберите хотя бы один тег — по нему книги попадут в фокус"))
            return False
        self.store.set_focus(self.name.text() or (labels[0][1] if labels else "—"), labels, self.enough.value(),
                             fid=self.focus["id"] if self.focus else None)
        self.app.on_focus_changed()
        return True


def show_focus_dialog(app, preset: tuple[str, list] | None = None, fid: str | None = None, new: bool = False) -> bool:
    return FocusDialog(app, preset, fid, new).exec()
