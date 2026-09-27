"""Unit tests for core.speech_stream.SentenceCutter (run: python -m pytest tests)."""

from core.speech_stream import SentenceCutter


def _stream(text: str, chunk: int = 3, min_chars: int = 25) -> list[str]:
    """Feed text in small deltas the way a model streams it and collect the output."""
    cutter = SentenceCutter(min_chars=min_chars)
    out: list[str] = []
    for i in range(0, len(text), chunk):
        out.extend(cutter.feed(text[i:i + chunk]))
    out.extend(cutter.flush())
    return out


def test_sentences_come_out_whole_and_in_order():
    text = "The Emperor protects, always. This unit stands ready to serve you! What is thy bidding?"
    assert _stream(text) == [
        "The Emperor protects, always.",
        "This unit stands ready to serve you!",
        "What is thy bidding?",
    ]


def test_sentence_is_emitted_before_the_stream_ends():
    cutter = SentenceCutter(min_chars=5)
    assert cutter.feed("Acknowledged, my Lord. The archives") == ["Acknowledged, my Lord."]
    # A period at the very end of a delta isn't final until a space follows it...
    assert cutter.feed(" are open.") == []
    assert cutter.feed(" The rite") == ["The archives are open."]
    # ...or the stream ends.
    assert cutter.flush() == ["The rite"]


def test_short_sentences_are_merged_with_the_next():
    assert _stream("Yes. It is done. The rite is complete, Master. Your will be done.") == [
        "Yes. It is done. The rite is complete, Master.",
        "Your will be done.",
    ]


def test_flush_returns_a_trailing_fragment_without_punctuation():
    assert _stream("This unit attends", chunk=50) == ["This unit attends"]
    assert _stream("", chunk=50) == []


def test_bracketed_command_spanning_deltas_is_never_cut():
    text = "[SPOTIFY: Sabaton. The Last Stand]\nAs the Omnissiah wills it. The music of war fills the air."
    out = _stream(text, chunk=2)
    assert out[0].startswith("[SPOTIFY: Sabaton. The Last Stand]")
    assert "".join(out).count("[") == 1
    assert out[-1] == "The music of war fills the air."


def test_abbreviations_and_decimals_do_not_end_a_sentence():
    assert _stream("Dr. Mordecai measured 3.5 metres. Then he left.") == [
        "Dr. Mordecai measured 3.5 metres.",
        "Then he left.",
    ]


def test_line_breaks_end_a_sentence():
    assert _stream("First line of the litany\nSecond line follows here\n", min_chars=5) == [
        "First line of the litany",
        "Second line follows here",
    ]
