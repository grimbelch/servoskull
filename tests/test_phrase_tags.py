"""The canned phrases shipped in personalities/omega7/config.json carry audio tags.

They are prerecorded once and cached, so a malformed tag is not a one-off bad
sentence — it is baked into the wake line until someone notices. These checks run
the shipped phrases through the real preprocessing."""

import json
import pathlib
import re

import pytest

from core import tts

CONFIG = pathlib.Path(__file__).parent.parent / "personalities" / "omega7" / "config.json"
PHRASE_LISTS = ("wake_phrases", "cogitation_phrases", "search_phrases", "ack_phrases", "silence_phrases")
SINGLE_PHRASES = ("boot_phrase", "farewell_phrase", "timer_completion_message")

# The delivery vocabulary persona.txt tells the skull to use. Keeping the canned
# phrases inside it means the prerecorded voice and the live replies draw on the
# same palette instead of drifting apart.
VOCABULARY = {
    "whispers", "quietly", "reverent", "solemn", "grimly", "ominously", "sternly",
    "proudly", "curious", "amused", "dryly", "sarcastic", "urgent", "shouts",
    "sighs", "exhales",
}


@pytest.fixture(scope="module")
def phrases() -> list[str]:
    data = json.loads(CONFIG.read_text())
    out = []
    for name in PHRASE_LISTS:
        out.extend(data.get(name, []))
    out.extend(data[name] for name in SINGLE_PHRASES if data.get(name))
    assert len(out) > 200, "personality config lost its phrase lists"
    return out


def test_every_tag_is_in_the_persona_vocabulary(phrases):
    unknown = {
        tag for phrase in phrases
        for tag in re.findall(r"\[([^\]]*)\]", phrase)
        if tag not in VOCABULARY
    }
    assert not unknown, f"tags outside the documented vocabulary: {sorted(unknown)}"


def test_tags_survive_preprocessing_for_a_tag_capable_model(phrases):
    for phrase in phrases:
        kept = tts._preprocess_text(phrase, keep_audio_tags=True)
        assert kept == phrase.strip(), f"preprocessing altered {phrase!r} -> {kept!r}"


def test_tags_are_stripped_cleanly_for_piper(phrases):
    for phrase in phrases:
        plain = tts._preprocess_text(phrase)
        assert "[" not in plain and "]" not in plain, f"bracket survived in {plain!r}"
        # Stripping a leading tag must not leave the line starting on stray
        # punctuation or a space, which Piper would voice as a stumble. (Only the
        # tagged lines are checked: timer_completion_message opens on a bracketed
        # aside of its own and is meant to.)
        if "[" in phrase:
            assert plain and plain[0].isalnum(), f"{phrase!r} strips to {plain!r}"


def test_no_phrase_is_only_a_tag(phrases):
    # has_speech gates synthesis: a tag-only phrase would cache an empty WAV and
    # the skull would answer a wake word with silence.
    for phrase in phrases:
        assert tts.has_speech(phrase), f"{phrase!r} has no speech once tags are stripped"


def test_tagged_phrases_stay_a_minority(phrases):
    # Variance is the point; wall-to-wall direction is not. If a future pass tags
    # everything, this is the line that should make someone think twice.
    tagged = [p for p in phrases if "[" in p]
    assert 20 < len(tagged) < len(phrases) * 0.6, f"{len(tagged)}/{len(phrases)} phrases tagged"
