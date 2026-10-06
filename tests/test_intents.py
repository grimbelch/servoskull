"""The local (pre-LLM) intent matchers in core.intents (run: python -m pytest tests)."""

import pytest

from core import intents
from core.intents import Context


def kind(text, ctx=Context(), matcher=None):
    """Kind of the Intent a matcher returns for text, or None."""
    intent = matcher(text.lower(), ctx)
    return intent.kind if intent else None


# ── maintenance confirmation ──────────────────────────────────────────────────

def test_maintenance_reply_only_while_a_confirmation_is_pending():
    assert intents.maintenance_reply("yes", Context()) is None
    pending = Context(pending_maintenance=True)
    assert intents.maintenance_reply("yes please", pending).args == {"answer": "yes"}
    assert intents.maintenance_reply("no, cancel that", pending).args == {"answer": "no"}
    # "yes... no" is not a yes; anything else is a new request.
    assert intents.maintenance_reply("yes, wait, no", pending).args == {"answer": "no"}
    assert intents.maintenance_reply("roll a d20", pending).args == {"answer": None}


def test_maintenance_command_needs_the_whole_utterance():
    assert intents.maintenance_command("omega 7, reboot yourself please", Context()).args == {"action": "reboot"}
    assert intents.maintenance_command("shut down", Context()).args == {"action": "shutdown"}
    assert intents.maintenance_command("run a system update", Context()).args == {"action": "update"}
    assert intents.maintenance_command("turn off the music", Context()) is None
    assert intents.maintenance_command("restart the song", Context()) is None


# ── briefing ──────────────────────────────────────────────────────────────────

def test_briefing_offer_answers():
    waiting = Context(awaiting_briefing=True)
    assert intents.briefing("yes please", waiting).args == {"answer": "yes"}
    assert intents.briefing("i am not ready", waiting).args == {"answer": "no"}
    assert intents.briefing("what time is it", waiting).args == {"answer": "unclear"}
    assert intents.briefing("give me the morning briefing", Context()).args == {"answer": "yes"}
    assert intents.briefing("what time is it", Context()) is None


# ── screensaver / game / reset ────────────────────────────────────────────────

def test_screensaver_by_name_or_mention():
    ctx = Context(screensavers=("votive_candle", "battlezone"))
    assert intents.screensaver("run the votive_candle screensaver", ctx).args == {"name": "votive_candle"}
    assert intents.screensaver("show me the battlezone visual emulation", ctx).args == {"name": "battlezone"}
    assert intents.screensaver("run the unknown screensaver", ctx) is None
    assert intents.screensaver("what is a screensaver", ctx) is None


def test_bards_tale_start_and_stop():
    assert intents.bards_tale("let's play bard's tale", Context()).args == {"action": "start", "new": False}
    assert intents.bards_tale("start a new game of bards tale", Context()).args == {"action": "start", "new": True}
    assert intents.bards_tale("stop the game", Context(game_running=True)).args == {"action": "stop"}
    assert intents.bards_tale("stop the game", Context(game_running=False)) is None
    assert intents.bards_tale("stop playing that song", Context(game_running=True)) is None


def test_conversation_reset():
    assert kind("please forget this conversation", matcher=intents.conversation_reset) == "conversation_reset"
    assert kind("do you remember our conversation", matcher=intents.conversation_reset) is None


# ── spotify ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, action", [
    ("stop the music", "stop"), ("Omega 7, please stop the music now", "stop"), ("pause", "stop"),
    ("stop playing", "stop"), ("kill the music", "stop"), ("turn off the music", "stop"),
    ("resume", "resume"), ("resume the music", "resume"), ("play music", "resume"), ("continue playing", "resume"),
    ("skip", "skip"), ("next song", "skip"), ("skip this track", "skip"),
])
def test_spotify_control_forms(text, action):
    assert intents.spotify_control(text.lower(), Context()).args == {"action": action}


@pytest.mark.parametrize("text", [
    "please resume the story where you left off",   # a bare "resume" substring used to resume Spotify
    "play music by sabaton",                         # a search for the model, not a resume
    "stop the music and tell me a joke",
    "what's next on the agenda",
    "continue",
])
def test_spotify_control_ignores_sentences_that_merely_contain_a_keyword(text):
    assert intents.spotify_control(text, Context()) is None


def test_spotify_volume_needs_music_named():
    assert intents.spotify_volume("turn up the music", Context()).args == {"change": 15}
    assert intents.spotify_volume("make the music quieter", Context()).args == {"change": -15}
    assert intents.spotify_volume("set the spotify volume to 40", Context()).args == {"level": 40}
    assert intents.spotify_volume("music volume 140", Context()) is None
    # The skull's own volume is the model's set_volume tool, not Spotify.
    assert intents.spotify_volume("volume up", Context()) is None
    assert intents.spotify_volume("set your volume to 70", Context()) is None


# ── dice ──────────────────────────────────────────────────────────────────────

def test_dice_forms():
    assert intents.dice("roll a d20", Context()).args == {"game": "standard", "count": 1, "sides": 20, "target": None}
    assert intents.dice("roll 3d6 needing 4", Context()).args == {"game": "standard", "count": 3, "sides": 6, "target": 4}
    assert intents.dice("roll a firepower die", Context()).args == {"game": "necromunda", "count": 1, "dice_type": "firepower"}
    assert intents.dice("roll 2 hit location dice", Context()).args == {"game": "necromunda", "count": 2, "dice_type": "location"}
    assert intents.dice("how do dice rolls work", Context()) is None


# ── settings ──────────────────────────────────────────────────────────────────

def test_display_rotation():
    assert intents.display_rotation("rotate the display 5 degrees clockwise", Context()).args == {"degrees": 5.0, "absolute": False}
    assert intents.display_rotation("turn the eye 3 degrees to the left", Context()).args == {"degrees": -3.0, "absolute": False}
    assert intents.display_rotation("set the screen rotation to 18", Context()) is None  # no rotate verb
    assert intents.display_rotation("rotate the display to 18 degrees", Context()).args == {"degrees": 18.0, "absolute": True}
    assert intents.display_rotation("rotate the display", Context()) is None


def test_voice_wait():
    assert intents.voice_wait("set the voice wait to 2.5 seconds", Context()).args == {"seconds": 2.5}
    assert intents.voice_wait("what is the silence duration", Context()) is None


@pytest.mark.parametrize("text, name", [
    ("call me lord commander", "lord commander"),
    ("from now on, call me master from now on", "master"),
    ("address me as magos", "magos"),
    ("set my honorific to grand inquisitor", "grand inquisitor"),
    ("change my title to my lord", "my lord"),
])
def test_honorific_forms(text, name):
    assert intents.honorific(text, Context()).args == {"name": name}


@pytest.mark.parametrize("text", [
    "can you call me an uber",          # used to save "an uber" as the honorific
    "call me back later",
    "call me when the print is done",
    "you can call me anytime",
    "what's the title of that book",
])
def test_honorific_ignores_non_titles(text):
    assert intents.honorific(text, Context()) is None


# ── voice / web / cache / tts ─────────────────────────────────────────────────

def test_voice_registration():
    assert intents.voice_registration("register my voice", Context()).args == {"name": None}
    assert intents.voice_registration("re-register my voice as sean", Context()).args == {"name": "sean"}
    assert intents.voice_registration("what does the voice of the emperor sound like", Context()) is None


def test_web_access_code_and_cache_refresh():
    assert kind("show me the web access code", matcher=intents.web_access_code) == "web_access_code"
    assert kind("what's the password for the remote", matcher=intents.web_access_code) == "web_access_code"
    assert kind("clear your voice cache", matcher=intents.voice_cache_refresh) == "voice_cache_refresh"
    assert kind("clear the table", matcher=intents.voice_cache_refresh) is None


def test_tts_switch():
    assert intents.tts_switch("switch to your cloud voice", Context()).args == {"backend": "elevenlabs"}
    assert intents.tts_switch("use the local voice", Context()).args == {"backend": "piper"}
    assert intents.tts_switch("do i have spotify premium", Context()) is None


# ── idle observation ──────────────────────────────────────────────────────────

def test_idle_observation_is_the_whole_request():
    assert kind("give me an observation", matcher=intents.idle_observation) == "idle_observation"
    assert kind("tell me something", matcher=intents.idle_observation) == "idle_observation"
    assert kind("what's happening around you?", matcher=intents.idle_observation) == "idle_observation"
    # These used to be swallowed and answered with a random idle remark.
    assert kind("tell me something about the horus heresy", matcher=intents.idle_observation) is None
    assert kind("what's happening in the news today", matcher=intents.idle_observation) is None
    assert kind("give me a status update on the print", matcher=intents.idle_observation) is None


# ── eye style ─────────────────────────────────────────────────────────────────

_EYES = Context(eye_styles=(
    ("auspex", ("auspex lens", "targeting", "scanner", "reticle", "auspex", "radar")),
    ("noosphere", ("noosphere cog", "data cog", "noosphere", "binharic", "cog iris")),
    ("cog", ("mechanicus cog", "original", "classic", "gear", "cog", "old")),
    ("mood", ("match your mood", "match my mood", "mood matched", "match mood", "mood")),
))


def test_eye_style_by_name():
    assert intents.eye_style("switch your eye to the auspex", _EYES).args == {"action": "set", "name": "auspex"}
    assert intents.eye_style("Omega 7, use the radar eye", _EYES).args == {"action": "set", "name": "auspex"}
    assert intents.eye_style("change your ocular to the noosphere cog", _EYES).args == {"action": "set", "name": "noosphere"}
    assert intents.eye_style("bring back the old eye", _EYES).args == {"action": "set", "name": "cog"}
    assert intents.eye_style("eye style classic", _EYES).args == {"action": "set", "name": "cog"}
    assert intents.eye_style("make your eye match your mood", _EYES).args == {"action": "set", "name": "mood"}
    assert intents.eye_style("switch to mood eyes", _EYES).args == {"action": "set", "name": "mood"}


def test_eye_style_cycle_and_list():
    assert intents.eye_style("next eye", _EYES).args == {"action": "cycle", "step": 1}
    assert intents.eye_style("give me a different eye", _EYES).args == {"action": "cycle", "step": 1}
    assert intents.eye_style("go back to the previous eye style", _EYES).args == {"action": "cycle", "step": -1}
    assert intents.eye_style("what eye styles do you have", _EYES).args == {"action": "list"}


def test_eye_style_leaves_other_eye_talk_alone():
    assert intents.eye_style("keep an eye on the printer", _EYES) is None
    assert intents.eye_style("show me what your eye sees", _EYES) is None
    assert intents.eye_style("rotate your eye 10 degrees", _EYES) is None
    assert intents.eye_style("run the auspex scan", _EYES) is None   # no eye word
    assert intents.eye_style("switch your eye to auspex", Context()) is None  # personality has one eye
    assert intents.eye_style("what is your mood", _EYES) is None
