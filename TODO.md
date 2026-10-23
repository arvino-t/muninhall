# TODO

Ideas for the next versions, most useful first. Finished items move to [CHANGELOG.md](CHANGELOG.md).
Reviewed: 2026-10-10 (after 1.1.0).

## Check first
- [ ] **LitRes with a real session after the connector move (0.15), the lazy Chromium (0.18) and the
  sync/download split (1.1):** sign-in, F5 sync, downloading one book and "Download all", LitRes folders,
  the position from the phone. Sync and download logic are tested against a fake server
  (`tests/test_litres_connector.py`); the real site and the web view are not.
- [ ] **Installers on real machines:** `Muninhall-Setup-*.exe` on Windows 10/11 (install, file
  associations, uninstall, restart after a restore in the frozen build) and `Muninhall.flatpak` on Linux
  (data shared with the native install, LitRes sign-in inside the sandbox).

## Second brain (Obsidian vault) — the direction
Goal: see which topics I have mastered, where to look next, which tips and reminders the books give,
and use the wiki for my own projects (incl. AI). The vault (Karpathy's LLM Wiki in `~/Documents`) is
the knowledge base; the app talks to it through the Obsidian CLI, with a plain-file fallback.
- [ ] **Mastery map** (the graph analysis covers topics, read / reading / not started and what's missing):
  add reading time per topic, highlights and question highlights per topic, a dedicated page outside the
  graph; better possible-tag suggestions for Russian titles (lemmatization instead of crude stemming).
- [ ] **Daily review — next:** copy the day's quotes to the Obsidian daily note (the Daily notes core plugin
  is off in the vault — decide the folder), a history of answers, FB2/MOBI passages.
- [ ] **Singularity reminders from books** — plan separately how to present them (tasks, habits, notes).
- [ ] **Growth focus — next:** a deadline and a reading pace per focus; a history view of past focuses
  (what was read, highlights, wiki pages created); Singularity task for the focus.
- [ ] **Projects:** `wiki/projects/` pages; the app shows books, quotes and concepts for a project.

## Reader
- [ ] **Full-text search in a book** with jumping to results — foliate-js has it, needs a UI.
- [ ] **Bookmarks** — several marked places in a book, not only the last one (stored in `.library/`
  for your own books).
- [ ] **Dictionary and translation of the selected word** — for books and articles in English.
- [ ] **Read aloud in the Flatpak** — QtTextToSpeech needs speech-dispatcher (`libspeechd` and the host
  socket); today it is unavailable there.

## Libraries
- [ ] **More pluggable libraries:** OPDS catalogs (Calibre server, public catalogs) and other stores as
  connectors next to LitRes (a new `LibrarySource` subclass in `libraries.KINDS`; `litres_connector.py` is the pattern for sync).
- [ ] **Conflicting `.library` copies** — when a library folder is edited on two computers, cloud sync
  (rclone) leaves conflict copies; merge them (positions — latest wins, marks and bookmarks — union).
- [ ] **Library metadata from files:** books in library folders are titled by the file name (recomputed on
  every scan); read title, authors and cover from EPUB/FB2 metadata during the scan. PDF covers already
  come from the first page; a file opened with "Open file" already takes title and author from the book.
- [ ] **Rework the backup logic** — per-library backups are done. Still to revisit: restoring one library
  without a restart, automatic backups per library, how backups relate to cloud sync.
- [ ] **Sync app-level data with the cloud** — your libraries' data already travels with their folders
  (`.library/`); what's left is LitRes data, statistics and settings. Google Drive (`appDataFolder`) or
  Yandex Disk (`app:/`), OAuth in the browser, token in the keyring or 0600; merging: positions — latest
  wins, statistics — per day with the maximum; works offline.
- [ ] **New books by favourite authors and series**: "the next book in the series is out" with a link to
  buy it on LitRes.
- [ ] **Download new LitRes purchases automatically**; how much space downloaded books take; removing
  downloaded finished books.

## Statistics and habit
- [ ] **Weekly and yearly goals** ("24 books a year") in addition to the daily one; monthly and yearly
  summaries; an estimate of when you'll finish the current book at your pace.
- [ ] **Evening reminder to read** if the daily goal isn't reached.

## Appearance and convenience
- [ ] **Narrow window mode is unreachable:** the window's minimum width is 1025 px (header and filter bar
  size hints), so the "Continue reading" panel, which hides below 900 px, never hides; let the filter bar
  wrap or shrink so the window can get narrower (tablet portrait).
- [ ] **Menu and tooltip labels follow custom shortcuts** — "Book graph (Ctrl+G)", "Search (Ctrl+F)" still
  show the defaults after a shortcut is changed.
- [ ] **App icon choice on Windows** — today it changes only the window icon; the Start menu and desktop
  shortcuts keep the installer's icon.
- [ ] **Tablet mode**: large page-turn zones, volume keys to turn pages, rotation without losing the place.
- [ ] **A note on a finished book** when marking it as read: a rating and a couple of lines that go to the
  book's card in the wiki.

## Performance
- [ ] **Stale cover thumbnails** are never deleted — prune `<cache>/thumbs` of covers that no longer exist
  (the cache is rebuilt once after an update, ~3.5 s).

## Distribution
- [ ] **Flathub** — submit the Flatpak; metainfo still lacks screenshots, and release notes there are
  written for 1.0.0 and 1.1.0 only.
- [ ] **Windows code signing** — the unsigned installer triggers a SmartScreen warning.
- [ ] **Update check** — tell the user when a newer release is on GitHub.
