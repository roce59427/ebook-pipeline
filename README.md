# ebook-pipeline

Automates moving books you bought on Google Play Books / Kobo into your own reading setup, and bringing your highlights back into Obsidian:

```
Books: .acsm (inbox) → Adobe Digital Editions → Calibre library → clean EPUB folder → (optional) iCloud Drive
Notes: Readest Markdown export → Obsidian vault (with frontmatter)
```

The script only drives tools you already have installed (ADE, Calibre and its plugins). It does not contain any DRM code.

## Requirements

- Windows, Python 3.11+ (stdlib only)
- Adobe Digital Editions 4.5, authorized with your Adobe ID
- Calibre, with the import plugins you use already configured
- [Readest](https://readest.com) for reading and highlighting across devices (optional)
- iCloud for Windows (optional, only if you want EPUBs copied to iCloud Drive)

## Folder layout

A suggested layout; every path is configurable in `config.toml`.

```
Book\
├─ inbox\         ← downloaded .acsm files go here      (acsm_inbox)
├─ _done_acsm\    ← processed .acsm files are moved here (acsm_done)
├─ CleanEpub\     ← exported EPUBs                       (clean_epub)
├─ Note\          ← Readest note exports                 (notes_source)
└─ calibre\       ← Calibre library                      (calibre_library)
```

ADE always downloads into `Documents\My Digital Editions` (`ade_output`). That folder cannot be changed in ADE 4.5.

## Setup

```bash
cp config.example.toml config.toml
```

Edit `config.toml` with your own paths. It is git-ignored, so paths never get committed.

### Double-click launchers

| File | Same as |
| --- | --- |
| `import-books.bat` | `python ebook_pipeline.py` |
| `sync-notes.bat` | `python ebook_pipeline.py --notes` |

To run them from somewhere handy (e.g. your `Book\` folder or the desktop), right-click the `.bat` → **Show more options → Create shortcut**, then move the **shortcut** there. Don't copy the `.bat` itself: it finds `ebook_pipeline.py` relative to its own location.

## Usage

### Books

1. Download the `.acsm` from Play Books / Kobo into `acsm_inbox`.
2. **Close the Calibre GUI** (it locks the library for `calibredb`).
3. Run `import-books.bat` (or `python ebook_pipeline.py`).
4. Import the EPUB from `clean_epub` into Readest; it syncs to your other devices.

### Notes

1. In Readest, export the book's annotations as Markdown into `notes_source`.
2. Run `sync-notes.bat` (or `python ebook_pipeline.py --notes`).

Each note is written to `obsidian_notes` as `<title>.md` with frontmatter (`title`, `date`, `tags: [書摘]`, `source: readest`, `author`). A newer export of the same book overwrites the older note.

When you finish a book, export its notes first, then remove it from Readest cloud to free space. The EPUB stays in `clean_epub` and the Calibre library.

### Options

| Option | What it does |
| --- | --- |
| *(none)* | Process every `.acsm` in the inbox once |
| `--watch` | Keep polling the inbox |
| `--epub FILE` | Skip ADE; start from a book ADE already downloaded |
| `--notes` | Sync Readest note exports into Obsidian |

If an exported EPUB still carries Adobe DRM, the script stops before copying it anywhere. Leave `icloud` empty in `config.toml` to skip the iCloud step.
