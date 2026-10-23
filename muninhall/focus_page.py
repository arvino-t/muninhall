"""Страница фокуса в вики: `wiki/plans/Фокус — <тема>.md` — теги, прогресс, книги со ссылками на карточки
и выделения; её читает планирование локального ассистента. Блок приложения — между метками, текст вокруг цел."""
from __future__ import annotations

from datetime import date

from . import vault as vault_mod
from .book_tags import kind_names
from .core import log
from .i18n import tr
from .obsidian import BLOCK_END, BLOCK_START, merge_page, safe_name


class FocusPage:
    def __init__(self, link, library, focus, pages):
        self.link = link
        self.library = library
        self.focus = focus
        self.pages = pages              # HighlightPages — где лежит страница выделений книги

    def export(self):
        """Страницы активных фокусов (до двух) в вики."""
        for f in self.focus.actives:
            self._export(self.focus, f)

    def _export(self, focus, f):
        """wiki/plans/Фокус — <тема>.md: цель, теги, прогресс, книги со ссылками на карточки и выделения."""
        if not self.link.enabled or not f:
            return
        v = self.link.vault()
        if not v:
            return
        today = date.today().isoformat()
        rel = f"wiki/plans/{safe_name(tr('Фокус — {0}', f['name']))}.md"
        header = {"type": "plan", "horizon": "focus", "title": tr("Фокус — {0}", f["name"]), "status": "active",
                  "created": today, "updated": today}
        self._archive_old(v, focus, rel, today)
        existing = v.read_page(rel)
        text = merge_page(existing, header, "\n".join(self._block(v, focus, f)))
        if text == existing:
            return
        try:
            v.write_page(rel, text)
            if existing is None:
                v.append_log(f"## [{today}] plan | {header['title']}")
        except OSError as e:
            log("страница фокуса не записана:", rel, e)

    def _block(self, v, focus, f) -> list[str]:
        """Блок приложения: теги, прогресс, книги по группам (читаю, дальше по релевантности, прочитано)."""
        p = focus.progress(f)
        kinds = kind_names()
        groups = {"reading": [], "unread": [], "finished": []}
        for b in focus.ranked(f) + [b for b in p["books"] if self.library.status(b) == "finished"]:
            groups[self.library.status(b)].append(b)
        lines = [BLOCK_START, tr("<!-- Блок обновляет Muninhall. Свои цели и выводы пишите выше или ниже. -->"),
                 "", f"**{tr('Теги фокуса')}:** " + ", ".join(f"{n} ({kinds.get(k, k)})" for k, n in f["labels"]),
                 f"**{tr('Прогресс')}:** " + tr("прочитано {0} из {1}, читаю {2}; достаточно — {3}",
                                                 p["finished"], p["total"], p["reading"], f.get("enough", 5))]
        if p["enough"]:
            lines.append(tr("**Прочитано достаточно** — время закрепить в вики (понятия, синтез) и сменить фокус."))
        for key, title in (("reading", tr("Читаю")), ("unread", tr("Дальше (по релевантности)")),
                           ("finished", tr("Прочитано"))):
            if groups[key]:
                lines += ["", f"## {title}", *(self._book_line(v, b) for b in groups[key][:40])]
        lines.append(BLOCK_END)
        return lines

    def _book_line(self, v, b) -> str:
        """- [[sources/Карточка|Название]] · [[highlights/…|выделения]]"""
        card = v.find_card(self.library.file_path(b), b.get("title"))
        title = b.get("title") or ""
        ref = f"[[{v.card_link(card)[2:-2]}|{title}]]" if card else title
        hl = self.pages.page_rel(b, card)
        has_hl = v.read_page(hl) is not None
        return f"- {ref}" + (f" · [[{hl[5:-3]}|{tr('выделения')}]]" if has_hl else "")

    @staticmethod
    def _archive_old(v, focus, rel, today):
        """Страницы прежних фокусов — уже не активные (по статусу ассистент находит текущий фокус)."""
        active_titles = {tr("Фокус — {0}", x["name"]) for x in focus.actives}
        for page in (v.root / "wiki" / "plans").glob(f"{safe_name(tr('Фокус — {0}', ''))}*.md"):
            prel = page.relative_to(v.root).as_posix()
            ptext = v.read_page(prel) or ""
            props = vault_mod.parse_frontmatter(ptext)
            if prel != rel and props.get("status") == "active" and props.get("title") not in active_titles:
                v.write_page(prel, vault_mod.set_frontmatter(ptext, status="archived", updated=today))
