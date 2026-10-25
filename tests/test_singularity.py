from muninhall.singularity import SingularitySync


class FakeApi:
    """Отдаёт страницы как сервер Singularity: часть записей отфильтрована уже после разбиения."""
    _list_all = SingularitySync._list_all

    def __init__(self, pages):
        self.pages = pages
        self.offsets = []

    def _request(self, method, path, query=None, done=None):
        self.offsets.append(query["offset"])
        page = self.pages.get(query["offset"], [])
        done(200, {"tasks": page}, "")


def ids(n, start=0):
    return [{"id": f"T-{i}"} for i in range(start, start + n)]


def collect(api):
    out = {}
    api._list_all("/task", "tasks", {}, lambda items, st, err: out.update(items=items))
    return out["items"]


def test_short_page_is_not_the_end():
    # первая страница неполная (480 из 500), но дальше есть ещё задачи
    api = FakeApi({0: ids(480), 480: ids(30, 480)})
    assert len(collect(api)) == 510
    assert api.offsets == [0, 480, 510]


def test_stops_when_server_ignores_offset():
    api = FakeApi({0: ids(10), 10: ids(10)})
    assert len(collect(api)) == 10
    assert api.offsets == [0, 10]


class ProjectsApi:
    """Сервер с проектами для _ensure_project: запоминает созданные."""
    _list_all = SingularitySync._list_all
    _ensure_project = SingularitySync._ensure_project

    def __init__(self, projects, chosen=None):
        self.projects = projects
        self.state = {"ids": {}, "booksProject": chosen, "wishlistProject": None}
        self._verified = set()
        self._errors = []
        self.created = []

    def save(self):
        pass

    def _request(self, method, path, body=None, query=None, done=None):
        if method == "POST":
            self.created.append(body)
            done(201, {"id": "P-new"}, "")
        else:
            done(200, {"projects": self.projects if not query["offset"] else []}, "")


def ensure(api):
    out = {}
    api._ensure_project("litreader-project-books", "Книги", "1f4da", lambda pid: out.update(pid=pid))
    return out["pid"]


def test_chosen_project_is_used():
    api = ProjectsApi([{"id": "P-edu", "title": "Education"}], chosen="P-edu")
    assert ensure(api) == "P-edu"
    assert api.created == [] and api.state["ids"] == {}


def test_deleted_chosen_project_falls_back_to_own():
    api = ProjectsApi([{"id": "P-edu", "title": "Education", "deleteDate": "2026-10-25"}], chosen="P-edu")
    assert ensure(api) == "P-new"
    assert api.state["booksProject"] is None
    assert api.created[0]["externalId"] == "litreader-project-books"
    assert len(api._errors) == 1


def test_own_project_found_by_external_id():
    api = ProjectsApi([{"id": "P-own", "title": "Книги", "externalId": "litreader-project-books"}])
    assert ensure(api) == "P-own"
    assert api.created == []
