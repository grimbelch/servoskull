#!/usr/bin/env python3
"""Ingest PDF rulebooks into the skull's offline Rules/ library.

Converts one or more PDFs into the same per-page Markdown + manifest.json layout
the skull already reads (see skull/search.py). Run this once, on a real computer
(NOT the Pi) — it needs pymupdf4llm, which is only a dev-time dependency:

    pip install pymupdf4llm

Usage:
    # Ingest every PDF in a folder into Rules/warhammer40k/
    python Rules/ingest_pdf.py warhammer40k "/path/to/40k Rules"

    # Ingest specific files
    python Rules/ingest_pdf.py warhammer40k a.pdf b.pdf

    # One Markdown file per PDF instead of per page (better for prose books)
    python Rules/ingest_pdf.py mygame book.pdf --split doc

Each PDF becomes a subfolder (named from its filename) with one Markdown file per
page. Body text/tables/columns are extracted with pymupdf4llm (proper Markdown
tables, multi-column aware). Wargaming datasheet STAT BLOCKS (M/T/SV/W/LD/OC) are
graphical boxes that no text extractor reads correctly, so they are reconstructed
separately from word geometry and prepended as a clean, labelled profile list —
otherwise the stats come out as an ambiguous one-value-per-line jumble and the
skull misreads them.

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
    import pymupdf4llm
except ImportError:
    sys.exit("pymupdf4llm is required: pip install pymupdf4llm")


# Unicode punctuation the PDFs use → ASCII, so the text reads cleanly and matches
# plain-hyphen / straight-quote search queries.
_NORMALIZE = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", " ": " ", "•": "-", "▪": "-", "■": "-",
    "◦": "-", "ﬁ": "fi", "ﬂ": "fl",
}


def _normalize(text: str) -> str:
    for bad, good in _NORMALIZE.items():
        text = text.replace(bad, good)
    text = text.replace("�", "")  # failed glyph decodes (e.g. dot-leaders)
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
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
    for _ in range(2):  # strip up to two trailing '-'-separated hash tokens
        name = re.sub(r"-[a-z0-9]{9,}$", "", name)
    name = re.sub(r"^eng_\d\d-\d\d_", "", name)
    for junk in ("warhammer40000_", "warhammer40k_", "new40k_", "faction_pack_"):
        name = name.replace(junk, "")
    return _slug(name)


def _doc_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def _page_title(raw_text: str, fallback: str) -> str:
    """First heading-like line of a page (>=3 letters, not a bare number)."""
    for line in raw_text.splitlines()[:6]:
        s = line.strip()
        if s.isdigit():
            continue
        if len(re.sub(r"[^A-Za-z]", "", s)) >= 3:
            return re.sub(r"\s+", " ", s)[:80]
    return fallback


# ── Datasheet stat-block reconstruction ────────────────────────────────────────
# GW stat lines (M T SV W LD OC) are drawn as separate graphical boxes, so every
# extractor flattens them to one value per line. We rebuild them from word
# geometry: find the header row, then bucket the value words below it into columns
# by x-position and rows by y-position.
_STAT_LABELS = ["M", "T", "SV", "W", "LD", "OC"]
_STAT_STOP = ("RANGED", "MELEE", "ABILITIES", "WARGEAR", "DAMAGED", "KEYWORDS", "UNIT")


def _dwords(page) -> list:
    """Words, de-duplicated (GW glyphs are drawn 2-3× as shadows/outlines)."""
    seen = {}
    for w in page.get_text("words"):
        seen.setdefault((round(w[0]), round(w[1]), w[4]), (w[0], w[1], w[2], w[3], w[4]))
    return list(seen.values())


def _cellval(tokens: list) -> str:
    """A stat cell is drawn as overlapping fragments ('4', '4+', '+'); the complete
    value is always the longest single token."""
    return max(tokens, key=len) if tokens else ""


def _stat_block(page) -> str | None:
    """Reconstruct a datasheet's profile stat line(s), or None if the page has none."""
    words = _dwords(page)
    by_y: dict = {}
    for w in words:
        by_y.setdefault(round(w[1] / 3), []).append(w)

    header = header_y = None
    for _, ws in sorted(by_y.items()):
        texts = {w[4] for w in ws}
        if {"M", "T", "OC"} <= texts and "SV" in texts:
            header = sorted([w for w in ws if w[4] in _STAT_LABELS], key=lambda w: w[0])
            header_y = min(w[1] for w in ws)
            break
    if not header or len(header) < 5:
        return None

    cols = [((w[0] + w[2]) / 2, w[4]) for w in header]
    oc_x = max(c[0] for c in cols)
    m_x = cols[0][0]

    stop_y = 1e9
    for w in words:
        if w[1] > header_y and w[4].upper() in _STAT_STOP:
            stop_y = min(stop_y, w[1])

    # Invulnerable save: a '<n>+' token just left of the word INVULNERABLE.
    inv = None
    invw = [w for w in words if w[4].upper() == "INVULNERABLE"]
    if invw:
        iy, ix = invw[0][1], invw[0][0]
        cand = [w for w in words if abs(w[1] - iy) < 7 and "+" in w[4] and w[0] < ix]
        if cand:
            inv = max(cand, key=lambda w: len(w[4]))[4]

    # Value rows: below the header, within the stat columns' x-range.
    vr: dict = {}
    for w in words:
        if header_y + 4 < w[1] < stop_y and (w[0] + w[2]) / 2 <= oc_x + 12:
            vr.setdefault(round(w[1] / 6), []).append(w)
    # Real profile rows have a Movement value; this drops the stray invuln-only row.
    prof = [yb for yb in sorted(vr)
            if any(abs((w[0] + w[2]) / 2 - m_x) < 15 for w in vr[yb])]
    if not prof:
        return None
    centers = [sum(w[1] for w in vr[yb]) / len(vr[yb]) for yb in prof]

    # Profile names (only meaningful when there are ≥2 profiles) sit right of OC;
    # assign each name word to the nearest profile row by y.
    names: dict = {i: [] for i in range(len(prof))}
    if len(prof) >= 2:
        lo, hi = min(centers) - 10, max(centers) + 10
        for w in words:
            cx = (w[0] + w[2]) / 2
            if oc_x + 12 < cx < oc_x + 230 and lo <= w[1] <= hi:
                i = min(range(len(prof)), key=lambda k: (abs(w[1] - centers[k]), k))
                names[i].append(w)

    lines = []
    for i, yb in enumerate(prof):
        nm = " ".join(w[4] for w in sorted(names[i], key=lambda w: (round(w[1] / 6), w[0]))).title()
        cells = [[] for _ in cols]
        for w in sorted(vr[yb], key=lambda w: w[0]):
            cx = (w[0] + w[2]) / 2
            k = min(range(len(cols)), key=lambda j: abs(cols[j][0] - cx))
            cells[k].append(w[4])
        vals = [_cellval(c) for c in cells]
        prefix = f"{nm} — " if nm else ""
        lines.append(prefix + ", ".join(f"{lbl} {v}" for (_, lbl), v in zip(cols, vals) if v))

    out = "**Profile" + ("s" if len(lines) > 1 else "") + " (stats):**\n"
    out += "\n".join(f"- {l}" for l in lines)
    if inv:
        out += f"\n- Invulnerable Save: {inv}"
    return out


def _strip_flat_stats(md: str) -> str:
    """Remove pymupdf4llm's garbled duplicates of the stat block (we prepend a clean
    reconstruction instead): its <!-- picture text --> blocks and the flattened
    'M T SV W LD OC ...' heading + INVULNERABLE SAVE line."""
    out, buf, in_pic = [], [], False
    for ln in md.split("\n"):
        if "<!-- Start of picture text -->" in ln:
            in_pic, buf = True, []
            continue
        if "<!-- End of picture text -->" in ln:
            in_pic = False
            block = "\n".join(buf)
            if not re.search(r"SV.{0,3}W.{0,3}LD.{0,3}OC", block) and "INVULNERABLE" not in block.upper():
                out.append(block)
            buf = []
            continue
        (buf if in_pic else out).append(ln)
    cleaned = [ln for ln in "\n".join(out).split("\n")
               if not re.search(r"M\s+T\s+SV\s+W\s+LD\s+OC", ln)
               and "INVULNERABLE SAVE" not in ln.upper()]
    return "\n".join(cleaned)


def _page_markdown(page, md_body: str) -> str:
    """Clean body markdown; prepend a reconstructed stat block if this is a datasheet."""
    body = _normalize(md_body)
    stat = _stat_block(page)
    if stat:
        body = stat + "\n\n" + _normalize(_strip_flat_stats(md_body))
    return body


def ingest_pdf(pdf: pathlib.Path, game_dir: pathlib.Path, split: str) -> list[dict]:
    """Convert one PDF to Markdown page(s); return manifest entries."""
    doc_slug = _doc_slug(pdf.stem)
    doc_name = _doc_title(doc_slug)
    out_dir = game_dir / doc_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    with fitz.open(pdf) as doc:
        chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=False)
        pages_out = []
        for n, page in enumerate(doc, start=1):
            raw = page.get_text("text")
            if len(raw.strip()) < 20:  # cover art / near-blank page
                continue
            title = _page_title(_normalize(raw), f"{doc_name} p.{n}")
            body = _page_markdown(page, chunks[n - 1]["text"])
            if len(body.strip()) < 10:
                continue
            pages_out.append((n, title, body))

    if split == "doc":
        joined = "\n\n".join(f"## {t}\n\n{b}" for _, t, b in pages_out)
        if not joined.strip():
            return entries
        fname = f"{doc_slug}.md"
        header = f"> Source: {doc_name} ({pdf.name})\n\n# {doc_name}\n\n"
        (out_dir / fname).write_text(header + joined, encoding="utf-8")
        entries.append({"path": doc_slug, "file": f"{doc_slug}/{fname}",
                        "title": doc_name, "url": f"{doc_name} ({pdf.name})"})
        return entries

    for n, title, body in pages_out:
        fname = f"p{n:02d}-{_slug(title, 50)}.md"
        src = f"{doc_name}, p.{n}"
        header = f"> Source: {src} ({pdf.name})\n\n# {title}\n\n"
        (out_dir / fname).write_text(header + body, encoding="utf-8")
        entries.append({"path": f"{doc_slug}/p{n:02d}", "file": f"{doc_slug}/{fname}",
                        "title": title, "url": src})
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
