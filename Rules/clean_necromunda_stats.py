#!/usr/bin/env python3
"""One-off cleanup of mangled stat tables in the Necromunda mirror.

The HTML->Markdown scrape crammed each fighter/vehicle profile into a single
giant empty table: the characteristic header and every value row ended up inside
one cell, interleaved with stray `| --- |` separators and dozens of empty columns.
This rewrites those lines into clean Markdown tables. The data is all present; only
the formatting is fixed.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("Rules/necromunda")
DRY = "--apply" not in sys.argv

_STAT_TOK = re.compile(r'^[0-9DdRr"+/?xX*.()\\\-]+$')
_HEADER_HINTS = ("M WS BS S T W I A Ld", "M Front Side Rear")


def _split_row(cell: str):
    """Split a value cell into (label, stat_tokens). Some reference rows lead with a
    non-stat label like '**Max**'; keep it as a row label."""
    toks = cell.split()
    i = 0
    while i < len(toks) and not _STAT_TOK.match(toks[i]):
        i += 1
    label = " ".join(toks[:i]).replace("*", "").strip()
    return label, toks[i:]


def _is_statrow(cell: str) -> bool:
    _, toks = _split_row(cell)
    return len(toks) >= 6 and all(_STAT_TOK.match(t) for t in toks)


def _clean_statline(line: str) -> str | None:
    """Return a clean multi-row Markdown table for a mangled stat line, or None."""
    cells = [c.strip() for c in line.split("|")]
    meaningful = [c for c in cells if c and (set(c) - set("- "))]
    hdr_i = next((i for i, c in enumerate(meaningful)
                  if c.startswith("M ") and not any(ch.isdigit() for ch in c)), None)
    if hdr_i is None:
        return None
    header = meaningful[hdr_i].split()
    parsed = [_split_row(c) for c in meaningful[hdr_i + 1:] if _is_statrow(c)]
    if not parsed:
        return None
    has_label = any(lbl for lbl, _ in parsed)
    hdr_cells = ([""] + header) if has_label else header
    ncol = max([len(hdr_cells)] + [(1 if has_label else 0) + len(t) for _, t in parsed])

    def fmt(cs):
        return "| " + " | ".join(list(cs) + [""] * (ncol - len(cs))) + " |"

    out = [fmt(hdr_cells), "| " + " | ".join(["---"] * ncol) + " |"]
    out += [fmt(([lbl] if has_label else []) + list(toks)) for lbl, toks in parsed]
    return "\n".join(out)


def main():
    files_changed = lines_changed = 0
    for path in sorted(ROOT.rglob("*.md")):
        src = path.read_text(encoding="utf-8")
        out_lines, changed = [], False
        for line in src.split("\n"):
            if any(h in line for h in _HEADER_HINTS):
                cleaned = _clean_statline(line)
                if cleaned and cleaned != line:
                    # Ensure a blank line precedes the table so it renders as a block.
                    if out_lines and out_lines[-1].strip():
                        out_lines.append("")
                    out_lines.append(cleaned)
                    changed = True
                    lines_changed += 1
                    continue
            out_lines.append(line)
        if changed:
            files_changed += 1
            if not DRY:
                path.write_text("\n".join(out_lines), encoding="utf-8")
    verb = "would fix" if DRY else "fixed"
    print(f"{verb} {lines_changed} stat table(s) across {files_changed} file(s)"
          + ("   [dry run — pass --apply to write]" if DRY else ""))


if __name__ == "__main__":
    main()
