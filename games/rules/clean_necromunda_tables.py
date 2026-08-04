#!/usr/bin/env python3
"""Clean up mangled tables in the Necromunda mirror.

The HTML->Markdown scrape turned every table (stat blocks, equipment lists, trading
post tables, dice-roll tables, …) into one giant empty grid: the header and all row
content were crammed into single cells, interleaved with stray `| --- |` separators
and dozens of empty columns. The data is all present; only the layout is broken.

This rewrites those lines into clean Markdown tables. It recognises the common,
well-structured types and reconstructs their columns; anything else falls back to a
readable one-row-per-line table (garbage stripped) rather than being left mangled.

Idempotent-ish: run it on a pristine (freshly scraped) mirror. Usage:
    python Rules/clean_necromunda_tables.py Rules/necromunda --apply
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("Rules/necromunda")
DRY = "--apply" not in sys.argv

_STAT_TOK = re.compile(r'^[0-9DdRr"+/?xX*.()\\\-]+$')     # a stat / value token
_VALUE_TOK = re.compile(r'^[+\-]?\d+\*?$|^-$|^\?$')        # a credits value: 15, +5, -, ?


def _meaningful(line: str):
    cells = [c.strip() for c in line.split("|")]
    return cells, [c for c in cells if c and (set(c) - set("- "))]


def _is_mangled(line: str) -> bool:
    """A scraped table row: many pipe cells, most of them empty/separators."""
    if line.count("|") < 15:
        return False
    cells, meaningful = _meaningful(line)
    return 2 <= len(meaningful) < len(cells) * 0.5


def _row(cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table(header_cells, body_rows) -> str:
    n = max([len(header_cells)] + [len(r) for r in body_rows])
    pad = lambda cs: list(cs) + [""] * (n - len(cs))
    out = [_row(pad(header_cells)), _row(["---"] * n)]
    out += [_row(pad(r)) for r in body_rows]
    return "\n".join(out)


# ── Type-specific reconstructors ───────────────────────────────────────────────

def _split_labelled(cell: str):
    """(label, stat_tokens): a reference row may lead with a non-stat label like Max."""
    toks = cell.split()
    i = 0
    while i < len(toks) and not _STAT_TOK.match(toks[i]):
        i += 1
    return " ".join(toks[:i]).replace("*", "").strip(), toks[i:]


def _build_stat(header, rows):
    hdr = header.split()
    parsed = []
    for c in rows:
        lbl, toks = _split_labelled(c)
        if len(toks) >= 6 and all(_STAT_TOK.match(t) for t in toks):
            parsed.append((lbl, toks))
    if not parsed:
        return None
    has_label = any(l for l, _ in parsed)
    hdr_cells = ([""] + hdr) if has_label else hdr
    body = [([l] if has_label else []) + t for l, t in parsed]
    return _table(hdr_cells, body)


def _build_name_value(header, rows):
    """Item/Option/Upgrade + Credits: name = all but trailing value; bold/no-value
    lines are category rows spanning the name column."""
    hdr = header.split()  # e.g. ["Item", "Credits"]
    body = []
    for c in rows:
        toks = c.split()
        if toks and _VALUE_TOK.match(toks[-1]) and len(toks) >= 2:
            body.append([" ".join(toks[:-1]), toks[-1]])
        else:                       # category header / no price
            body.append([c, ""])
    return _table(hdr, body)


def _build_trading(header, rows):
    """Item | <n> credits | Rarity(/Legality)."""
    hdr = header.split(None, 2) if len(header.split()) >= 3 else header.split()
    body = []
    for c in rows:
        toks = c.split()
        low = [t.lower() for t in toks]
        if "credits" in low:
            i = low.index("credits")
            item = " ".join(toks[:i - 1]) if i >= 1 else ""
            price = " ".join(toks[i - 1:i + 1])
            rarity = " ".join(toks[i + 1:])
            body.append([item, price, rarity])
        else:
            body.append([c, "", ""])
    return _table(hdr, body)


def _build_roll(header, rows):
    """Dice tables: first token is the roll, the rest is the result."""
    hdr = header.split(None, 1)
    body = []
    for c in rows:
        toks = c.split(None, 1)
        body.append(toks if len(toks) == 2 else [c, ""])
    return _table(hdr, body)


def _build_generic(header, rows):
    """Unknown layout: strip the garbage, one real cell per row (single column)."""
    return _table([header], [[r] for r in rows])


def _clean(line: str):
    _, meaningful = _meaningful(line)
    if len(meaningful) < 2:
        return None
    header, rows = meaningful[0], meaningful[1:]
    h = header.strip()
    toks = h.split()
    hl = h.lower()

    if h.startswith("M ") and not any(ch.isdigit() for ch in h) and ("WS BS" in h or "Front Side" in h):
        return _build_stat(header, rows)
    if len(toks) == 2 and toks[1].lower() in ("credits", "cost"):
        return _build_name_value(header, rows)
    if hl in ("item price rarity", "item price legality/rarity"):
        return _build_trading(header, rows)
    if toks and toks[-1].lower() in ("result", "effect") and re.match(r'^\d?d\d', toks[0].lower()):
        return _build_roll(header, rows)
    return _build_generic(header, rows)


def main():
    files_changed = tables = 0
    for path in sorted(ROOT.rglob("*.md")):
        out, changed = [], False
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.count("|") >= 15:
                meaningful = _meaningful(line)[1]
                if len(meaningful) >= 2:                 # mangled multi-row table
                    cleaned = _clean(line)
                    if cleaned:
                        if out and out[-1].strip():
                            out.append("")
                        out.append(cleaned)
                        changed = True
                        tables += 1
                        continue
                elif len(meaningful) == 1:               # one real cell in an empty grid
                    out.append(meaningful[0])            # unwrap to plain text
                    changed = True
                    continue
                else:                                    # pure empty/separator scaffold
                    changed = True
                    continue
            out.append(line)
        if changed:
            files_changed += 1
            if not DRY:
                path.write_text("\n".join(out), encoding="utf-8")
    verb = "would clean" if DRY else "cleaned"
    print(f"{verb} {tables} table(s) across {files_changed} file(s)"
          + ("   [dry run — pass --apply]" if DRY else ""))


if __name__ == "__main__":
    main()
