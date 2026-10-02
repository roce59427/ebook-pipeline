# ebook-pipeline

Automates moving books you bought on Google Play Books / Kobo into your own reading setup:

```
.acsm (inbox) → Adobe Digital Editions → Calibre library → clean EPUB folder → iCloud Drive
```

The script only drives tools you already have installed (ADE, Calibre and its plugins). It does not contain any DRM code.

## Requirements

- Windows, Python 3.11+ (stdlib only)
- Adobe Digital Editions 4.5, authorized with your Adobe ID
- Calibre, with the import plugins you use already configured
- iCloud for Windows (optional, for the last step)

## Setup

```bash
cp config.example.toml config.toml
```

Edit `config.toml` with your own paths. It is git-ignored, so paths never get committed.

## Usage

1. Download the `.acsm` from Play Books / Kobo into `acsm_inbox`.
2. **Close the Calibre GUI** (it locks the library for `calibredb`).
3. Run:

```bash
python ebook_pipeline.py
```

| Option | What it does |
| --- | --- |
| *(none)* | Process every `.acsm` in the inbox once |
| `--watch` | Keep polling the inbox |
| `--epub FILE` | Skip ADE; start from a book ADE already downloaded |
| `--notes` | Copy Readest note exports from `notes_source` into `obsidian_notes` as UTF-8 `.md` with frontmatter (title, author, date, source) |

Processed `.acsm` files are moved to `acsm_done`. If an exported EPUB still carries Adobe DRM, the script stops before copying it to iCloud.
