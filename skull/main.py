import argparse
import time
import signal
import sys
import threading
import random

from skull import config
from skull import audio, wake_word, transcribe, brain, tts, eyes, sfx, reminders, mood
from skull import spotify_ctrl, cast_audio, camera, quiet, display, temperature


def shutdown(sig=None, frame=None):
    print("\n[skull] Powering down. The Emperor protects.")
    display.cleanup()
    eyes.cleanup()
    audio.cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


_WAKE_PHRASES = [
    "Yes, my Lord?",
    "How may this unit serve?",
    "Awaiting your command.",
    "Speak your will.",
    "This unit attends.",
    "Your command, my Lord?",
]

_COGITATION_PHRASES = [
    "Cogitating.",
    "Consulting the archives.",
    "Accessing the data-vaults.",
    "The machine spirits deliberate.",
    "Searching the cogitator.",
    "Processing.",
]

# Short "stand by" lines spoken the instant Omega-7 starts a slow tool call
# (web search, news, rules lookup, Bluetooth scan) so the user gets immediate feedback.
_SEARCH_PHRASES = [
    "One moment. This unit consults the archives.",
    "Accessing the data-vaults. Stand by.",
    "Querying the noosphere. A moment, my Lord.",
    "Searching the cogitator banks.",
]

# Spoken the instant the user's request is heard — confirms receipt before the
# (otherwise silent) thinking begins. Fires on EVERY request, not just slow tool
# calls, so even a fast reply is preceded by acknowledgement.
_ACK_PHRASES = [
    "Acknowledged.",
    "As you command. One moment.",
    "Understood. Processing.",
    "Compliance. Stand by.",
    "By your will, my Lord.",
    "Affirmative. This unit attends to it.",
]

# Spoken when the wake word fires but no speech follows. Without this, a silent
# recording reaches Whisper, which (biased by its domain prompt) hallucinates 40k
# lore words and the brain rambles about the Mechanicum / Necromunda. Instead,
# Omega-7 simply acknowledges the silence and signals he is waiting.
_SILENCE_PHRASES = [
    "This unit awaits your command.",
    "Silence. Omega-7 stands ready when you are.",
    "I am listening, my Lord. Speak when you will.",
    "The vox is open. State your need.",
    "Nothing? This unit holds its vigil, awaiting your word.",
]

_wake_wavs: list = []
_cogitation_wavs: list = []
_search_wavs: list = []
_ack_wavs: list = []
_silence_wavs: list = []

# Serialises filler speech (search announcement + cogitation) so two threads never
# open the output device at once. The final reply plays after these are done.
_speech_lock = threading.Lock()


# ── ElevenLabs voice cache for the canned phrases ──────────────────────────────
# The prerecorded phrases (wake / cogitation / search / acknowledgement / boot) are
# spoken in the ElevenLabs voice regardless of TTS_BACKEND (which still governs the
# dynamic conversational replies). To avoid hitting the API on every boot, each
# phrase's WAV is cached to disk keyed by (voice id, text): changing
# ELEVENLABS_VOICE_ID transparently regenerates them, and RESET_VOICE_CACHE=true in
# .env wipes the cache so everything is re-synthesized on the next run.
import hashlib
import pathlib

_VOICE_CACHE_DIR = pathlib.Path("models/phrase_cache")


def _voice_cache_path(text: str) -> pathlib.Path:
    key = f"{config.ELEVENLABS_VOICE_ID}:{text}".encode("utf-8")
    return _VOICE_CACHE_DIR / f"{hashlib.sha1(key).hexdigest()[:16]}.wav"


def _eleven_cached(text: str) -> bytes:
    """Synthesize `text` in the ElevenLabs voice, caching the WAV to disk so the API
    is hit at most once per (voice, phrase)."""
    path = _voice_cache_path(text)
    if path.exists():
        return path.read_bytes()
    wav = tts.synthesize_elevenlabs(text)  # raises on failure → not cached
    try:
        _VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav)
    except Exception as e:
        print(f"[skull] Voice cache write error: {e}")
    return wav


def reset_voice_cache_if_requested() -> None:
    """If RESET_VOICE_CACHE=true, delete cached phrase audio (incl. the legacy boot
    cache) so the canned phrases are re-synthesized with the current ElevenLabs voice
    on this run."""
    import os
    if os.getenv("RESET_VOICE_CACHE", "false").lower() != "true":
        return
    import shutil
    try:
        if _VOICE_CACHE_DIR.exists():
            shutil.rmtree(_VOICE_CACHE_DIR)
        legacy = pathlib.Path(_BOOT_CACHE)
        if legacy.exists():
            legacy.unlink()
        print("[skull] RESET_VOICE_CACHE set — cleared cached phrase audio; regenerating "
              "with ElevenLabs. Set RESET_VOICE_CACHE=false to stop wiping on every boot.")
    except Exception as e:
        print(f"[skull] Voice cache reset error: {e}")


def _preload_phrases() -> None:
    global _wake_wavs, _cogitation_wavs, _search_wavs, _ack_wavs, _silence_wavs
    wake, cog, search, ack, silence = [], [], [], [], []
    for phrase in _WAKE_PHRASES:
        try:
            wake.append(_eleven_cached(phrase))
        except Exception as e:
            print(f"[skull] Wake phrase preload warning: {e}")
    for phrase in _COGITATION_PHRASES:
        try:
            cog.append(_eleven_cached(phrase))
        except Exception as e:
            print(f"[skull] Cogitation preload warning: {e}")
    for phrase in _SEARCH_PHRASES:
        try:
            search.append(_eleven_cached(phrase))
        except Exception as e:
            print(f"[skull] Search phrase preload warning: {e}")
    for phrase in _ACK_PHRASES:
        try:
            ack.append(_eleven_cached(phrase))
        except Exception as e:
            print(f"[skull] Ack phrase preload warning: {e}")
    for phrase in _SILENCE_PHRASES:
        try:
            silence.append(_eleven_cached(phrase))
        except Exception as e:
            print(f"[skull] Silence phrase preload warning: {e}")
    # Replace atomically so the main thread always sees a complete list
    _wake_wavs = wake
    _cogitation_wavs = cog
    _search_wavs = search
    _ack_wavs = ack
    _silence_wavs = silence
    print("[skull] Phrases preloaded (elevenlabs voice, cached)")


def _announce_search(tool_names) -> None:
    """Immediate spoken 'stand by' before a slow tool call. Called from brain.respond()."""
    print(f"[skull] Slow tool starting ({', '.join(tool_names)}) — announcing.")
    wav = None
    if _search_wavs:
        wav = random.choice(_search_wavs)
    with _speech_lock:
        try:
            if wav is not None:
                audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
            else:
                # Phrases not preloaded yet — synthesize one on the spot.
                audio.play_wav_bytes(
                    tts.synthesize(random.choice(_SEARCH_PHRASES)),
                    output_device=config.VOICE_OUTPUT_DEVICE,
                )
        except Exception as e:
            print(f"[skull] Search announcement error: {e}")


def _acknowledge() -> None:
    """Speak an immediate confirmation that the request was heard.

    Fires on every request (before the silent thinking begins), so the user always
    gets prompt feedback even when the reply itself comes back quickly. Plays
    blocking under _speech_lock so it finishes before the cogitation loop starts
    and never overlaps another output stream.
    """
    with _speech_lock:
        try:
            wav = random.choice(_ack_wavs) if _ack_wavs else tts.synthesize(random.choice(_ACK_PHRASES))
            audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception as e:
            print(f"[skull] Acknowledgement error: {e}")


def _acknowledge_silence() -> None:
    """Speak a brief 'I'm waiting' line when the wake word fired but no speech followed.

    Replaces the old silent `continue`, and short-circuits the brain entirely so a
    silent recording can't be turned into an unprompted lore monologue.
    """
    with _speech_lock:
        try:
            wav = random.choice(_silence_wavs) if _silence_wavs else tts.synthesize(random.choice(_SILENCE_PHRASES))
            audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception as e:
            print(f"[skull] Silence acknowledgement error: {e}")


def _cogitation_loop(cancel: threading.Event) -> None:
    """Play periodic thinking phrases while brain.respond() is running."""
    if cancel.wait(timeout=4.0):
        return
    indices = list(range(len(_cogitation_wavs)))
    random.shuffle(indices)
    i = 0
    while not cancel.is_set() and _cogitation_wavs:
        wav = _cogitation_wavs[indices[i % len(indices)]]
        try:
            with _speech_lock:
                audio.play_wav_bytes(wav, stop_event=cancel, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception:
            pass
        i += 1
        cancel.wait(timeout=5.0)


_BOOT_PHRASE = (
    "Omega-7 online. Neural cortex active. Ready to serve the Omnissiah."
)
_BOOT_CACHE = "models/boot_phrase.wav"


def _load_or_record_boot_wav() -> bytes:
    """Boot line in the ElevenLabs voice, served from the shared voice cache (keyed
    by voice id, so it regenerates if the voice changes or the cache is reset)."""
    return _eleven_cached(_BOOT_PHRASE)


def _speak_interruptible(wav_bytes: bytes, on_wake) -> bool:
    """Play wav_bytes while listening for the wake word so the user can barge in.

    Mirrors the main reply path's barge-in: a background listener stops playback
    the instant the wake word fires, and the eyes/display track speech amplitude
    throughout. Used by the unprompted speech paths (idle utterances, camera
    observations) which otherwise played to completion and ignored the wake word.

    Returns True if the wake word interrupted playback — the caller should set
    skip_wake_word so the next loop records the new command immediately. When not
    interrupted, the eyes are turned off and the display returned to idle here.
    """
    _stop_play = threading.Event()
    _interrupted = threading.Event()
    _cancel_listener = threading.Event()

    def _interrupt_listener():
        if wake_word.wait_for_wake_word(cancel=_cancel_listener):
            print("[skull] Interrupted — new command incoming.")
            _stop_play.set()
            _interrupted.set()
            if on_wake:
                on_wake()

    int_thread = threading.Thread(target=_interrupt_listener, daemon=True)
    int_thread.start()

    def _drive_visuals(amp: float) -> None:
        eyes.set_amplitude(amp)
        display.set_amplitude(amp)

    # Route to the same output the main reply path uses: cast to the Google Home
    # when configured, otherwise the local speaker. Either way the eyes/display
    # track amplitude and stop_event provides barge-in.
    if cast_audio.is_configured():
        cast_audio.play(wav_bytes, amplitude_fn_setter=lambda fn: _drive_visuals(fn()), stop_event=_stop_play)
    else:
        amp_ref = [None]
        play_done = threading.Event()

        def receive_amp(fn):
            amp_ref[0] = fn

        def eye_loop():
            time.sleep(0.05)
            while not play_done.is_set():
                amp = amp_ref[0]() if amp_ref[0] else 0.0
                _drive_visuals(amp)
                time.sleep(0.025)

        eye_thread = threading.Thread(target=eye_loop, daemon=True)
        eye_thread.start()

        try:
            audio.play_wav_bytes(
                wav_bytes,
                amplitude_cb=receive_amp,
                stop_event=_stop_play,
                output_device=config.VOICE_OUTPUT_DEVICE,
            )
        finally:
            play_done.set()
            eye_thread.join(timeout=1.0)

    if _interrupted.is_set():
        # Leave the eyes lit — on_wake() already turned them on for the next command.
        return True
    eyes.off()
    display.idle()
    _cancel_listener.set()
    int_thread.join(timeout=1.0)
    return False


def main():
    eyes.setup(config.LED_PIN_LEFT, config.LED_PIN_CENTER, config.LED_PIN_RIGHT)
    display.setup()
    display.set_mood(mood.get())
    camera.start()
    temperature.start()
    print("[skull] Omega-7 online. Awaiting the Emperor's commands.")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        mic_label = f"device {config.MIC_DEVICE_INDEX}" if config.MIC_DEVICE_INDEX >= 0 else "system default"
        out_label = f"device {config.VOICE_OUTPUT_DEVICE}" if config.VOICE_OUTPUT_DEVICE >= 0 else "system default"
        print(f"[skull] Mic: {mic_label}  |  Output: {out_label}")
        print(f"[skull] Available devices:\n{devices}")
    except Exception:
        pass

    # Honour RESET_VOICE_CACHE before anything reads the cache, so the boot phrase
    # and preloaded phrases regenerate with the current ElevenLabs voice this run.
    reset_voice_cache_if_requested()

    # Pre-synthesize phrases in background while boot phrase is being generated
    threading.Thread(target=_preload_phrases, daemon=True).start()

    sfx.play("skull_boot", config.VOICE_OUTPUT_DEVICE)
    try:
        boot_wav = _load_or_record_boot_wav()
        eyes.on()
        display.on()
        audio.play_wav_bytes(boot_wav, output_device=config.VOICE_OUTPUT_DEVICE)
    except Exception as e:
        print(f"[skull] Boot phrase error: {e}")
        time.sleep(0.5)
    finally:
        eyes.off()
        display.idle()

    skip_wake_word = False
    _IDLE_MIN, _IDLE_MAX = 5 * 60, 10 * 60  # seconds

    while True:
        # Back at idle — undo any music ducking from the previous interaction.
        spotify_ctrl.restore()

        # Immediate feedback the moment the wake word fires: dip music, ping, light
        # the eyes. Defined once per loop so every speech path — replies and the
        # unprompted observations/utterances below — can hand it to the barge-in listener.
        def on_wake():
            spotify_ctrl.duck()  # dip any playing music for the whole interaction
            sfx.play_blocking("wake_ping", config.VOICE_OUTPUT_DEVICE)
            eyes.on()

        # ── 0. Speak any internal-temperature warning ───────────────────────────
        # Fires regardless of silent mode — an overheating cogitator is a hardware
        # safety issue the master should always hear about.
        temp_warning = temperature.get_warning()
        if temp_warning:
            print(f"[skull] Temperature warning: {temp_warning}")
            try:
                spotify_ctrl.duck()
                sfx.play_blocking("negative", config.VOICE_OUTPUT_DEVICE)
                eyes.on()
                warn_wav = tts.synthesize(temp_warning)
                audio.play_wav_bytes(warn_wav, output_device=config.VOICE_OUTPUT_DEVICE)
            except Exception as _e:
                print(f"[skull] Temperature warning TTS error: {_e}")
            finally:
                eyes.off()
                spotify_ctrl.restore()
            continue  # back to the top; resume listening

        # ── 0a. Speak any reminders that fired during the last conversation ──────
        for _rem in reminders.get_due():
            print(f"[skull] Reminder firing: {_rem['message']}")
            try:
                spotify_ctrl.duck()
                sfx.play_blocking("wake_ping", config.VOICE_OUTPUT_DEVICE)
                eyes.on()
                rem_wav = tts.synthesize(_rem["message"])
                audio.play_wav_bytes(rem_wav, output_device=config.VOICE_OUTPUT_DEVICE)
            except Exception as _e:
                print(f"[skull] Reminder TTS error: {_e}")
            finally:
                eyes.off()
                spotify_ctrl.restore()
            reminders.add(_rem["message"], 10, repeating=True)

        # ── 0b. Speak any pending camera observations ──────────────────────────
        observation = camera.get_observation()
        if observation and quiet.is_silent():
            # Silent mode: drain the observation so it doesn't burst out later, but stay quiet.
            observation = None
        if observation:
            try:
                spotify_ctrl.duck()  # restored at the loop top after the `continue` below
                eyes.on()
                obs_wav = tts.synthesize(observation)
                # Barge-in: let the user cut in with the wake word mid-observation.
                if _speak_interruptible(obs_wav, on_wake):
                    skip_wake_word = True
            except Exception as e:
                print(f"[skull] Camera observation error: {e}")
                eyes.off()
                display.idle()
            continue

        # ── 1. Wait for wake word (skip after a barge-in interruption) ────────
        if skip_wake_word:
            skip_wake_word = False
            on_wake()
            ack = random.choice([
                "Ah, yes?",
                "Speak.",
                "Yes?",
                "Proceed.",
                "Command me.",
                "Why must you interrupt me?",
                "Again you interrupt Omega-7?",
                "This had better be important.",
                "Insufferable. What is it?",
            ])
            _barge_wav = None
            try:
                _barge_wav = tts.synthesize(ack)
            except Exception:
                pass
        else:
            _idle_cancel = threading.Event()
            _idle_fired = threading.Event()
            _due_reminders: list = []

            def _idle_timer():
                delay = random.uniform(_IDLE_MIN, _IDLE_MAX)
                if not _idle_cancel.wait(timeout=delay):
                    _idle_fired.set()
                    _idle_cancel.set()

            def _reminder_watcher():
                while not _idle_cancel.is_set():
                    due = reminders.get_due()
                    if due:
                        _due_reminders.extend(due)
                        _idle_cancel.set()
                        return
                    if temperature.has_pending():
                        _idle_cancel.set()  # wake the loop so the warning speaks at the top
                        return
                    _idle_cancel.wait(timeout=5.0)

            threading.Thread(target=_idle_timer, daemon=True).start()
            threading.Thread(target=_reminder_watcher, daemon=True).start()
            detected = wake_word.wait_for_wake_word(on_detected=on_wake, cancel=_idle_cancel)
            _idle_cancel.set()  # stop background threads if wake word fired first

            if not detected and _due_reminders:
                for _rem in _due_reminders:
                    print(f"[skull] Reminder firing: {_rem['message']}")
                    try:
                        spotify_ctrl.duck()  # restored at the loop top after the `continue` below
                        sfx.play_blocking("wake_ping", config.VOICE_OUTPUT_DEVICE)
                        eyes.on()
                        rem_wav = tts.synthesize(_rem["message"])
                        audio.play_wav_bytes(rem_wav, output_device=config.VOICE_OUTPUT_DEVICE)
                    except Exception as _e:
                        print(f"[skull] Reminder TTS error: {_e}")
                    finally:
                        eyes.off()
                    reminders.add(_rem["message"], 10, repeating=True)
                continue  # back to top of loop

            if not detected and _idle_fired.is_set():
                if quiet.is_silent():
                    print("[skull] Idle timeout — silent mode active, holding tongue.")
                    continue  # back to listening; no unprompted observation
                new_mood = mood.drift()
                if new_mood:
                    print(f"[skull] Mood drifted → {new_mood}")
                    display.set_mood(new_mood)
                print("[skull] Idle timeout — generating ambient utterance...")
                try:
                    spotify_ctrl.duck()  # restored at the loop top after the `continue` below
                    utterance = brain.idle_utterance()
                    if utterance:
                        print(f"[skull] Idle: {utterance}")
                        idle_wav = tts.synthesize(utterance)
                        eyes.on()
                        display.on()
                        # Barge-in: let the user cut in with the wake word mid-utterance.
                        if _speak_interruptible(idle_wav, on_wake):
                            skip_wake_word = True
                except Exception as e:
                    print(f"[skull] Idle utterance error: {e}")
                    eyes.off()
                    display.idle()
                continue  # back to listening without going through record/transcribe

            if not detected and temperature.has_pending():
                continue  # temp warning queued — spoken at the top of the loop

            _barge_wav = None

        # ── 2. Play wake ack, then record ────────────────────────────────────────
        # Wake phrase plays first (blocking) so the mic doesn't pick up the skull's
        # own speaker output. Recording starts after playback finishes.
        if _barge_wav is not None:
            try:
                audio.play_wav_bytes(_barge_wav, output_device=config.VOICE_OUTPUT_DEVICE)
            except Exception:
                pass
        elif _wake_wavs:
            try:
                audio.play_wav_bytes(
                    random.choice(_wake_wavs),
                    output_device=config.VOICE_OUTPUT_DEVICE,
                )
            except Exception:
                pass

        _rec_pcm: list = [None]
        _rec_exc: list = [None]
        _rec_done = threading.Event()

        def _do_record():
            try:
                _rec_pcm[0] = audio.record(
                    seconds=config.RECORD_SECONDS,
                    device_index=config.MIC_DEVICE_INDEX,
                    silence_threshold=config.SILENCE_THRESHOLD,
                    silence_duration=config.SILENCE_DURATION,
                )
            except Exception as e:
                _rec_exc[0] = e
            finally:
                _rec_done.set()

        threading.Thread(target=_do_record, daemon=True).start()
        print("[skull] Recording... (speak now)")
        if not _rec_done.wait(timeout=config.RECORD_SECONDS + 15.0):
            print("[skull] Recording hung — forcing recovery")
            try:
                import sounddevice as _sd_recovery
                _sd_recovery.stop()
            except Exception:
                pass
            eyes.off()
            continue

        if _rec_exc[0] is not None:
            print(f"[skull] Audio record error: {_rec_exc[0]}")
            sfx.play("negative", config.VOICE_OUTPUT_DEVICE)
            eyes.off()
            continue

        pcm, pcm_rate = _rec_pcm[0]
        if not pcm or audio.max_window_rms(pcm, pcm_rate) < config.SILENCE_THRESHOLD:
            print("[skull] No speech detected — acknowledging silence, not transcribing.")
            eyes.off()
            _acknowledge_silence()
            continue

        eyes.off()

        # ── 3. Transcribe ──────────────────────────────────────────────────────
        wav = audio.pcm_to_wav_bytes(pcm, pcm_rate)
        if config.AUDIO_DEBUG:
            import pathlib
            pathlib.Path("/tmp/skull_debug.wav").write_bytes(wav)
            print("[skull] DEBUG: saved recording to /tmp/skull_debug.wav — open it to hear what the mic captured")
        print("[skull] Transcribing...")
        try:
            user_text = transcribe.transcribe(wav)
        except Exception as e:
            print(f"[skull] STT error: {e}")
            sfx.play("negative", config.VOICE_OUTPUT_DEVICE)
            continue

        if not user_text:
            print("[skull] No speech detected — acknowledging silence.")
            _acknowledge_silence()
            continue

        print(f"[skull] Heard: {user_text}")

        # ── 3b. Detect explicit voice-switch requests ──────────────────────────
        _t = user_text.lower()
        # Unambiguous phrases match on their own (they name a backend or contain "voice").
        _ELEVENLABS_PHRASES = (
            "elevenlabs", "eleven labs", "cloud voice", "premium voice", "cloud tts",
            "fancy voice", "good voice", "better voice", "real voice", "nice voice",
        )
        _PIPER_PHRASES = (
            "piper", "local voice", "standard voice", "local tts",
            "basic voice", "offline voice", "robot voice", "cheap voice",
        )
        # Bare words that are too common to match alone (e.g. "Spotify Premium",
        # "premium ammunition") — only count when a voice-switch intent word is present.
        _SWITCH_INTENT = ("voice", "speak", "sound", "talk", "tts", "switch")
        _has_intent = any(w in _t for w in _SWITCH_INTENT)
        _AMBIGUOUS_ELEVENLABS = ("premium", "cloud")
        _AMBIGUOUS_PIPER = ("local", "offline")
        if any(p in _t for p in _ELEVENLABS_PHRASES) or (
            _has_intent and any(p in _t for p in _AMBIGUOUS_ELEVENLABS)
        ):
            config.TTS_BACKEND = "elevenlabs"
            print("[skull] TTS → elevenlabs (user request)")
            threading.Thread(target=_preload_phrases, daemon=True).start()
        elif any(p in _t for p in _PIPER_PHRASES) or (
            _has_intent and any(p in _t for p in _AMBIGUOUS_PIPER)
        ):
            config.TTS_BACKEND = "piper"
            print("[skull] TTS → piper (user request)")
            threading.Thread(target=_preload_phrases, daemon=True).start()

        # ── 3c. Detect on-demand idle observation request ─────────────────────
        _IDLE_TRIGGERS = ("idle observation", "status update", "observation", "what have you observed",
                          "ambient", "what's happening", "hive update", "tell me something")
        if any(p in _t for p in _IDLE_TRIGGERS):
            print("[skull] On-demand idle utterance requested.")
            try:
                utterance = brain.idle_utterance()
                if utterance:
                    print(f"[skull] Idle: {utterance}")
                    idle_wav = tts.synthesize(utterance)
                    eyes.on()
                    # Barge-in: let the user cut in with the wake word mid-utterance.
                    if _speak_interruptible(idle_wav, on_wake):
                        skip_wake_word = True
            except Exception as e:
                print(f"[skull] Idle utterance error: {e}")
                eyes.off()
            continue  # skip normal brain.respond(); idle timer resets on next loop

        # ── 4. Generate response ───────────────────────────────────────────────
        # Acknowledge the request immediately, then think (cogitation loop fills
        # longer waits with periodic phrases).
        _acknowledge()
        print("[skull] Consulting the Machine God...")
        display.think()  # spin the cog while the brain cogitates
        _cancel_cog = threading.Event()
        cog_thread = threading.Thread(target=_cogitation_loop, args=(_cancel_cog,), daemon=True)
        cog_thread.start()
        try:
            reply, spotify_cmds = brain.respond(user_text, on_tool_use=_announce_search)
        except Exception as e:
            print(f"[skull] Brain error: {e}")

            _cancel_cog.set()
            display.idle()
            continue
        finally:
            _cancel_cog.set()
            cog_thread.join(timeout=2.0)

        print(f"[skull] Omega-7: {reply}")

        # ── 4b. Execute commands ───────────────────────────────────────────────
        if not spotify_cmds:
            print("[skull] No Spotify command parsed from reply.")
        for cmd in spotify_cmds:
            print(f"[skull] Spotify command: {cmd}")
            try:
                if spotify_ctrl.is_configured():
                    if cmd[0] == "play":
                        device_name = cmd[2] if len(cmd) > 2 else config.SPOTIFY_DEVICE_NAME
                        result = spotify_ctrl.search_and_play(cmd[1], device_name=device_name)
                        print(f"[skull] Spotify: {result}")
                        if result in ("no-device", "not-found") or result.startswith(("error", "spotify-error", "playback-error")):
                            _error_phrases = {
                                "no-device": "This unit cannot locate the Spotify cogitator. Ensure the application is active.",
                                "not-found": "The requested composition could not be found in the Spotify archives.",
                            }
                            err_text = _error_phrases.get(result, "The Spotify cogitator has reported a malfunction.")
                            try:
                                audio.play_wav_bytes(tts.synthesize(err_text), output_device=config.VOICE_OUTPUT_DEVICE)
                            except Exception:
                                pass
                    elif cmd[0] == "pause":
                        spotify_ctrl.pause()
                    elif cmd[0] == "resume":
                        spotify_ctrl.resume()
                    elif cmd[0] == "skip":
                        spotify_ctrl.skip()
                else:
                    print("[skull] Spotify command ignored — SPOTIFY_CLIENT_ID/SECRET not set in .env")
            except Exception as e:
                print(f"[skull] Command error: {e}")

        # ── 5. Synthesize speech ───────────────────────────────────────────────
        tts_text = reply[:1200]  # cap chars (Piper is unlimited; guards ElevenLabs quota)
        try:
            # synthesize() already falls back from ElevenLabs to local Piper on
            # quota exhaustion; reaching this except means Piper failed too, so
            # drop to the OS system voice as a last resort.
            speech_wav = tts.synthesize(tts_text)
        except Exception as e:
            print(f"[skull] TTS error: {e} — using system TTS.")
            try:
                tts.synthesize_fallback(tts_text)
            except Exception as fe:
                print(f"[skull] System TTS error: {fe}")
            display.idle()  # stop the thinking spin; no amplitude path ran
            continue

        # ── 6. Play audio with barge-in (same path as idle observations) ─────────
        if _speak_interruptible(speech_wav, on_wake):
            # Wake word already heard; go straight to recording next iteration.
            skip_wake_word = True




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Omega-7 Servo Skull")
    parser.add_argument("--premium-voice", action="store_true",
                        help="Use ElevenLabs TTS for this session (overrides .env TTS_BACKEND)")
    args = parser.parse_args()
    if args.premium_voice:
        config.TTS_BACKEND = "elevenlabs"
        print("[skull] Premium voice enabled for this session.")
    main()
