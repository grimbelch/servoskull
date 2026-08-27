"""Extract illustrations, maps and portraits from the module PDF.

The book's images are not usable as raw embedded streams: a single printed
illustration is often several overlapping XObjects stacked on a full-page
parchment background, and the decorative page furniture is repeated on every
spread. So each image is instead *re-rendered* from its printed rectangle, which
yields exactly what a reader sees.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional

from .layout import ModuleDocument
from .sections import Section, slugify

# Page furniture: header and footer ornaments are only a few points tall.
MIN_HEIGHT = 24.0
MIN_WIDTH = 60.0
# A rectangle covering most of the page is the parchment background.
BACKGROUND_COVERAGE = 0.92
RENDER_DPI = 150


@dataclass
class Asset:
    """One rendered illustration."""

    page: int
    kind: str
    slug: str
    path: str
    caption: str = ""
    width: int = 0
    height: int = 0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    section_slug: str = ""
    chapter_slug: str = ""
    sha256: str = ""


def _iou(a: tuple, b: tuple) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - overlap
    return overlap / union if union else 0.0


def _merge_boxes(boxes: list[tuple], threshold: float = 0.6) -> list[tuple]:
    """Collapse the stacked XObjects of one illustration into a single box."""
    merged: list[tuple] = []
    for box in sorted(boxes, key=lambda b: -((b[2] - b[0]) * (b[3] - b[1]))):
        for index, kept in enumerate(merged):
            if _iou(box, kept) >= threshold:
                merged[index] = (
                    min(box[0], kept[0]),
                    min(box[1], kept[1]),
                    max(box[2], kept[2]),
                    max(box[3], kept[3]),
                )
                break
        else:
            merged.append(box)
    return merged


def image_boxes(doc: ModuleDocument, page_number: int) -> list[tuple]:
    """Printed rectangles of the real illustrations on a page."""
    page = doc.doc[page_number - 1]
    page_area = page.rect.width * page.rect.height
    boxes = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 1:
            continue
        bbox = tuple(block["bbox"])
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            continue
        if (width * height) / page_area >= BACKGROUND_COVERAGE:
            continue
        boxes.append(bbox)
    return _merge_boxes(boxes)


def _classify(
    page_number: int, bbox: tuple, doc: ModuleDocument, map_pages: dict[int, Section]
) -> str:
    if page_number == 1:
        return "cover"
    if page_number in map_pages:
        return "map"
    page = doc.doc[page_number - 1]
    coverage = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / (
        page.rect.width * page.rect.height
    )
    if coverage >= 0.5:
        return "art"
    if (bbox[3] - bbox[1]) > (bbox[2] - bbox[0]):
        return "portrait"
    return "art"


def extract_assets(
    doc: ModuleDocument, roots: list[Section], out_dir: str
) -> list[Asset]:
    """Render every illustration to disk and describe it.

    Identical renders are de-duplicated by content hash, which removes the
    repeated decorative plates that appear across multiple chapters.
    """
    os.makedirs(out_dir, exist_ok=True)
    sections = [node for root in roots for node in root.walk()]
    map_pages = {s.page: s for s in sections if s.kind == "map"}

    # The innermost section covering a page, used to caption and place an image.
    page_section: dict[int, Section] = {}
    for section in sorted(sections, key=lambda s: (s.page_start or s.page, s.level)):
        for page in range(section.page_start or section.page, (section.page_end or section.page) + 1):
            page_section[page] = section

    assets: list[Asset] = []
    seen: dict[str, str] = {}

    for page_number in range(1, doc.page_count + 1):
        for ordinal, bbox in enumerate(image_boxes(doc, page_number)):
            kind = _classify(page_number, bbox, doc, map_pages)
            section = map_pages.get(page_number) or page_section.get(page_number)
            chapter = section.ancestor_of_kind("chapter") if section else None
            if section and section.kind == "chapter":
                chapter = section

            pixmap = doc.doc[page_number - 1].get_pixmap(
                clip=bbox, dpi=RENDER_DPI, alpha=False
            )
            data = pixmap.tobytes("png")
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue

            caption = section.title if kind == "map" and section else ""
            base = slugify(f"p{page_number:03d}-{ordinal + 1}-{caption or kind}")
            filename = f"{base}.png"
            path = os.path.join(out_dir, filename)
            with open(path, "wb") as handle:
                handle.write(data)
            seen[digest] = path

            assets.append(
                Asset(
                    page=page_number,
                    kind=kind,
                    slug=base,
                    path=path,
                    caption=caption,
                    width=pixmap.width,
                    height=pixmap.height,
                    bbox=bbox,
                    section_slug=section.slug if section else "",
                    chapter_slug=chapter.slug if chapter else "",
                    sha256=digest,
                )
            )
    return assets
