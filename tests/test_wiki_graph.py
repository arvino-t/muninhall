"""Граф из Obsidian: страницы и ссылки вики, связь карточек книг с ними, возможные теги, данные графа."""
from muninhall import folder_scan, wiki_graph
from muninhall.graph import build_graph
from muninhall.model import Library
from tests.test_folder_library import bid_of, make_lib


def make_wiki(root):
    w = root / "wiki"
    for d in ("sources", "topics", "concepts"):
        (w / d).mkdir(parents=True, exist_ok=True)
    (w / "topics" / "Сжатие.md").write_text('---\ntitle: "Сжатие LLM"\n---\nСм. [[concepts/Квантование]].\n')
    (w / "concepts" / "Квантование.md").write_text("---\ntype: concept\n---\nСвязано с [[concepts/Прунинг]].\n")
    (w / "sources" / "B.md").write_text('---\ntitle: "B"\nfile: "Books/sub/b.pdf"\n---\n# B\n'
                                        "[[topics/Сжатие|Сжатие]] и [[concepts/Квантование]]\n"
                                        "## Суть\nPost-training quantization for language models.\n")
    return w


def test_load_pages_links_and_missing(tmp_path):
    make_wiki(tmp_path)
    g = wiki_graph.load(tmp_path)
    assert g.pages["topics/Сжатие"] == {"title": "Сжатие LLM", "kind": "wtopic"}
    assert g.pages["concepts/Квантование"]["kind"] == "wconcept"
    assert ("topics/Сжатие", "concepts/Квантование") in g.links
    assert g.card_links["sources/B"] == {"topics/Сжатие", "concepts/Квантование"}
    assert g.missing["concepts/Прунинг"] == {"concepts/Квантование"}       # упомянута, страницы нет
    # ответ Obsidian CLI (resolvedLinks) важнее разбора файлов
    g2 = wiki_graph.load(tmp_path, {"wiki/topics/Сжатие.md": {}, "wiki/sources/B.md": {"wiki/topics/Сжатие.md": 1}})
    assert ("topics/Сжатие", "concepts/Квантование") not in g2.links
    assert g2.card_links["sources/B"] == {"topics/Сжатие"}


def test_suggest_tags():
    texts = {"1": "Language models quantization", "2": "Small language models on edge",
             "3": "Language models: post-training quantization", "4": "Борщ и щи", "5": "Квантование сетей",
             "6": "Квантования моделей"}
    found = dict(wiki_graph.suggest_tags(texts, existing=["Сжатие"], min_books=2))
    assert found["language models"] == ["1", "2", "3"]
    assert found["quantization"] == ["1", "3"]
    assert sorted(found.get("квантование", found.get("квантования", []))) == ["5", "6"]   # одна основа
    assert not any(w in found for w in ("and", "on", "borsch"))
    assert "сжатие" not in found                                            # уже есть такая тема


def test_build_graph_with_wiki(clean_data, tmp_path):
    folder = make_lib(tmp_path / "Books")
    make_wiki(tmp_path)
    lib = Library()
    folder_scan.scan_folders(lib, [folder])
    b = bid_of(lib, "sub/b.pdf")
    wiki = {"graph": wiki_graph.load(tmp_path), "cards": {b: "sources/B"},
            "texts": {b: "language models", bid_of(lib, "a.epub"): "language models"}}
    d = build_graph(lib, "all", wiki)
    ids = {n["id"] for n in d["nodes"]}
    assert "wtopic:topics/Сжатие" in ids and "wconcept:concepts/Квантование" in ids
    assert {"source": b, "target": "wconcept:concepts/Квантование"} in d["links"]
    assert {"source": "wtopic:topics/Сжатие", "target": "wconcept:concepts/Квантование"} in d["pagelinks"]
    ghosts = {g["id"]: g for g in d["ghosts"]}
    assert ghosts["ghost:concepts/Прунинг"]["ghost"] == "page"
    assert ghosts["ghost:language models"]["ghost"] == "tag"
    assert all(k["on"] for k in d["kinds"])                                 # все виды включены по умолчанию
    assert next(n for n in d["nodes"] if n["id"] == b)["status"] == "unread"
