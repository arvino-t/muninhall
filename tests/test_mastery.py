"""«Карта освоения»: уровни тем, советы «куда обратить внимание», какие теги считаются темами."""
from muninhall import mastery
from muninhall.highlights import HighlightStore
from muninhall.mastery import Topic
from muninhall.model import Library


def test_levels():
    t = Topic("genre", "x", books=[{}] * 10)
    assert t.level == "none"
    t.reading = 1
    assert t.level == "started"
    t.finished = 1
    assert t.level == "learning"
    t.ingested = 1
    assert t.level == "understand"                         # одна прочитанная и осмысленная в вики
    big = Topic("genre", "big", books=[{}] * 53, finished=12)
    assert big.level == "understand"                       # 12 из 53 — ещё не «освоено»
    small = Topic("genre", "small", books=[{}] * 10, finished=5)
    assert small.level == "mastered"
    wiki = Topic("genre", "wiki", books=[{}] * 20, finished=3, ingested=2)
    assert wiki.level == "mastered"                        # путь через работу в вики


def test_build_and_attention(clean_data, tmp_path):
    lib = Library()
    for i in range(12):
        genres = ["психология"] if i < 6 else ["финансы"]
        lib.books[str(i)] = {"id": str(i), "source": "litres", "title": f"Книга {i}", "genres": genres + ["всё"],
                             "tags": ["редкий"] if i == 0 else []}
        lib.order.append(str(i))
    for i in (0, 1):
        lib.books[str(i)]["finished"] = True
    lib.progress["6"] = {"fraction": 0.4}
    hs = HighlightStore(lib)
    hs.add(lib.books["0"], text="почему?", color="question")
    topics = mastery.build(lib, hs, {"books": {"0": 600, "6": 1200}})
    names = {t.name for t in topics}
    assert names == {"психология", "финансы"}               # «всё» — на всю библиотеку, «редкий» — одна книга
    psy = next(t for t in topics if t.name == "психология")
    fin = next(t for t in topics if t.name == "финансы")
    assert (psy.finished, psy.questions, psy.quotes, psy.seconds, psy.level) == (2, 1, 1, 600, "learning")
    assert (fin.reading, fin.level) == (1, "started")
    tips = mastery.attention(topics)
    assert ("continue", fin) in tips and ("questions", psy) in tips
    assert mastery.hours(3900) == "1 ч 5 мин" and mastery.hours(120) == "2 мин"


def test_same_books_one_topic(clean_data):
    lib = Library()
    for i in range(4):
        lib.books[str(i)] = {"id": str(i), "source": "folder", "title": str(i), "collection": "Мои/llm-compression",
                             "vault_topic": "Сжатие LLM"}
        lib.order.append(str(i))
    for i in range(4, 12):
        lib.books[str(i)] = {"id": str(i), "source": "folder", "title": str(i)}
        lib.order.append(str(i))
    assert [(t.kind, t.name) for t in mastery.build(lib)] == [("wtopic", "Сжатие LLM")]


def test_storage_folder_and_variety():
    with_genres = [{"genres": ["x"]}] * 9 + [{}]
    assert mastery._storage_folder(Topic("wtopic", "Книги ЛитРес", books=with_genres))
    assert not mastery._storage_folder(Topic("wtopic", "Управление", books=[{}] * 10))
    assert not mastery._storage_folder(Topic("genre", "психология", books=with_genres))
    many = [Topic("genre", str(i), books=[{}] * 5, finished=2) for i in range(6)]
    assert [k for k, _ in mastery.attention(many)] == ["consolidate"] * 3
