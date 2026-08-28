# Adventure module extraction

Adventure modules are ingested from **Foundry VTT**, not from the source PDFs.

Foundry ships the same books as structured documents: journal pages with real
headings, actors with real characteristic numbers, and `@UUID` links naming
every NPC a scene involves. All of that had to be inferred from glyph positions
when the source was a PDF, and the NPC-to-scene graph could not be recovered at
all.

Extraction is two steps, because they run in different places.

## 1. Export, on the Foundry host

Foundry stores compendium packs as LevelDB directories. Reading them needs the
`classic-level` package, which ships inside Foundry's own `node_modules`, so the
export runs where Foundry is installed:

```bash
node foundry_export.cjs \
  --module /path/to/Data/modules/wfrp4e-rnhd \
  --out rnhd.foundry-export.json
```

The packs are copied to a temporary directory first: LevelDB takes a write lock
even to read, so pointing this at a live install would fail, and a read-only
mount fails for the same reason.

Parents in a pack store only the *ids* of their embedded documents, so actors
arrive separately from their items and journals separately from their pages.
The exporter rejoins them, which is why the output is one self-contained file.

Options:

| Flag | Meaning |
| --- | --- |
| `--module` | Foundry module directory (required) |
| `--out` | Destination JSON (required) |
| `--classic-level` | Override the `classic-level` lookup path |
| `--no-copy` | Read the packs in place; only safe with Foundry stopped |

## 2. Ingest, on the machine holding the database

Copy the JSON and the module directory across, then:

```bash
python -m games.wfrp.extract.foundry_module rnhd.foundry-export.json \
  --module-dir /path/to/wfrp4e-rnhd \
  --slug rough-nights-and-hard-days \
  --title "Rough Nights & Hard Days"
```

This rebuilds every `module_*` table from scratch. Per-campaign state in
`campaign_*` is keyed by module id and is left alone, so re-running mid-campaign
does not disturb a game in progress.

The module directory is needed as well as the JSON because the artwork is
copied out of it into `games/wfrp/rules/modules/<slug>/images/`.

## The core rulebook

The Core Rulebook ships in Foundry too, as the `wfrp4e-core` module, and it is
a far better source than the PDF: 1,500+ actor documents with real
characteristic numbers, careers with parsed skill/talent/trapping lists, and
roll tables with machine-readable ranges and system keys. The same
`foundry_export.cjs` export feeds a dedicated ingester that fills the `rule_*`
tables of `rules_schema.py` — the rules engine cannot tell which extractor
built them:

```bash
node foundry_export.cjs \
  --module /path/to/Data/modules/wfrp4e-core \
  --out wfrp4e-core.foundry-export.json

python -m games.wfrp.extract.rulebook.foundry wfrp4e-core.foundry-export.json \
  --slug wfrp-4e-core
```

Condition rules text is not compendium content — the wfrp4e system renders it
from the module's language file — so the exporter bundles `lang/en.json` into
the export and the ingester reads `WFRP4E.Conditions.*` from there.

Foundry is the only supported source; the old PDF extraction path has been
removed.

## What is not in Foundry

`map_keys.py` holds the numbered callouts printed on the floorplans — "21 Hall",
"24 Dormitory". Foundry's scenes for these modules carry no map notes, and the
KEY panels are painted into the raster artwork, so the callouts exist in no
machine-readable form anywhere. They are transcribed by hand there, and matched
to artwork by filename.

OCR is not an option: the books set numerals as oldstyle figures, so `21` reads
as `2I` and `30` as `3O` — exactly the kind of quietly-wrong digit that sends a
Gamemaster to the wrong room.

## Licensing

The exported JSON and the copied artwork are licensed Cubicle 7 content and are
git-ignored. Only the extractors are tracked; anyone with the module installed
in their own Foundry can reproduce the data.
