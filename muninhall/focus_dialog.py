"""Окно «Фокус»: тема, теги (книги с ними попадают в фокус), порог «достаточно», архив."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .i18n import tr
from .widgets import cls, exec_dialog, frameless_dialog, label


def kind_names() -> dict[str, str]:
    return {"genre": tr("Жанр"), "tag": tr("Тег ЛитРес"), "wiki": tr("Тег вики"), "wtopic": tr("Тема вики"),
            "topic": tr("Тема"), "folder": tr("Папка ЛитРес"), "series": tr("Серия"), "author": tr("Автор")}


def show_focus_dialog(app, preset: tuple[str, list] | None = None, fid: str | None = None, new: bool = False) -> bool:
    """True — фокусы изменены. fid — изменить этот фокус; new — новый (вторым или вместо самого давнего);
    preset — (название, [(вид, подпись)]) для нового фокуса (например, из подсказки)."""
    store = app.focus
    if preset or new:
        active = None                                   # новый фокус
    else:
        active = store.data["items"].get(fid) if fid else store.active
    name0, labels0 = preset if preset else ((active["name"], active["labels"]) if active else ("", []))
    chosen = {(k, n.lower()) for k, n in labels0}
    dlg, v = frameless_dialog(app.window, tr("Фокус"), 520)
    body = QWidget()
    b = QVBoxLayout(body)
    b.setContentsMargins(18, 14, 18, 18)
    b.setSpacing(10)
    b.addWidget(label(tr("Текущий приоритет в чтении: тема и её теги. Книги с этими тегами попадают в фокус "
                         "сами; отдельные книги можно добавить или убрать в меню книги."), "dim", wrap=True))
    name = QLineEdit(name0)
    name.setPlaceholderText(tr("Например: Коммуникация, Квантование LLM, Финансы"))
    b.addWidget(name)
    search = QLineEdit()
    search.setPlaceholderText(tr("Найти тег, жанр, тему…"))
    b.addWidget(search)
    lst = QListWidget()
    lst.setMinimumHeight(260)
    kinds = kind_names()
    for kind, text, count in store.all_labels():
        it = QListWidgetItem(f"{text}  ·  {kinds.get(kind, kind)} · {count}")
        it.setData(Qt.ItemDataRole.UserRole, (kind, text))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if (kind, text.lower()) in chosen else Qt.CheckState.Unchecked)
        lst.addItem(it)
    b.addWidget(lst, 1)
    row = QHBoxLayout()
    row.addWidget(QLabel(tr("Достаточно, чтобы разобраться:")))
    enough = QSpinBox()
    enough.setRange(1, 50)
    enough.setValue(int((active or {}).get("enough", 5)))
    enough.setSuffix(tr(" книг"))
    row.addWidget(enough)
    row.addStretch()
    count = label("", "dim", "caption")
    row.addWidget(count)
    b.addLayout(row)

    def checked() -> list[tuple[str, str]]:
        return [lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked]

    def update_count(*_):
        probe = {"labels": [list(x) for x in checked()], "include": (active or {}).get("include", []), "exclude": (active or {}).get("exclude", [])}
        count.setText(tr("Книг в фокусе: {0}", len(store.books(probe))))

    def filter_list(text):
        t = text.strip().lower()
        for i in range(lst.count()):
            it = lst.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())
    lst.itemChanged.connect(update_count)
    search.textChanged.connect(filter_list)
    update_count()

    archive = store.archive()
    if archive:
        b.addWidget(label(tr("Прежние фокусы"), "heading"))
        for f in archive[:6]:
            ar = QHBoxLayout()
            p = store.progress(f)
            state = tr("пройден") if f.get("status") == "done" else tr("отложен")
            ar.addWidget(label(f"{f['name']} — {state} · {tr('прочитано {0} из {1}', p['finished'], p['total'])}",
                               "caption", wrap=True), 1)
            again = QPushButton(tr("Сделать текущим"))
            again.clicked.connect(lambda _=False, fid=f["id"]: (store.activate(fid), dlg.done(2)))
            ar.addWidget(again)
            b.addLayout(ar)
    buttons = QHBoxLayout()
    if active:
        finish = QPushButton(tr("Завершить фокус"))
        finish.clicked.connect(lambda: (store.finish(active["id"], True), dlg.done(2)))
        buttons.addWidget(finish)
    buttons.addStretch()
    cancel = QPushButton(tr("Отмена"))
    save = QPushButton(tr("Сохранить"))
    cls(save, "suggested")
    cancel.clicked.connect(dlg.reject)
    save.clicked.connect(dlg.accept)
    buttons.addWidget(cancel)
    buttons.addWidget(save)
    b.addLayout(buttons)
    v.addWidget(body)
    name.setFocus()
    result = exec_dialog(dlg)
    if result == 2:                                     # сменили активный или завершили
        app.on_focus_changed()
        return True
    if not result:
        return False
    labels = checked()
    if not labels and not (active and active.get("include")):
        app.toast(tr("Выберите хотя бы один тег — по нему книги попадут в фокус"))
        return False
    store.set_focus(name.text() or (labels[0][1] if labels else "—"), labels, enough.value(),
                    fid=active["id"] if active else None)
    app.on_focus_changed()
    return True
