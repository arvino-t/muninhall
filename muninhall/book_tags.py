"""Теги книги — одни правила для графа, фокуса и всего, что группирует книги по темам.

Вид тега: genre (жанр ЛитРес), tag (тег ЛитРес), wiki (тег карточки в вики; вложенный «ml/сжатие» даёт и «ml»),
wtopic (тема карточки в вики), topic (подпапка своей библиотеки), folder (папка на ЛитРес), series, author.
"""
from __future__ import annotations

from .i18n import tr


def kind_names() -> dict[str, str]:
    """Подписи видов тегов для интерфейса и страниц вики."""
    return {"genre": tr("Жанр"), "tag": tr("Тег ЛитРес"), "wiki": tr("Тег вики"), "wtopic": tr("Тема вики"),
            "topic": tr("Тема"), "folder": tr("Папка ЛитРес"), "series": tr("Серия"), "author": tr("Автор")}


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
