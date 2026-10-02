"""ACSM -> Adobe Digital Editions -> Calibre -> clean EPUB -> iCloud Drive.

Usage:
    python ebook_pipeline.py                 # process every .acsm in the inbox once
    python ebook_pipeline.py --watch         # keep polling the inbox
    python ebook_pipeline.py --epub FILE     # skip ADE, start from an ADE-downloaded epub
    python ebook_pipeline.py --notes         # copy KyBook notes (iCloud) into Obsidian as .md
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

CONFIG_PATH = Path(__file__).with_name("config.toml")
BOOK_SUFFIXES = {".epub", ".pdf"}


class PipelineError(Exception):
    pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"Missing {CONFIG_PATH.name}. Copy config.example.toml to config.toml and edit the paths.")
    with CONFIG_PATH.open("rb") as f:
        config = tomllib.load(f)
    return {
        "acsm_inbox": Path(config["paths"]["acsm_inbox"]),
        "acsm_done": Path(config["paths"]["acsm_done"]),
        "ade_output": Path(config["paths"]["ade_output"]),
        "calibre_library": Path(config["paths"]["calibre_library"]),
        "clean_epub": Path(config["paths"]["clean_epub"]),
        "icloud": Path(config["paths"]["icloud"]) if config["paths"].get("icloud") else None,
        "notes_source": Path(config["paths"]["notes_source"]) if config["paths"].get("notes_source") else None,
        "obsidian_notes": Path(config["paths"]["obsidian_notes"]) if config["paths"].get("obsidian_notes") else None,
        "ade_exe": Path(config["apps"]["ade_exe"]),
        "calibredb_exe": Path(config["apps"]["calibredb_exe"]),
        "ade_timeout_sec": config["options"].get("ade_timeout_sec", 180),
        "export_template": config["options"].get("export_template", "{title} - {authors}"),
        "watch_interval_sec": config["options"].get("watch_interval_sec", 10),
    }


# ---------- Step 1: ADE fulfillment ----------

def snapshot_mtimes(folder: Path, suffixes: set[str]) -> dict[Path, float]:
    return {p: p.stat().st_mtime for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes}


def wait_until_stable(path: Path, checks: int = 3, interval: float = 1.0) -> None:
    last_size = -1
    stable_count = 0
    while stable_count < checks:
        size = path.stat().st_size
        stable_count = stable_count + 1 if size == last_size and size > 0 else 0
        last_size = size
        time.sleep(interval)


def fulfill_with_ade(acsm: Path, config: dict) -> Path:
    ade_output = config["ade_output"]
    before = snapshot_mtimes(ade_output, BOOK_SUFFIXES)
    print(f"  Opening in ADE: {acsm.name}")
    subprocess.Popen([str(config["ade_exe"]), str(acsm)])

    deadline = time.monotonic() + config["ade_timeout_sec"]
    while time.monotonic() < deadline:
        time.sleep(2)
        after = snapshot_mtimes(ade_output, BOOK_SUFFIXES)
        changed = [p for p, mtime in after.items() if before.get(p) != mtime]
        if changed:
            book = max(changed, key=lambda p: after[p])
            wait_until_stable(book)
            print(f"  ADE downloaded: {book.name}")
            return book
    raise PipelineError(
        f"No new book appeared in {ade_output} within {config['ade_timeout_sec']}s. "
        "If ADE already downloaded it before, rerun with --epub <file>."
    )


# ---------- Step 2: Calibre import (DeDRM plugin runs on import) ----------

def run_calibredb(config: dict, *args: str) -> str:
    command = [str(config["calibredb_exe"]), *args, "--with-library", str(config["calibre_library"])]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise PipelineError(f"calibredb {args[0]} failed:\n{result.stderr or result.stdout}")
    return result.stdout


def ensure_calibre_gui_closed() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq calibre.exe", "/NH"],
        capture_output=True, text=True, errors="replace",
    )
    if "calibre.exe" in result.stdout.lower():
        raise PipelineError("Calibre GUI is running and locks the library. Close it and rerun.")


def read_epub_title(epub: Path) -> str | None:
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "dc": "http://purl.org/dc/elements/1.1/"}
    try:
        with zipfile.ZipFile(epub) as zf:
            container = ElementTree.fromstring(zf.read("META-INF/container.xml"))
            opf_path = container.find(".//c:rootfile", ns).get("full-path")
            title = ElementTree.fromstring(zf.read(opf_path)).find(".//dc:title", ns)
            return title.text.strip() if title is not None and title.text else None
    except (zipfile.BadZipFile, KeyError, AttributeError, ElementTree.ParseError):
        return None


def import_to_calibre(book: Path, config: dict) -> int:
    output = run_calibredb(config, "add", str(book))
    added = re.search(r"Added book ids:\s*([\d,\s]+)", output)
    if added:
        book_id = int(added.group(1).split(",")[0])
        print(f"  Added to Calibre, id={book_id}")
        return book_id

    # Already in the library: look it up by exact title instead of adding a duplicate.
    title = read_epub_title(book) if book.suffix.lower() == ".epub" else None
    if not title:
        raise PipelineError(f"calibredb did not add the book and its title is unknown:\n{output}")
    escaped_title = title.replace('"', '\\"')
    ids = run_calibredb(config, "search", f'title:"={escaped_title}"').strip()
    if not ids:
        raise PipelineError(f"calibredb did not add '{title}' and could not find it:\n{output}")
    book_id = int(ids.split(",")[0])
    print(f"  Already in Calibre, id={book_id}")
    return book_id


# ---------- Step 3: export clean EPUB ----------

def has_adobe_drm(epub: Path) -> bool:
    with zipfile.ZipFile(epub) as zf:
        names = set(zf.namelist())
        if "META-INF/rights.xml" in names:
            return True
        if "META-INF/encryption.xml" in names:
            return b"ns.adobe.com/adept" in zf.read("META-INF/encryption.xml")
    return False


def export_from_calibre(book_id: int, config: dict) -> Path:
    clean_dir = config["clean_epub"]
    clean_dir.mkdir(parents=True, exist_ok=True)
    before = snapshot_mtimes(clean_dir, {".epub"})
    run_calibredb(
        config, "export", str(book_id),
        "--to-dir", str(clean_dir),
        "--single-dir",
        "--formats", "epub",
        "--template", config["export_template"],
        "--dont-save-cover",
        "--dont-write-opf",
    )
    after = snapshot_mtimes(clean_dir, {".epub"})
    changed = [p for p, mtime in after.items() if before.get(p) != mtime]
    if not changed:
        raise PipelineError(f"Calibre exported nothing for id={book_id} (is there an EPUB format?)")
    exported = max(changed, key=lambda p: after[p])
    if has_adobe_drm(exported):
        raise PipelineError(f"{exported.name} still has Adobe DRM. Check the DeDRM plugin / ADE key in Calibre.")
    print(f"  Exported: {exported}")
    return exported


# ---------- Step 4: iCloud Drive ----------

def copy_to_icloud(epub: Path, config: dict) -> None:
    icloud_dir = config["icloud"]
    if icloud_dir is None:
        print("  iCloud path not set, skipped.")
        return
    if not icloud_dir.exists():
        raise PipelineError(f"iCloud folder not found: {icloud_dir} (is iCloud for Windows installed and signed in?)")
    destination = icloud_dir / epub.name
    shutil.copy2(epub, destination)
    print(f"  Copied to iCloud: {destination}")


# ---------- KyBook notes -> Obsidian ----------

def decode_note(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("big5", errors="replace")


def note_filename(text: str, fallback: str) -> str:
    # KyBook exports start with "# Notes from <book title>".
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    match = re.match(r"#\s*Notes from\s+(.+)", first_line)
    title = match.group(1).strip() if match else fallback
    return re.sub(r'[\\/:*?"<>|]', "_", title) or fallback


def sync_notes(config: dict) -> None:
    source, target = config["notes_source"], config["obsidian_notes"]
    if source is None or target is None:
        raise PipelineError("Set notes_source and obsidian_notes in config.toml first.")
    if not source.exists():
        raise PipelineError(f"Notes folder not found: {source}")
    target.mkdir(parents=True, exist_ok=True)

    synced = 0
    # Oldest first, so a newer export of the same book overwrites an older one.
    for note in sorted(source.glob("*"), key=lambda p: p.stat().st_mtime):
        if note.suffix.lower() not in {".txt", ".md"}:
            continue
        text = decode_note(note.read_bytes())
        destination = target / f"{note_filename(text, note.stem)}.md"
        if destination.exists() and destination.stat().st_mtime >= note.stat().st_mtime:
            continue
        destination.write_text(text, encoding="utf-8", newline="\n")
        print(f"  Note -> {destination}")
        synced += 1
    print(f"  {synced} note(s) synced.")


# ---------- Orchestration ----------

def process_book(book: Path, config: dict) -> None:
    ensure_calibre_gui_closed()
    book_id = import_to_calibre(book, config)
    clean_epub = export_from_calibre(book_id, config)
    copy_to_icloud(clean_epub, config)


def process_acsm(acsm: Path, config: dict) -> None:
    print(f"[{acsm.name}]")
    ensure_calibre_gui_closed()
    book = fulfill_with_ade(acsm, config)
    process_book(book, config)
    config["acsm_done"].mkdir(parents=True, exist_ok=True)
    shutil.move(str(acsm), config["acsm_done"] / acsm.name)
    print("  Done.")


def pending_acsm_files(config: dict) -> list[Path]:
    return sorted(config["acsm_inbox"].glob("*.acsm"), key=lambda p: p.stat().st_mtime)


def run_once(config: dict) -> int:
    failures = 0
    for acsm in pending_acsm_files(config):
        try:
            process_acsm(acsm, config)
        except PipelineError as error:
            failures += 1
            print(f"  ERROR: {error}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="ACSM -> ADE -> Calibre -> iCloud")
    parser.add_argument("--watch", action="store_true", help="keep polling the ACSM inbox")
    parser.add_argument("--epub", type=Path, help="skip ADE and process this already-downloaded book")
    parser.add_argument("--notes", action="store_true", help="copy KyBook notes from iCloud into Obsidian as .md")
    args = parser.parse_args()
    config = load_config()

    if args.notes:
        try:
            sync_notes(config)
        except PipelineError as error:
            sys.exit(f"  ERROR: {error}")
        return

    if args.epub:
        try:
            print(f"[{args.epub.name}]")
            process_book(args.epub, config)
        except PipelineError as error:
            sys.exit(f"  ERROR: {error}")
        return

    if not args.watch:
        if not pending_acsm_files(config):
            print(f"No .acsm files in {config['acsm_inbox']}")
        sys.exit(1 if run_once(config) else 0)

    print(f"Watching {config['acsm_inbox']} (Ctrl+C to stop)")
    while True:
        run_once(config)
        time.sleep(config["watch_interval_sec"])


if __name__ == "__main__":
    main()
