"""«Карта освоения»: что я знаю — по каждой теме уровень освоения и что делать дальше.

Тема — тег книги (book_tags): тема вики, жанр, тема своей библиотеки, тег вики. По теме считаются книги
(прочитано / читаю / впереди), время чтения (статистика), мои цитаты и вопросы (выделения), осмысленные в вики
книги (status: ingested в карточке). Уровень и «куда обратить внимание» выводятся из этих чисел — без нейросети.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .book_tags import book_labels

TOPIC_KINDS = ("wtopic", "genre", "wiki", "topic")   # серии, авторы, папки ЛитРес — не темы знаний;
                                                      # порядок — чьё название берём при одинаковых книгах
MIN_BOOKS = 3                                         # тема — от трёх книг
LEVELS = ("none", "started", "learning", "understand", "mastered")


def level_names() -> dict[str, str]:
    from .i18n import tr
    return {"none": tr("Не начато"), "started": tr("Знакомство"), "learning": tr("Изучаю"),
            "understand": tr("Разбираюсь"), "mastered": tr("Освоено")}


@dataclass
class Topic:
    kind: str
    name: str
    books: list = field(default_factory=list)
    finished: int = 0
    reading: int = 0
    seconds: int = 0
    quotes: int = 0
    questions: int = 0
    ingested: int = 0
    question_texts: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.books)

    @property
    def unread(self) -> int:
        return self.total - self.finished - self.reading

    @property
    def level(self) -> str:
        # «освоено» — и по числу, и по доле книг темы (12 из 53 — ещё не освоено), либо через работу в вики
        if (self.finished >= 5 and self.finished >= self.total * 0.4) or (self.finished >= 3 and self.ingested >= 2):
            return "mastered"
        if self.finished >= 3 or (self.finished >= 1 and self.ingested >= 1):
            return "understand"
        if self.finished >= 1:
            return "learning"
        if self.reading or self.seconds > 0:
            return "started"
        return "none"


def build(library, highlights=None, stats: dict | None = None, limit: int = 30) -> list[Topic]:
    """Темы библиотеки (от MIN_BOOKS книг, без «зонтиков» на половину библиотеки), крупные первыми."""
    books = library.ordered()
    per_book_seconds = (stats or {}).get("books", {})
    topics: dict[tuple, Topic] = {}
    for b in books:
        for kind, name in book_labels(library, b):
            if kind in TOPIC_KINDS:
                topics.setdefault((kind, name.lower()), Topic(kind, name)).books.append(b)
    total = max(1, len(books))
    out = [t for t in topics.values() if MIN_BOOKS <= t.total <= max(MIN_BOOKS, total * 0.5)
           and not _storage_folder(t)]
    seen = set()                                      # папка «llm-compression» и тема вики «Сжатие LLM» — одно
    out.sort(key=lambda t: TOPIC_KINDS.index(t.kind))
    out = [t for t in out if not (frozenset(b["id"] for b in t.books) in seen
                                  or seen.add(frozenset(b["id"] for b in t.books)))]
    for t in out:
        for b in t.books:
            st = library.status(b)
            t.finished += st == "finished"
            t.reading += st == "reading"
            t.seconds += int(per_book_seconds.get(b["id"], 0))
            t.ingested += b.get("vault_status") == "ingested"
            for h in (highlights.for_book(b) if highlights else []):
                t.quotes += 1
                if h.get("color") == "question":
                    t.questions += 1
                    t.question_texts.append((b, h))
    out.sort(key=lambda t: (-LEVELS.index(t.level), -t.total) if t.level != "none" else (1, -t.total))
    return out[:limit]


def _storage_folder(t: Topic) -> bool:
    """Тема вики, которая лишь папка хранения (например, «Книги ЛитРес» — все покупки): у её книг свои жанры,
    они и есть темы. Темы своих папок (книги без жанров) остаются."""
    return t.kind == "wtopic" and sum(1 for b in t.books if b.get("genres")) >= t.total * 0.8


def attention(topics: list[Topic], per_kind: int = 3) -> list[tuple[str, Topic]]:
    """Куда обратить внимание: (вид совета, тема). Виды: continue — начато, ничего не дочитано;
    questions — остались вопросы; consolidate — прочитано, но не закреплено (ни цитат, ни конспекта в вики);
    move_on — освоено, пора двигаться дальше; untouched — большая тема, к которой не приступали."""
    out = []
    for t in topics:
        if t.reading and not t.finished:
            out.append(("continue", t))
        if t.questions:
            out.append(("questions", t))
        if t.finished >= 2 and not t.ingested and not t.quotes:
            out.append(("consolidate", t))
        if t.level == "mastered":
            out.append(("move_on", t))
    untouched = sorted((t for t in topics if t.level == "none" and t.total >= 5), key=lambda t: -t.total)[:3]
    out += [("untouched", t) for t in untouched]
    order = ("continue", "questions", "consolidate", "move_on", "untouched")
    out = [x for x in out if sum(1 for y in out[:out.index(x)] if y[0] == x[0]) < per_kind]   # разнообразие
    return sorted(out, key=lambda x: order.index(x[0]))


def tip_text(kind: str, t: Topic, short: bool = False) -> str:
    """Текст совета; short — для страницы вики (без призыва к действию)."""
    from .i18n import tr
    if kind == "continue":
        return tr("«{0}»: начато {1}, ни одной не дочитано", t.name, t.reading) if short else \
            tr("«{0}»: начато {1}, ни одной не дочитано — продолжите", t.name, t.reading)
    if kind == "questions":
        return tr("«{0}»: вопросов без ответа — {1}", t.name, t.questions) if short else \
            tr("«{0}»: вопросов без ответа — {1}; вернитесь к ним", t.name, t.questions)
    if kind == "consolidate":
        return tr("«{0}»: прочитано {1}, ничего не закреплено в вики", t.name, t.finished) if short else \
            tr("«{0}»: прочитано {1}, но ничего не закреплено — сделайте конспект в вики", t.name, t.finished)
    if kind == "move_on":
        return tr("«{0}»: освоено — пора к новой теме", t.name) if short else \
            tr("«{0}»: освоено — можно сменить фокус на новую тему", t.name)
    return tr("«{0}»: {1} книг, ни одной не начато", t.name, t.total)


def hours(seconds: int) -> str:
    from .i18n import tr
    h, m = divmod(int(seconds) // 60, 60)
    return tr("{0} ч {1} мин", h, m) if h else tr("{0} мин", m)
