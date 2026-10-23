# Muninhall

A desktop app for Linux and Windows to build, read and organize **your own library** of e-books and
articles, and to look after it with extra features. A library is a folder on disk (EPUB, FB2, MOBI,
PDF); you can add several and browse them together as one big library. Each library keeps its data
(marks, reading positions, graph) inside its folder, has its own graph and its own backups.
[LitRes](https://www.litres.ru) is a pluggable commercial library: the app signs in on the LitRes
website in a built-in browser and downloads purchased books and audiobooks. Books open in a built-in
reader and audiobook player (M4B, MP3). The UI follows GNOME's libadwaita style on both systems and
is available in Russian and English.

*Muninhall* — "the hall of Muninn", Odin's raven of memory. Formerly *Читалка ЛитРес* (LitRes
Reader), briefly *Shelfwise* in 0.16; data from the previous versions is migrated automatically.

**User guide:** [English](docs/en/user-guide.md) · [Русский](docs/ru/user-guide.md)

## Features

- **Libraries** — named folder libraries with subfolder filtering; files are opened in place, data
  lives in `<library>/.library/` and travels with the folder (e.g. via cloud sync).
- **LitRes (optional)** — purchased books and audiobooks, LitRes folders, "read" marks synced both
  ways, download one book or all of them at once; can be disconnected.
- **Reader** — page turning by tap, swipe and keys; themes, fonts and layout; contents; gestures;
  auto page turn; read aloud with sentence highlighting; PDF via pdf.js.
- **Growth focus** — your current reading priority: next relevant book, progress, a nudge to switch topics.
- **Daily review** — one of your quotes by spaced repetition and a random passage from a book you read.
- **Highlights and notes** — four meaning colors (important, advice, concept, question) and notes in
  EPUB, FB2, MOBI and PDF; a list of quotes per book.
- **Obsidian "second brain"** — highlights go to your vault (Karpathy's LLM Wiki layout) as
  `wiki/highlights/<Book>.md` with `muninhall://` links back to the quote; reading status and tags are
  kept in the book's card; works through the official Obsidian CLI or plain files.
- **Audiobook player** — M4B chapters, speed 0.75–2× without pitch change, sleep timer, background
  playback.
- **Continue reading** — resumes the last book on startup and picks up the position from your phone
  or the LitRes website.
- **Book graph** — an Obsidian-style graph of books and tags (genres, folders, series, authors,
  topics, wiki tags and pages from Obsidian), possible tags and an analysis (mastered topics, where to
  look next, bridges between areas), per library or for all of them.
- **Reading statistics** — minutes per day, streaks, finished books, including reading on the phone;
  for all libraries or one.
- **Backups** — manual and scheduled backups for all libraries or one; restore from a list or a file.
- **Singularity integration** — "Reading" tasks, progress notes and a daily reading habit in
  [SingularityApp](https://singularity-app.com).

## Installation

Ready-made installers are attached to every [release](https://github.com/arvino-t/muninhall/releases):
`Muninhall-Setup-<version>.exe` for Windows (per-user, no Python needed) and `Muninhall.flatpak` for Linux.

### Linux (Fedora, Ubuntu/Debian, Arch)

```
bash install.sh              # install or update
bash install.sh --uninstall  # remove
```

Installs for the current user into `~/.local/opt/muninhall` (a venv with PySide6), adds the
`muninhall` command, a menu entry and file associations. `sudo` is requested only for missing
system libraries.

### Windows 10/11

Double-click `install.cmd` (or `powershell -ExecutionPolicy Bypass -File windows\install.ps1`).
No administrator rights needed; Python 3.12 is installed via winget if Python 3.10+ is missing.

See the user guide for details. The first installation downloads PySide6 (~600 MB).

## Development

### Run from source

```
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/muninhall
```

Requires Python 3.10+ and `PySide6>=6.10,<6.12` (Qt 6 with QtWebEngine).

### Tests

```
.venv/bin/pip install -e .[dev]
.venv/bin/python -m pytest
```

The tests use the source tree and a temporary data directory (never your real data). They cover
the library model and folder scanning, library stores and migration, backups (all and per library),
the graph scope, per-library statistics, the Singularity filter, settings autosave, library kinds, LitRes sync and
download against a fake server, translation coverage and package data.

Scenario check on the installed build (Linux) — filters, reader, player, dialogs, settings tabs, graph,
LitRes connect/disconnect — against a copy of your data in a temporary profile:

```
bash install.sh && bash tools/flow_check.sh
```

Environment variables:

| Variable | Effect |
|---|---|
| `MUNINHALL_DEBUG=1` | verbose log: LitRes requests, downloads, page messages; DevTools via right click in the reader |
| `MUNINHALL_LANG=en\|ru` | force the interface language |

### Project layout

| Path | Contents |
|---|---|
| `muninhall/app.py` | `App`: window, navigation, libraries, reader/player wiring, backups, app startup |
| `muninhall/library.py` | `LibraryView`: the library page — filters, cards created in batches, covers, book menu (`app.library_view`) |
| `muninhall/appearance.py` | appearance (mixin of `App`): theme, accent, app icon, keyboard shortcuts (`SHORTCUTS`) |
| `muninhall/core.py` | paths, default settings, data migration, small helpers |
| `muninhall/model.py` | the `Library` model: books of all libraries, order, reading positions, status and percent |
| `muninhall/library_store.py` | `LibraryStore`: `library.json`, `progress.json` and the `.library/` stores (writes only changes) |
| `muninhall/folder_scan.py` | scanning your libraries' folders and migrating their data into `.library/` |
| `muninhall/litres_data.py` | LitRes data: merging the account's books, "Reading now", LitRes folders and their queue |
| `muninhall/reading_stats.py` | `ReadingStats`: time per day, book and library, finished books (`stats.json`) |
| `muninhall/libraries.py` | the registry of libraries (`libraries` setting) and its migration |
| `muninhall/litres_connector.py` | the LitRes connector: sign-in, sync, downloads, remote position (`litres_folders.py` — folders dialog) |
| `muninhall/litres.py` | LitRes session and API inside the built-in Chromium (QtWebEngine) |
| `muninhall/reader.py` | reader page (foliate-js in QtWebEngine), `litreader://` scheme |
| `muninhall/reader_highlights.py` | highlights in the reader: list, menu, note dialog |
| `muninhall/highlights.py` | `HighlightStore`: highlights per book (library `.library/` or app data) |
| `muninhall/vault.py` | Obsidian vault access: `CliVault` (Obsidian CLI) and `FileVault` (Markdown files) |
| `muninhall/obsidian.py` | `VaultLink` (the vault connection) and `HighlightPages` (wiki/highlights pages) |
| `muninhall/wiki_cards.py` | reading status and tags in the books' wiki cards; card tags for the graph and focus |
| `muninhall/focus_page.py` | the focus page in the wiki (`wiki/plans/Фокус — …`) |
| `muninhall/book_tags.py` | one set of rules for a book's tags (graph, focus) and their kind names |
| `muninhall/mastery.py`, `mastery_page.py` | the mastery map: topic levels, tips, the page and its wiki copy |
| `muninhall/wiki_graph.py` | the wiki graph for the book graph (pages, links, cards) and possible tags |
| `muninhall/review.py`, `review_widget.py` | daily review: spaced repetition of highlights, random passages; the panel section |
| `muninhall/focus.py`, `focus_dialog.py`, `focus_widget.py` | growth focus: focus books, next book, switch advice; dialog; panel section |
| `muninhall/tags_dialog.py` | the book's "Tags" dialog |
| `muninhall/player.py` | audiobook player (QtMultimedia), M4B chapter parsing |
| `muninhall/settings.py` | settings page (tabs: General, Reading, Integrations, Backups, Advanced) |
| `muninhall/backup.py` | backup archives (all libraries or one) and two-step restore |
| `muninhall/graph.py` | book graph data and page |
| `muninhall/stats.py` | reading statistics dialog |
| `muninhall/singularity.py` | SingularityApp sync and its settings window |
| `muninhall/i18n.py`, `i18n_en.py` | translations: `tr()` with Russian source strings as keys, English dictionary |
| `muninhall/widgets.py`, `style.py` | libadwaita-style widgets and stylesheet |
| `muninhall/web/` | reader and graph pages, `litres-hook.js` (passes API headers from the LitRes site; doesn't touch passwords or forms) |
| `muninhall/web/foliate/` | [foliate-js](https://github.com/johnfactotum/foliate-js) rendering engine (MIT) with pdf.js |
| `muninhall/web/vendor/` | d3-force, d3-quadtree, d3-dispatch, d3-timer (ISC) for the graph |
| `muninhall/data/sym/` | Adwaita symbolic icons (CC-BY-SA 3.0 / LGPLv3) |
| `install.sh`, `install.cmd`, `windows/` | installers |
| `vpn-bypass/` | Linux scripts to reach LitRes directly while a VPN is on |
| `docs/en/`, `docs/ru/` | user guide in English and Russian |
| `tests/` | pytest suite |
| `tools/flow_check.sh` | scenario check of the installed build |

### Translations

UI strings are written in Russian and wrapped in `tr()`: `tr("Скачано {0} из {1}", done, total)`.
The English text for each string lives in `muninhall/i18n_en.py`; plurals use `plural()`.
Strings for the web pages are listed in `WEB_KEYS` in `i18n.py` and passed to the page with its data.
When adding a string, add its English translation too — a missing one falls back to Russian.

### Packaging note

Every asset folder must be listed in `[tool.setuptools.package-data]` in `pyproject.toml`.
Test features against the installed package (`bash install.sh`), not only the source tree.

### Packaging

`packaging/windows` — PyInstaller spec and Inno Setup script (one per-user installer);
`packaging/flatpak` — Flatpak manifest (freedesktop 24.08 runtime + PySide6 wheels), desktop entry and
metainfo (the runtime lacks Kerberos, so `krb5` is built; read aloud is unavailable in the Flatpak — no
speech-dispatcher). Both are built by `.github/workflows/build.yml` (manually or on a `v*` tag), which runs the tests,
smoke-tests each build (`MUNINHALL_SMOKE_TEST=1` starts the app, builds the library and exits) and attaches
the installers to the release.

### Releases

Bump the version in `pyproject.toml` and `muninhall/__init__.py`, move the "Unreleased"
section of [CHANGELOG.md](CHANGELOG.md) under the new version, tag `vX.Y.Z` and publish a GitHub
release with that section as notes. Planned work is in [TODO.md](TODO.md).

## Security

- Scripts inside books are not executed (page CSP); external images and fonts from books are not
  loaded.
- Links from books open in the system only for `http`, `https` and `mailto`.
- LitRes API calls run in an isolated JavaScript world of the litres.ru page; responses carry a
  random session token so site scripts can't forge them.
- PDFs are rendered by pdf.js with `eval` disabled; book files are served only by a one-time token
  of the open book.
- Data files (library, progress, settings, tokens, backups) are created with 0600 permissions.

## Limitations

- LitRes has no public API; the app uses the same endpoints as the website (some were found by the
  [bookvault](https://github.com/mavrovde/bookvault) project). If LitRes changes them, the book
  list or downloads will break.
- DRM-protected and online-only books don't open.
- Only the "read" mark is written back to LitRes, not the exact position.
- No automatic hyphenation: QtWebEngine ships without hyphenation dictionaries.

## License

MIT.
