"""Cut a reply into speakable sentences while it is still streaming in.

The model's text arrives in small deltas; SentenceCutter buffers them and hands
back complete sentences as soon as they end, so each one can be synthesized and
spoken while the rest of the reply is still being written. Pure text logic, no
audio or threads, so it can be unit-tested on its own.
"""

from __future__ import annotations

import re

# A sentence ends at . ! ? or … (optionally followed by a closing quote/bracket)
# and whitespace, or at a line break. Tag-only lines such as "[SPOTIFY: …]" end
# at the newline that follows them.
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+|\n+")
# A period after these is an abbreviation or an initial, not a sentence end.
_ABBREV = re.compile(r"(?:\b(?:mr|mrs|ms|dr|st|vs|e\.g|i\.e|etc|no|vol|approx)|\b[A-Za-z])\.$", re.I)


class SentenceCutter:
    """Feed text deltas in; get finished sentences out.

    Very short sentences ("Yes.") are held and merged with the next so playback
    isn't a string of tiny clips, and text after an unclosed "[" is never cut, so
    a bracketed command spanning several deltas stays whole.
    """

    def __init__(self, min_chars: int = 25):
        self.min_chars = min_chars
        self._buf = ""
        self._pending = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta or ""
        out: list[str] = []
        while True:
            sentence = self._take_sentence()
            if sentence is None:
                break
            merged = f"{self._pending} {sentence}".strip()
            if len(merged) >= self.min_chars:
                out.append(merged)
                self._pending = ""
            else:
                self._pending = merged
        return out

    def flush(self) -> list[str]:
        """Return whatever is left (call once the stream has ended)."""
        rest = f"{self._pending} {self._buf}".strip()
        self._pending = ""
        self._buf = ""
        return [rest] if rest else []

    def _take_sentence(self) -> str | None:
        limit = len(self._buf)
        open_idx = self._buf.rfind("[")
        if open_idx != -1 and self._buf.find("]", open_idx) == -1:
            limit = open_idx  # don't cut inside an unclosed [tag]
        pos = 0
        while True:
            m = _BOUNDARY.search(self._buf, pos, limit)
            if m is None:
                return None
            candidate = self._buf[:m.start()].rstrip()
            if m.group().startswith("\n") or not _ABBREV.search(candidate):
                sentence = self._buf[:m.end()].strip()
                self._buf = self._buf[m.end():]
                return sentence
            pos = m.end()  # "Dr. " – keep looking for the real end
