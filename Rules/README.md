# Rules — offline game reference library

Downloaded rulebooks the skull consults **locally** instead of fetching them over
the web at question time. Lookups work offline, return instantly, and don't depend
on a third-party site staying up.

## Layout

One subfolder per game. Each page is a single Markdown file (mirroring the source
site's URL tree for web scrapes, or one file per PDF page for ingested PDFs), with
a `> Source:` line at the top for attribution, plus a `manifest.json` listing every
page (`path`, `url`, `title`, `file`).

```
Rules/
  ingest_pdf.py       # reusable PDF -> Markdown ingester (tracked in git)
  necromunda/         # NecroRAW mirror (necroraw.com.ru) — 527 pages
    manifest.json
    general-principles/conditions.md
    gang-fighters-and-their-weaponry/weapon-traits.md
    ...
  warhammer40k/       # 11th-ed core rules + faction packs + event companions (PDF)
    manifest.json
    world-eaters/p02-brazen-engines.md
    space-marines/...
    ...
```

## How the skull uses it

`skull/search.py` loads a game's folder once and ranks pages by relevance (title
match + full-text scoring, with optional per-game concept routing) via the shared
`_search_rules_library()` engine. Each game gets a thin lookup function + Claude
tool: `necromunda_rules(query)` (falls back to live fetch if its mirror is missing)
and `warhammer40k_rules(query)` (offline only — sourced from PDFs).

The folder is chosen by `RULES_DIR` (see `.env.example`); it defaults to `Rules/`
next to the code.

## Adding another game

### From a website
Mirror it to `Rules/<game>/` as one Markdown file per page + a `manifest.json`
(see the Necromunda scraper notes in git history).

### From PDFs — use the ingester
`ingest_pdf.py` converts PDFs into the layout above. It needs `pymupdf4llm`, a
**dev-time only** dependency (run this on a computer, not the Pi):

```
pip install pymupdf4llm
# every PDF in a folder -> Rules/warhammer40k/
python Rules/ingest_pdf.py warhammer40k "/path/to/40k Rules"
# or specific files; --split doc makes one file per PDF (better for prose books)
python Rules/ingest_pdf.py mygame book.pdf --split doc
```

Each PDF becomes a subfolder (named from its filename); by default each page
becomes one Markdown file titled from its first heading — which suits GW's
lay-out-per-page packs (each page is a detachment / datasheet / section) and makes
them rank well. Body text/tables/columns come from pymupdf4llm (proper Markdown
tables, multi-column aware). Image-only pages (no text layer) are skipped; scanned
PDFs would need OCR (e.g. `ocrmypdf`) first.

**Datasheet stat blocks** (M/T/SV/W/LD/OC) are drawn as graphical boxes that no
text extractor reads correctly — they flatten to an ambiguous one-value-per-line
jumble (which once made the skull misread a unit's Movement). `ingest_pdf.py`
reconstructs them from word geometry and prepends a clean labelled profile list,
then strips the garbled duplicates. This is the fiddliest part; if a future game's
stat layout differs, that's the code to revisit (`_stat_block`).

### Then wire it up
Add a lookup function + Claude tool for the game, following the `warhammer40k_rules`
pattern in `skull/search.py` and `skull/brain.py` (call `_search_rules_library()`
with the game's folder; add a matching entry to `TOOLS` and the dispatch).

> **Note:** These files are third-party copyrighted rules text kept for personal
> local reference on this device only. They are git-ignored — do not redistribute
> or commit them to a public repository.
