"""«Фокус на развитии»: книги фокуса, следующая книга, порог «достаточно», похожие книги, архив."""
from muninhall.focus import FocusStore, book_labels
from muninhall.model import Library


def make_lib():
    lib = Library()
    data = {
        "1": {"genres": ["психология"], "tags": ["коммуникация", "переговоры"]},
        "2": {"genres": ["психология"], "tags": ["коммуникация"]},
        "3": {"genres": ["психология"], "tags": ["коммуникация", "переговоры", "влияние"]},
        "4": {"genres": ["финансы"], "tags": ["инвестиции"]},
        "5": {"genres": ["психология"], "tags": ["влияние", "переговоры"]},
        "6": {"genres": ["финансы"], "tags": ["инвестиции", "трейдинг"]},
        "7": {"genres": ["финансы"], "tags": ["трейдинг"]},
    }
    for bid, extra in data.items():
        lib.books[bid] = {"id": bid, "source": "litres", "title": f"Книга {bid}", **extra}
        lib.order.append(bid)
    return lib


def test_focus_books_next_and_enough(clean_data, tmp_path):
    lib = make_lib()
    fs = FocusStore(lib, path=tmp_path / "focus.json")
    f = fs.set_focus("Коммуникация", [("tag", "Коммуникация")], enough=2)
    assert {b["id"] for b in fs.books()} == {"1", "2", "3"}               # теги без учёта регистра
    lib.books["1"]["finished"] = True
    # следующей — самая близкая к прочитанной книге 1 (общие «переговоры»): 3, а не 2
    assert fs.progress()["next"]["id"] == "3"
    fs.toggle_book(lib.books["5"], True)                                   # вручную — в фокус
    fs.toggle_book(lib.books["2"], False)                                  # и из фокуса
    assert {b["id"] for b in fs.books()} == {"1", "3", "5"}
    p = fs.progress()
    assert (p["total"], p["finished"], p["unread"]) == (3, 1, 2) and not p["enough"]
    assert p["next"]["id"] == "5"                                          # явный выбор — выше тегов
    lib.progress["3"] = {"fraction": 0.3}                                  # начатая — всегда первой
    assert fs.progress()["next"]["id"] == "3"
    lib.progress.pop("3")
    lib.progress["5"] = {"fraction": 0.3}
    assert fs.progress()["next"]["id"] == "5"
    lib.books["3"]["finished"] = True
    assert fs.progress()["enough"]                                         # прочитано 2 из порога 2
    assert [b["id"] for b in fs.ranked()] == ["5"]
    assert FocusStore(lib, path=tmp_path / "focus.json").active["name"] == "Коммуникация"   # сохранено
    assert f["id"] == fs.active["id"]


def test_related_next_topics_and_archive(clean_data, tmp_path):
    lib = make_lib()
    fs = FocusStore(lib, path=tmp_path / "focus.json")
    first = fs.set_focus("Переговоры", [("tag", "переговоры")])
    assert {b["id"] for b in fs.related()} >= {"2"}                      # общая «коммуникация», «психология»
    topics = [name for _k, name, _n in fs.next_topics(5)]
    assert "переговоры" not in topics and "финансы" in topics
    assert "психология" not in topics                    # покрывает все книги фокуса — не смена темы
    second = fs.set_focus("Финансы", [("genre", "финансы")])
    assert fs.active["id"] == second["id"]
    assert [f["id"] for f in fs.archive()] == [first["id"]] and first["status"] == "archived"
    fs.activate(first["id"])
    assert fs.active["id"] == first["id"] and second["status"] == "archived"
    fs.finish()
    assert fs.active is None and first["status"] == "done"
    assert ("tag", "переговоры") in book_labels(lib, lib.books["1"])
