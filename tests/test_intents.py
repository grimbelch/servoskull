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
    assert intents.dice("roll 3 injury dice", Context()).args == {"game": "necromunda", "count": 3, "dice_type": "injury"}
    assert intents.dice("roll 2 scatter dice", Context()).args == {"game": "necromunda", "count": 2, "dice_type": "scatter"}
    assert intents.dice("how do dice rolls work", Context()) is None


def test_d66_is_not_a_sixty_six_sided_die():
    """D66 is two D6 read as tens then units, so it must not fall through to dN.

    Matched by the generic pattern it would roll 1-66 uniformly and produce
    results the game cannot show, such as 17 or 20.
    """
    assert intents.dice("roll a d66", Context()).args == {
        "game": "necromunda", "count": 1, "dice_type": "d66"}
    assert intents.dice("roll 2 d66", Context()).args == {
        "game": "necromunda", "count": 2, "dice_type": "d66"}
    # A plain d6 must still reach the standard roller.
    assert intents.dice("roll a d6", Context()).args["game"] == "standard"


def test_hit_location_dice_are_not_offered():
    """The 2026 edition has no hit location roll; the phrase must not match.

    It belonged to the previous edition. Matching it would send a request for a
    roll that does not exist to a simulator that would invent a result.
    """
    assert intents.dice("roll 2 hit location dice", Context()) is None


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


# -- response length ----------------------------------------------------------

@pytest.mark.parametrize("text,mode", [
    ("short answers", "SHORT"),
    ("omega 7 short answers please", "SHORT"),
    ("give me shorter answers", "SHORT"),
    ("be brief", "SHORT"),
    ("keep it short", "SHORT"),
    ("be more concise", "SHORT"),
    ("answer concisely", "SHORT"),
    ("terse mode", "SHORT"),
    ("long answers", "LONG"),
    ("long answers from now on", "LONG"),
    ("speak freely", "LONG"),
    ("be verbose", "LONG"),
    ("give me detailed answers", "LONG"),
    ("don't hold back", "LONG"),
    ("normal answers", "NORMAL"),
    ("back to normal answers", "NORMAL"),
    ("default response length", "NORMAL"),
    ("answer normally", "NORMAL"),
    ("standard mode", "NORMAL"),
])
def test_response_length_forms(text, mode):
    assert intents.response_length(text, Context()).args == {"mode": mode}


@pytest.mark.parametrize("text", [
    "take a short rest",                            # WFRP rules term
    "tell me a long story",
    "how long until the print is done",
    "give me a brief history of the horus heresy",   # 'brief' as an adjective, not a directive
    "what is the full name of the primarch",
    "the detailed rules for overwatch",
    "is that the standard pattern bolter",
    "that was a quick game",
    "roll a d6",
    "set volume to 50",
])
def test_response_length_ignores_unrelated(text):
    assert intents.response_length(text, Context()) is None


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
    ("shuffle", ("match your mood", "surprise me", "randomize", "shuffle", "random", "mood")),
))


def test_eye_style_by_name():
    assert intents.eye_style("switch your eye to the auspex", _EYES).args == {"action": "set", "name": "auspex"}
    assert intents.eye_style("Omega 7, use the radar eye", _EYES).args == {"action": "set", "name": "auspex"}
    assert intents.eye_style("change your ocular to the noosphere cog", _EYES).args == {"action": "set", "name": "noosphere"}
    assert intents.eye_style("bring back the old eye", _EYES).args == {"action": "set", "name": "cog"}
    assert intents.eye_style("eye style classic", _EYES).args == {"action": "set", "name": "cog"}
    assert intents.eye_style("make your eye match your mood", _EYES).args == {"action": "set", "name": "shuffle"}
    assert intents.eye_style("shuffle your eyes", _EYES).args == {"action": "set", "name": "shuffle"}
    assert intents.eye_style("use a random eye", _EYES).args == {"action": "set", "name": "shuffle"}


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


# ── wake-word sensitivity ─────────────────────────────────────────────────────

def _wake(text):
    return intents.wake_sensitivity(text.lower(), Context())


def test_the_request_that_the_model_only_ever_narrated():
    # Spoken on Oct 5 and again on Oct 8; the tool never fired either time.
    assert _wake("increase your wake word sensitivity.").args == {"direction": "more"}
    assert _wake("decrease your wake word sensitivity.").args == {"direction": "less"}


def test_sensitivity_and_threshold_point_opposite_ways():
    # Raising the sensitivity lowers the number; raising the threshold raises it.
    assert _wake("make your wake word more sensitive").args == {"direction": "more"}
    assert _wake("raise your wake word threshold").args == {"direction": "less"}
    assert _wake("lower your wake word threshold").args == {"direction": "more"}


def test_an_explicit_threshold_is_taken_as_given():
    assert _wake("set the wake word threshold to 0.5").args == {"threshold": 0.5}
    assert _wake("set wake word sensitivity to .45").args == {"threshold": 0.45}
    # A bare number is a percentage, not a threshold of fifty.
    assert _wake("set wake word threshold to 50 percent").args == {"threshold": 0.5}


def test_a_named_level_is_recognised():
    assert _wake("set wake word sensitivity to high").args == {"level": "high"}
    assert _wake("put the wake word threshold back to default").args == {"level": "default"}


def test_a_question_reports_rather_than_changes():
    assert _wake("what is your wake word sensitivity").args == {}


def test_it_keeps_out_of_other_commands():
    assert _wake("increase the volume") is None
    assert _wake("set your microphone sensitivity to high") is None   # a different setting
    assert _wake("wake me up at seven") is None
    assert _wake("roll a d6") is None


# ── settings the model used to narrate ────────────────────────────────────────

def _m(matcher, text):
    return matcher(text.lower(), Context())


def test_microphone_sensitivity_is_separate_from_the_wake_threshold():
    assert _m(intents.mic_sensitivity, "increase your microphone sensitivity").args == {"direction": "more"}
    assert _m(intents.mic_sensitivity, "set the silence threshold to 250").args == {"threshold": 250}
    assert _m(intents.mic_sensitivity, "make your hearing less sensitive").args == {"direction": "less"}
    # The wake matcher owns anything naming the wake word; these must not collide.
    assert _m(intents.mic_sensitivity, "increase your wake word sensitivity") is None
    assert _m(intents.wake_sensitivity, "increase your microphone sensitivity") is None


def test_the_skulls_own_volume():
    assert _m(intents.volume, "set volume to 50%").args == {"level": "50"}
    assert _m(intents.volume, "set your volume to 30").args == {"level": "30"}
    # The form that was silently narrated on Oct 4, buried mid-sentence.
    assert _m(intents.volume, "I am, but also reduce your volume by 30%").args == {"level": "-30"}
    assert _m(intents.volume, "turn your volume up").args == {"level": "+15"}
    assert _m(intents.volume, "speak louder").args == {"level": "+15"}
    assert _m(intents.volume, "quieter please").args == {"level": "-15"}


def test_music_volume_still_belongs_to_spotify():
    for said in ("turn up the music", "set spotify volume to 40", "make the music quieter"):
        assert _m(intents.volume, said) is None, said
    assert _m(intents.volume, "roll a d6") is None


def test_volume_out_of_range_is_not_treated_as_a_level():
    assert _m(intents.volume, "set volume to 500") is None


def test_silent_mode_both_ways():
    assert _m(intents.quiet_mode, "you can be quiet now").args == {"enabled": True}
    assert _m(intents.quiet_mode, "stop talking").args == {"enabled": True}
    assert _m(intents.quiet_mode, "hold your tongue").args == {"enabled": True}
    assert _m(intents.quiet_mode, "silent mode off").args == {"enabled": False}
    assert _m(intents.quiet_mode, "you can talk again").args == {"enabled": False}
    assert _m(intents.quiet_mode, "resume your observations").args == {"enabled": False}


def test_silent_mode_keeps_out_of_the_music_and_confirmation_commands():
    for said in ("turn off the music", "stop the song", "yes", "no", "cancel that"):
        assert _m(intents.quiet_mode, said) is None, said


def test_where_the_voice_comes_out():
    assert _m(intents.voice_output, "speak through the bluetooth speaker").args == {"target": "bluetooth"}
    assert _m(intents.voice_output, "use your internal speaker").args == {"target": "internal"}
    assert _m(intents.voice_output, "cast your voice to the google home").args == {"cast": True}
    assert _m(intents.voice_output, "stop casting").args == {"cast": False}
    assert _m(intents.voice_output, "what did you say") is None


def test_quiet_hours():
    assert _m(intents.sleep_schedule, "set your sleep schedule from 11pm to 7am").args == {
        "start_hour": 23, "end_hour": 7, "enabled": True}
    assert _m(intents.sleep_schedule, "quiet hours from midnight until 6").args == {
        "start_hour": 0, "end_hour": 6, "enabled": True}
    assert _m(intents.sleep_schedule, "turn off your sleep schedule").args == {"enabled": False}
    # A question, or hours we cannot read, goes to the model rather than guessing.
    assert _m(intents.sleep_schedule, "what is your sleep schedule") is None
    assert _m(intents.sleep_schedule, "wake me at seven") is None


def test_which_game_is_on_the_table():
    assert _m(intents.active_game, "we're playing necromunda").args == {"game": "necromunda"}
    assert _m(intents.active_game, "switch to wfrp").args == {"game": "Warhammer Fantasy Roleplay"}
    assert _m(intents.active_game, "set the active game to warhammer 40k").args == {"game": "Warhammer 40k"}
    # Asking about a game is not switching to it, and an unknown game is the model's.
    assert _m(intents.active_game, "what are the necromunda rules for cover") is None
    assert _m(intents.active_game, "we're playing chess") is None


def test_spelled_out_numbers_are_read_like_digits():
    # Three rotations were spoken with the number as a word and never matched; the
    # model answered them with a running total it had invented.
    assert _m(intents.display_rotation, "rotate your display counterclockwise five degrees").args == {
        "degrees": -5.0, "absolute": False}
    assert _m(intents.display_rotation, "rotate the display clockwise twenty five degrees").args == {
        "degrees": 25.0, "absolute": False}
    assert _m(intents.volume, "set volume to fifty percent").args == {"level": "50"}
    assert _m(intents.sleep_schedule, "quiet hours from eleven pm to seven am").args == {
        "start_hour": 23, "end_hour": 7, "enabled": True}
    assert _m(intents.voice_wait, "set the voice wait to three seconds").args == {"seconds": 3.0}
    # Digits still work, and an utterance with no number is untouched.
    assert _m(intents.display_rotation, "rotate your display counterclockwise 15 degrees").args == {
        "degrees": -15.0, "absolute": False}


def test_disposition():
    assert _m(intents.shift_mood, "change your mood to contemplative").args == {"mood": "CONTEMPLATIVE"}
    assert _m(intents.shift_mood, "change mode to contemplative").args == {"mood": "CONTEMPLATIVE"}
    assert _m(intents.shift_mood, "shift your disposition to suspicious").args == {"mood": "SUSPICIOUS"}
    # A question is not a command, and an unknown mood belongs to the model.
    assert _m(intents.shift_mood, "what mood are you in") is None
    assert _m(intents.shift_mood, "change your mood to peckish") is None
