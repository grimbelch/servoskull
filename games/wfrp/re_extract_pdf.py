#!/usr/bin/env python3
"""Re-extract Rough Nights & Hard Days PDF into clean per-page Markdown.

Improvements over the original extraction:
  - Uses PDF TOC for accurate page titles and section breadcrumbs
  - Intelligent bold fragment merger that preserves word boundaries
  - Cleans WFRP-specific running headers/footers
  - Proper page titles from TOC rather than guessing from first line
  - Skips near-blank pages (cover art, full-page illustrations)
  - Outputs clean filenames based on TOC-derived slugs
"""
import json
import pathlib
import re
import sys

try:
    import fitz
    import pymupdf4llm
except ImportError:
    sys.exit("Required: pip install pymupdf4llm pymupdf")

# ── Paths ──────────────────────────────────────────────────────────────────────
PDF_PATH = pathlib.Path(__file__).resolve().parent / "rules" / "modules" / "[WFRP][4E] - Rough Nights and Hard Days.pdf"
OUT_DIR = pathlib.Path(__file__).resolve().parent / "rules" / "wfrp-4e-rough-nights-and-hard-days"
PDF_FILENAME = "[WFRP][4E] - Rough Nights and Hard Days.pdf"

# ── Chapter page ranges (0-indexed) for section assignment ─────────────────────
CHAPTER_RANGES = [
    (0, 6, "Front Matter"),
    (7, 22, "A Rough Night at the Three Feathers"),
    (23, 36, "A Day at the Trials"),
    (37, 54, "A Night at the Opera"),
    (55, 68, "Nastassia's Wedding"),
    (69, 86, "Lord of Ubersreik"),
    (87, 91, "Appendix 1: Gnomes"),
    (92, 96, "Appendix 2: Pub Games"),
]

# ── Unicode normalization ──────────────────────────────────────────────────────
_NORMALIZE_MAP = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u00ad": "-",  # soft hyphen -> regular hyphen
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u00a0": " ", "\u2022": "-", "\u25aa": "-", "\u25a0": "-",
    "\u25e6": "-", "\ufb01": "fi", "\ufb02": "fl",
}

# Running headers/footers to strip (case-insensitive patterns)
_HEADER_FOOTER_PATTERNS = [
    r"^(?:WARHAMMER FANTASY ROLEPL?\s*AY)$",
    r"^(?:WFRP CORE RULEBOOK)$",
    r"^(?:A ROUGH NIGHT AT THE THREE FEATHERS\s*(?:III)?)$",
    r"^(?:A DAY AT THE TRIALS\s*(?:IV)?)$",
    r"^(?:A NIGHT AT THE OPERA\s*(?:V)?)$",
    r"^(?:NASTASSIA.S WEDDING\s*(?:VI)?)$",
    r"^(?:LORD OF UBERSREIK\s*(?:VII)?)$",
    r"^(?:APPENDIX \d:?\s*.*)$",
    r"^(?:ROUGH NIGHTS .{0,3} HARD DAYS)$",
    r"^\d{1,3}$",  # bare page numbers
]
_HEADER_RE = re.compile("|".join(_HEADER_FOOTER_PATTERNS), re.IGNORECASE)
_DECO_RE = re.compile(r"^[.\*\s\-_]{2,}$")
_ROMAN_RE = re.compile(r"^(?:III|IV|V|VI|VII|VIII)$")


def _normalize_unicode(text: str) -> str:
    """Replace smart quotes, dashes, ligatures, soft hyphens with ASCII equivalents."""
    for bad, good in _NORMALIZE_MAP.items():
        text = text.replace(bad, good)
    text = text.replace("\ufffd", "").replace("\x00", "")
    return text


def _fix_bold_kerning(text: str) -> str:
    """Fix fragmented bold spans by intelligently merging adjacent **X** **Y** sequences.

    The PDF renderer splits words at character boundaries, producing:
      **F** **ollowing** **the** **C** **ampaign**
    This should become:
      **Following the Campaign**

    Strategy: find contiguous runs of adjacent bold spans, extract their fragments,
    and merge them intelligently — joining kerning splits (single uppercase char +
    lowercase continuation) without space, but preserving word boundaries.
    """
    # Match contiguous sequences of 2+ adjacent bold spans
    pattern = r'(\*\*[^\*\n]+\*\*(?:\s*\*\*[^\*\n]+\*\*)+)'

    def _merge_bold_sequence(match):
        seq = match.group(0)
        frags = re.findall(r'\*\*([^\*\n]+)\*\*', seq)
        if not frags:
            return seq

        result_parts = [frags[0].strip()]

        for frag in frags[1:]:
            frag = frag.strip()
            if not frag:
                continue
            prev = result_parts[-1]
            if not prev:
                result_parts[-1] = frag
                continue

            frag_start = frag[0]

            # Rule 1: Fragment starts with '-' → attach directly (hyphenated word)
            #   "Stand" + "-Alone" → "Stand-Alone"
            if frag_start == '-':
                result_parts[-1] = prev + frag
                continue

            # Rule 2: Previous ends with '-' → attach directly
            if prev[-1] == '-':
                result_parts[-1] = prev + frag
                continue

            # Rule 3: Fragment starts with lowercase → check if it's continuing a word
            #   The last "token" in prev (split by spaces or hyphens) tells us:
            #   - If it's a single uppercase letter, this is kerning: "C" + "ampaign" → "Campaign"
            #   - Otherwise it's a new word: "Following" + "the" → "Following the"
            if frag_start.islower():
                last_token = re.split(r'[\s\-]', prev)[-1]
                if len(last_token) == 1 and last_token.isupper():
                    # Kerning split: merge without space
                    result_parts[-1] = prev + frag
                else:
                    # Separate word: merge with space
                    result_parts[-1] = prev + " " + frag
                continue

            # Rule 4: Everything else (uppercase start, numbers, etc.) → add space
            result_parts[-1] = prev + " " + frag

        return "**" + result_parts[0] + "**"

    text = re.sub(pattern, _merge_bold_sequence, text)

    # Clean excessive asterisks (****X**** → **X**)
    text = re.sub(r'\*{3,}', '**', text)

    return text


def _fix_italic_kerning(text: str) -> str:
    """Fix fragmented italic spans: *X* *Y* → *X Y* (less common than bold)."""
    # Only merge single-char italic + lowercase continuation
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'\*([A-Z])\*\s+\*([a-z][^\*\n]*)\*', r'*\1\2*', text)
    return text


def _clean_page_text(raw_md: str) -> str:
    """Full cleaning pipeline for a page's markdown text."""
    text = _normalize_unicode(raw_md)

    # Line-by-line filter for headers, footers, decorative lines
    lines = text.split("\n")
    filtered = []
    for line in lines:
        s = line.strip()
        if _HEADER_RE.match(s):
            continue
        if _DECO_RE.match(s):
            continue
        if _ROMAN_RE.match(s):
            continue
        # Skip lines that are just "##### CHAPTER TITLE III" repeated headers
        if s.startswith("#####") and any(ch in s for ch in [
            "THREE FEATHERS", "DAY AT THE TRIALS", "NIGHT AT THE OPERA",
            "WEDDING", "UBERSREIK",
        ]):
            continue
        filtered.append(line)
    text = "\n".join(filtered)

    # Fix kerning in bold/italic spans
    text = _fix_bold_kerning(text)
    text = _fix_italic_kerning(text)

    # Fix space after punctuation before word (e.g. "11:Consumers" → "11: Consumers")
    text = re.sub(r"(\d+[:\)])([A-Za-z])", r"\1 \2", text)

    # Strip stray dot tokens like **..**
    text = re.sub(r"\s*\*\*\.[\.\s]*\*\*\s*", " ", text)
    text = re.sub(r"\.{4,}", " ... ", text)

    # Clean whitespace
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _build_toc_map(doc) -> dict:
    """Build page_num (1-indexed) → section breadcrumb string from PDF TOC."""
    toc = doc.get_toc()
    if not toc:
        return {}

    page_map = {}
    total_pages = len(doc)

    for page_num in range(1, total_pages + 1):
        active = []
        for item in toc:
            lvl, title, start_page = item
            if start_page <= page_num:
                active = active[:lvl - 1]
                active.append(title.strip())
        if active:
            page_map[page_num] = " > ".join(active)

    return page_map


def _toc_page_title(toc, page_num: int) -> str:
    """Get the most specific TOC title for a given page number."""
    # Find all TOC entries that start on this exact page
    exact = [entry for entry in toc if entry[2] == page_num]
    if exact:
        best = max(exact, key=lambda e: e[0])
        return best[1].strip()

    # Otherwise find the most recent entry before this page
    candidates = [entry for entry in toc if entry[2] <= page_num]
    if candidates:
        best = max(candidates, key=lambda e: (e[2], e[0]))
        return best[1].strip()

    return None


def _slug(s: str, maxlen: int = 60) -> str:
    """Create a URL-safe slug from a string."""
    s = _normalize_unicode(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen].strip("-") or "untitled"


def _get_chapter_name(page_num_0indexed: int) -> str:
    """Get chapter name for a 0-indexed page number."""
    for start, end, name in CHAPTER_RANGES:
        if start <= page_num_0indexed <= end:
            return name
    return "Unknown"


def extract_all():
    """Main extraction: PDF → per-page Markdown files + manifest."""
    if not PDF_PATH.exists():
        sys.exit(f"PDF not found: {PDF_PATH}")

    # Clean output directory
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old_f in OUT_DIR.glob("*.md"):
        old_f.unlink()

    doc = fitz.open(str(PDF_PATH))
    toc = doc.get_toc()
    toc_map = _build_toc_map(doc)

    print(f"Extracting {len(doc)} pages from: {PDF_PATH.name}")
    print(f"TOC entries: {len(toc)}")
    print(f"Output: {OUT_DIR}")

    # Extract markdown for all pages at once
    print("Running pymupdf4llm extraction (this may take a minute)...")
    chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, show_progress=True)
    print(f"Got {len(chunks)} page chunks")

    manifest = []
    pages_written = 0
    pages_skipped = 0

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]
        raw_text = page.get_text("text")

        # Skip near-blank pages (cover art, full-page illustrations)
        if len(raw_text.strip()) < 30:
            pages_skipped += 1
            continue

        # Get the markdown body from pymupdf4llm
        md_body = chunks[page_idx]["text"] if page_idx < len(chunks) else ""
        if len(md_body.strip()) < 15:
            pages_skipped += 1
            continue

        # Clean the markdown
        body = _clean_page_text(md_body)
        if len(body.strip()) < 10:
            pages_skipped += 1
            continue

        # Determine title from TOC
        toc_title = _toc_page_title(toc, page_num)
        if not toc_title:
            for line in body.splitlines()[:6]:
                s = line.strip().strip("#").strip()
                if len(re.sub(r"[^A-Za-z]", "", s)) >= 3:
                    toc_title = s[:80]
                    break
            if not toc_title:
                toc_title = f"Page {page_num}"

        # Clean up title
        toc_title = toc_title.strip()
        if "Fill ME" in toc_title:
            toc_title = _toc_page_title(toc, page_num - 1) or f"Page {page_num}"

        # Section breadcrumb
        sec_path = toc_map.get(page_num, "")
        chapter_name = _get_chapter_name(page_idx)

        # Build header
        header = f"> Source: Rough Nights & Hard Days, p.{page_num} ({PDF_FILENAME})\n"
        if sec_path:
            header += f"> Section: {sec_path}\n"
        header += f"\n# {toc_title}\n\n"

        # Generate filename
        title_slug = _slug(toc_title, 50)
        fname = f"p{page_num:02d}-{title_slug}.md"

        # Write the file
        (OUT_DIR / fname).write_text(header + body, encoding="utf-8")

        manifest.append({
            "path": f"wfrp-4e-rough-nights-and-hard-days/p{page_num:02d}",
            "file": f"wfrp-4e-rough-nights-and-hard-days/{fname}",
            "title": toc_title,
            "url": f"Rough Nights & Hard Days, p.{page_num}",
            "page": page_num,
            "chapter": chapter_name,
            "section": sec_path,
        })
        pages_written += 1

    doc.close()

    # Write manifest
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"\nDone!")
    print(f"  Pages written: {pages_written}")
    print(f"  Pages skipped: {pages_skipped}")
    print(f"  Manifest: {manifest_path}")

    # Also update the game-level manifest
    game_manifest_path = OUT_DIR.parent / "manifest.json"
    if game_manifest_path.exists():
        try:
            existing = json.loads(game_manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
        existing = [e for e in existing
                    if not e.get("path", "").startswith("wfrp-4e-rough-nights-and-hard-days")]
        existing.extend(manifest)
        game_manifest_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"  Updated game manifest: {game_manifest_path} ({len(existing)} total entries)")


if __name__ == "__main__":
    extract_all()
