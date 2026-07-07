#!/usr/bin/env python3
"""Ingest PDF rulebooks into the skull's offline Rules/ library.

Converts one or more PDFs into the same per-page Markdown + manifest.json layout
the skull already reads (see skull/search.py). Run this once, on a real computer
(NOT the Pi) — it needs PyMuPDF, which is only a dev-time dependency:

    pip install pymupdf

Usage:
    # Ingest every PDF in a folder into Rules/warhammer40k/
    python Rules/ingest_pdf.py warhammer40k "/path/to/40k Rules"

    # Ingest specific files
    python Rules/ingest_pdf.py warhammer40k a.pdf b.pdf

    # One Markdown file per PDF instead of per page (better for prose books)
    python Rules/ingest_pdf.py mygame book.pdf --split doc

Each PDF becomes a subfolder (named from its filename) with one Markdown file per
page. A page's first heading-like line becomes its title, which the skull's
relevance ranking weights heavily — so these lay-out-per-page rulebooks (each page
is a detachment / datasheet / section) rank very well out of the box.

These are third-party copyrighted rules kept for personal local reference only.
Rules/ is git-ignored — never commit or redistribute the output.
"""
import argparse
import json
import pathlib
import re
import sys

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF is required: pip install pymupdf")


# Unicode punctuation the PDFs use → ASCII, so the text reads cleanly and matches
# plain-hyphen / straight-quote search queries.
_NORMALIZE = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", " ": " ", "•": "-", "▪": "-", "■": "-",
    "◦": "-", "–": "-", "ﬁ": "fi", "ﬂ": "fl",
}


def _normalize(text: str) -> str:
    for bad, good in _NORMALIZE.items():
        text = text.replace(bad, good)
    # Drop the replacement char (failed glyph decodes — e.g. contents dot-leaders).
    text = text.replace("�", "")
    # Strip any remaining control chars but keep newlines/tabs.
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    # Collapse dot-leaders and repeated spaces; tidy blank lines.
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _slug(s: str, maxlen: int = 60) -> str:
    s = _normalize(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen].strip("-") or "untitled"


def _doc_slug(stem: str) -> str:
    """Derive a clean folder name from a GW-style PDF filename.

    e.g. 'eng_10-06_warhammer40000_faction_pack_world_eaters-az7..-d9r..'
         -> 'world-eaters'
    Words are separated by '_'; hash suffixes are '-'-separated ~10-char tokens."""
    name = stem
    # Strip up to two trailing '-'-separated hash tokens (>=9 alnum chars). Real
    # multi-word names use '_' between words, so this won't eat 'space-marines'.
    for _ in range(2):
        name = re.sub(r"-[a-z0-9]{9,}$", "", name)
    # Strip common GW filename boilerplate prefixes.
    name = re.sub(r"^eng_\d\d-\d\d_", "", name)
    for junk in ("warhammer40000_", "warhammer40k_", "new40k_", "faction_pack_"):
        name = name.replace(junk, "")
    return _slug(name)


def _doc_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def _page_title(text: str, fallback: str) -> str:
    """First heading-like line of a page (>=3 letters, not a bare number)."""
    for line in text.splitlines()[:6]:
        s = line.strip()
        if s.isdigit():
            continue
        if len(re.sub(r"[^A-Za-z]", "", s)) >= 3:
            return re.sub(r"\s+", " ", s)[:80]
    return fallback


def ingest_pdf(pdf: pathlib.Path, game_dir: pathlib.Path, split: str) -> list[dict]:
    """Convert one PDF to Markdown page(s); return manifest entries."""
    doc_slug = _doc_slug(pdf.stem)
    doc_name = _doc_title(doc_slug)
    out_dir = game_dir / doc_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    with fitz.open(pdf) as doc:
        pages = [_normalize(page.get_text("text")) for page in doc]

    if split == "doc":
        body = "\n\n".join(f"{p}" for p in pages if len(p) > 20)
        if not body:
            return entries
        fname = f"{doc_slug}.md"
        header = f"> Source: {doc_name} ({pdf.name})\n\n# {doc_name}\n\n"
        (out_dir / fname).write_text(header + body, encoding="utf-8")
        entries.append({
            "path": doc_slug, "file": f"{doc_slug}/{fname}",
            "title": doc_name, "url": f"{doc_name} ({pdf.name})",
        })
        return entries

    for n, text in enumerate(pages, start=1):
        if len(text) < 20:  # cover art / near-blank page — skip
            continue
        title = _page_title(text, f"{doc_name} p.{n}")
        fname = f"p{n:02d}-{_slug(title, 50)}.md"
        src = f"{doc_name}, p.{n}"
        header = f"> Source: {src} ({pdf.name})\n\n# {title}\n\n"
        (out_dir / fname).write_text(header + text, encoding="utf-8")
        entries.append({
            "path": f"{doc_slug}/p{n:02d}", "file": f"{doc_slug}/{fname}",
            "title": title, "url": src,
        })
    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest PDF rulebooks into Rules/<game>/")
    ap.add_argument("game", help="Game slug, e.g. warhammer40k")
    ap.add_argument("inputs", nargs="+", help="PDF file(s) or folder(s) of PDFs")
    ap.add_argument("--split", choices=("page", "doc"), default="page",
                    help="One Markdown file per page (default) or per PDF")
    ap.add_argument("--rules-dir", default=None,
                    help="Rules/ root (default: alongside this script)")
    args = ap.parse_args()

    rules_root = (pathlib.Path(args.rules_dir).expanduser() if args.rules_dir
                  else pathlib.Path(__file__).resolve().parent)
    game_dir = rules_root / args.game

    pdfs: list[pathlib.Path] = []
    for item in args.inputs:
        p = pathlib.Path(item).expanduser()
        if p.is_dir():
            pdfs.extend(sorted(p.glob("*.pdf")))
        elif p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            print(f"  ! skipping non-PDF: {p}")
    if not pdfs:
        sys.exit("No PDFs found.")

    manifest: list[dict] = []
    for pdf in pdfs:
        entries = ingest_pdf(pdf, game_dir, args.split)
        print(f"  {pdf.name}  ->  {len(entries)} page(s)")
        manifest.extend(entries)

    (game_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(manifest)} pages across {len(pdfs)} PDF(s) to {game_dir}")
    print(f"Manifest: {game_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
