"""Page furniture lifted from the module PDF, so the web app can match it.

The book is a designed object: a cool grey paper texture with a ghosted skull
column down the outer margin, hand-inked rules under the headings, and a torn
paper tab bleeding off the top corner of every page. That tab is a different
colour in every chapter, which is how a reader finds their place by thumb.

All of it lives in the PDF as ordinary embedded images, repeated on every page,
so it can be pulled out once and reused as CSS backgrounds. The chapter tab
colours are sampled rather than eyeballed, which keeps the web app honest if a
different book is ingested later.

Extracted artwork is written alongside the module images -- a gitignored
directory -- because it is copyrighted material that should not enter the
repository.
"""

from __future__ import annotations

import collections
import os
from dataclasses import dataclass

import fitz

__all__ = ["ThemeAssets", "extract_theme"]

# A tab is a tall, narrow strip in the top outer corner. Every chapter has one,
# and the artwork is identical apart from its colour and roman numeral.
_TAB_SIZE = (98, 217)

# The page texture covers the whole trim area.
_MIN_BACKGROUND_PIXELS = 1_000_000


@dataclass
class ThemeAssets:
    """Paths (repo-relative) and colours describing the book's page furniture."""

    background_recto: str = ""
    background_verso: str = ""
    rule: str = ""
    # First page of a chapter -> "#rrggbb", sampled from that chapter's tab.
    accents: dict[int, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.accents is None:
            self.accents = {}


def _save(doc: fitz.Document, xref: int, path: str, *, shrink: int = 0) -> bool:
    """Write an embedded image out, optionally downsampled.

    The page textures are 1953x2481 -- around 3MB as PNG, which is a poor thing
    to put behind every screen of a web app served off a Raspberry Pi. They are
    soft, low-contrast paper grain, so halving them and encoding as JPEG costs
    nothing visible and saves roughly 95% of the bytes.
    """
    try:
        pix = fitz.Pixmap(doc, xref)
    except Exception:
        return False
    if pix.n - pix.alpha > 3:          # CMYK and friends
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if shrink:
        pix.shrink(shrink)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.lower().endswith((".jpg", ".jpeg")):
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)  # JPEG has no alpha channel
        with open(path, "wb") as handle:
            handle.write(pix.tobytes("jpeg", jpg_quality=82))
    else:
        pix.save(path)
    return True


def _dominant(pix: fitz.Pixmap) -> str:
    """The tab's flat colour, sampled away from its torn, feathered edges."""
    counts: collections.Counter = collections.Counter()
    for y in range(60, min(160, pix.height), 4):
        for x in range(25, min(75, pix.width), 3):
            counts[pix.pixel(x, y)] += 1
    if not counts:
        return ""
    red, green, blue = counts.most_common(1)[0][0][:3]
    return f"#{red:02x}{green:02x}{blue:02x}"


def extract_theme(document, image_dir: str) -> ThemeAssets:
    """Pull the shared page furniture out of an open module PDF.

    Accepts a `ModuleDocument` or a raw `fitz.Document`.
    """
    doc = getattr(document, "doc", document)
    usage: dict[int, list[int]] = collections.defaultdict(list)
    for page_index, page in enumerate(doc):
        for xref in {image[0] for image in page.get_images(full=True)}:
            usage[xref].append(page_index + 1)

    theme = ThemeAssets()
    backgrounds: list[tuple[int, int]] = []   # (page count, xref)
    rules: list[tuple[int, int]] = []

    for xref, pages in usage.items():
        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            continue

        if (pix.width, pix.height) == _TAB_SIZE:
            colour = _dominant(
                pix if pix.n - pix.alpha <= 3 else fitz.Pixmap(fitz.csRGB, pix)
            )
            # Front matter carries tabs too; keep them all and let the caller
            # match them to chapters by page.
            if colour:
                theme.accents[min(pages)] = colour
            continue

        if pix.width * pix.height >= _MIN_BACKGROUND_PIXELS and len(pages) > 10:
            backgrounds.append((len(pages), xref))
        elif pix.height <= 45 and pix.width >= 500 and len(pages) > 30:
            rules.append((len(pages), xref))

    # The recto texture appears on roughly twice as many pages as the verso,
    # because the book opens and closes on right-hand pages.
    backgrounds.sort(reverse=True)
    for index, field in ((0, "background_recto"), (1, "background_verso")):
        if index >= len(backgrounds):
            continue
        name = f"theme-page-{'recto' if index == 0 else 'verso'}.jpg"
        path = os.path.join(image_dir, name)
        if _save(doc, backgrounds[index][1], path, shrink=1):
            setattr(theme, field, path)

    rules.sort(reverse=True)
    if rules and _save(doc, rules[0][1], os.path.join(image_dir, "theme-rule.png")):
        theme.rule = os.path.join(image_dir, "theme-rule.png")

    return theme


def accent_for_page(theme: ThemeAssets, page_start: int) -> str:
    """The tab colour in force on a given page.

    Tabs are keyed by the first page they appear on, so the right colour for
    any page is the nearest tab at or before it.
    """
    candidates = [page for page in theme.accents if page <= page_start]
    if not candidates:
        return ""
    return theme.accents[max(candidates)]
