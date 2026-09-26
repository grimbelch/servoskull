import argparse
import os
import time
import signal
import sys
import threading
import traceback
import random
import re
import pathlib
from concurrent.futures import ThreadPoolExecutor

# ── Module-level compiled regexes ─────────────────────────────────────────────
# Compiled once at import; never recompiled per loop iteration.
_RE_GAME_START = re.compile(
    r"\b(play|start|launch|run|begin)\b.*\b(bard|bardstale)\b"
    r"|\bwatch\s+.*play\b|\bplay\s+(the\s+)?game\b",
    re.I,
)
_RE_GAME_STOP = re.compile(
    r"\b(stop|end|quit|halt|enough)\b.*\b(bard|game|playing)\b",
    re.I,
)

_background_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="skull_bg")


def run_background_task(func, *args, **kwargs):
    """Execute a background function using the managed ThreadPoolExecutor."""
    return _background_executor.submit(func, *args, **kwargs)


from core import config
from core import db
db.init_db()
from core import audio, wake_word, transcribe, brain, tts, eyes, sfx, reminders, mood
from core import spotify_ctrl, cast_audio, camera, quiet, display, temperature, candles, bambu_ctrl


def shutdown(sig=None, frame=None):
    _shutdown_requested = True
    farewell = config.PERSONALITY.get("shutdown_message", "Powering down.")
    print(f"\n[skull] {farewell}")
    try:
        _background_executor.shutdown(wait=False)
    except Exception:
        pass
    try:
        monitor = bambu_ctrl.get_monitor()
        if monitor:
            monitor.stop()
    except Exception:
        pass
    display.cleanup()
    eyes.cleanup()
    candles.cleanup()
    audio.cleanup()
    os._exit(0)


if threading.current_thread() == threading.main_thread():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)






# Short "stand by" lines spoken the instant Omega-7 starts a slow tool call
# (web search, news, rules lookup, Bluetooth scan) so the user gets immediate feedback.


# Spoken the instant the user's request is heard — confirms receipt before the
# (otherwise silent) thinking begins. Fires on EVERY request, not just slow tool
# calls, so even a fast reply is preceded by acknowledgement.


# Spoken when the wake word fires but no speech follows. Without this, a silent
# recording reaches Whisper, which (biased by its domain prompt) hallucinates 40k
# lore words and the brain rambles about the Mechanicum / Necromunda. Instead,
# Omega-7 simply acknowledges the silence and signals he is waiting.


_wake_wavs: list = []
_cogitation_wavs: list = []
_search_wavs: list = []
_ack_wavs: list = []
_silence_wavs: list = []

# Serialises filler speech (search announcement + cogitation) so two threads never
# open the output device at once. The final reply plays after these are done.
_speech_lock = threading.RLock()


# ── ElevenLabs voice cache for the canned phrases ──────────────────────────────
# The prerecorded phrases (wake / cogitation / search / acknowledgement / boot) are
# spoken in the ElevenLabs voice regardless of TTS_BACKEND (which still governs the
# dynamic conversational replies). To avoid hitting the API on every boot, each
# phrase's WAV is cached to disk keyed by (voice id, text): changing
# ELEVENLABS_VOICE_ID transparently regenerates them, and RESET_VOICE_CACHE=true in
# .env wipes the cache so everything is re-synthesized on the next run.
import hashlib
import pathlib

_persona_key = config.get_personality_key() if hasattr(config, "get_personality_key") else config.SKULL_NAME.lower().replace("-", "")
_VOICE_CACHE_DIR = pathlib.Path(f"models/phrase_cache/{_persona_key}")


def _voice_cache_path(text: str) -> pathlib.Path:
    key = f"{config.SKULL_NAME}:{config.ELEVENLABS_VOICE_ID}:{text}".encode("utf-8")
    return _VOICE_CACHE_DIR / f"{hashlib.sha1(key).hexdigest()[:16]}.wav"


def _eleven_cached(text: str) -> bytes:
    """Synthesize `text` in the ElevenLabs voice, caching the WAV to disk so the API
    is hit at most once per (voice, phrase)."""
    path = _voice_cache_path(text)
    if path.exists():
        cached = path.read_bytes()
        if cached[:4] == b"RIFF" and len(cached) > 44:
            return cached
        print(f"[skull] Discarding damaged cached phrase {path.name}; re-synthesizing.")
    wav = tts.synthesize_elevenlabs(text)  # raises on failure → not cached
    try:
        config.atomic_write(path, wav)
    except Exception as e:
        print(f"[skull] Voice cache write error: {e}")
    return wav


def reset_voice_cache_if_requested() -> None:
    """If RESET_VOICE_CACHE=true, delete cached phrase audio (incl. the legacy boot
    cache) so the canned phrases are re-synthesized with the current ElevenLabs voice
    on this run."""
    if not config.RESET_VOICE_CACHE:
        return
    import shutil
    try:
        if _VOICE_CACHE_DIR.exists():
            shutil.rmtree(_VOICE_CACHE_DIR)
        legacy = pathlib.Path("models/boot_phrase.wav")
        if legacy.exists():
            legacy.unlink()
        print("[skull] RESET_VOICE_CACHE set — cleared cached phrase audio; regenerating "
              "with ElevenLabs. Set RESET_VOICE_CACHE=false to stop wiping on every boot.")
    except Exception as e:
        print(f"[skull] Voice cache reset error: {e}")


def refresh_voice_cache() -> str:
    import shutil
    try:
        if _VOICE_CACHE_DIR.exists():
            shutil.rmtree(_VOICE_CACHE_DIR)
        legacy = pathlib.Path("models/boot_phrase.wav")
        if legacy.exists():
            legacy.unlink()
        
        run_background_task(lambda: _preload_phrases(show_progress=True))
        print("[skull] Voice cache refresh triggered with display progress indicator.")
        return "Voice cache cleared and background phrase synthesis initiated. Displaying rebuild progress now."
    except Exception as e:
        print(f"[skull] Voice cache refresh error: {e}")
        return f"Failed to refresh voice cache: {e}"


def _get_active_service() -> str:
    import subprocess
    for svc in ["omega7", "omega8"]:
        try:
            res = subprocess.run(["systemctl", "is-active", "--quiet", f"{svc}.service"], capture_output=True)
            if res.returncode == 0:
                return svc
        except Exception:
            pass
    return "omega7"


def _do_update_async():
    import subprocess
    import sys
    import os
    import tempfile
    try:
        print("[skull] Starting background update task...")
        display.start_update_progress()
        display.set_update_progress(0.0, "INITIATING...")
        time.sleep(2)  # Give time for verbal confirmation audio to play

        display.set_update_progress(25.0, "GIT PULL")
        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        git_env["GIT_MERGE_AUTOEDIT"] = "no"
        
        pull_res = subprocess.run(
            ["git", "pull", "--no-edit", "--autostash"],
            capture_output=True, text=True, check=True, timeout=120, env=git_env
        )
        print(f"[update] Git Pull Output: {pull_res.stdout}")

        display.set_update_progress(50.0, "INSTALLING...")
        venv_pip = pathlib.Path(sys.prefix) / "bin" / "pip"
        if venv_pip.exists():
            req_file = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"
            if req_file.exists():
                req_lines = req_file.read_text().splitlines()
                filtered = [line for line in req_lines if not line.strip().startswith("openwakeword")]
                
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
                    tf.write("\n".join(filtered) + "\n")
                    temp_req_path = tf.name

                try:
                    res_pip = subprocess.run(
                        [str(venv_pip), "install", "--prefer-binary", "-r", temp_req_path],
                        capture_output=True, text=True, check=True, timeout=300
                    )
                    print(f"[update] Pip Install Output: {res_pip.stdout}")

                    subprocess.run(
                        [str(venv_pip), "install", "--no-deps", "openwakeword"],
                        capture_output=True, text=True, check=False, timeout=60
                    )
                finally:
                    try:
                        os.remove(temp_req_path)
                    except Exception:
                        pass

        display.set_update_progress(100.0, "RESTARTING...")
        time.sleep(2)
        active_svc = _get_active_service()
        print(f"[skull] Update complete. Restarting service '{active_svc}'...")
        subprocess.run(["sudo", "systemctl", "restart", active_svc], check=True)
    except subprocess.CalledProcessError as ce:
        display.stop_update_progress()
        err_msg = ce.stderr or ce.stdout or str(ce)
        print(f"[skull] Update failed during background execution: {err_msg}")
    except Exception as e:
        display.stop_update_progress()
        print(f"[skull] Update error during background execution: {e}")


def self_update() -> str:
    print("[skull] Self-update requested. Spawning background update worker...")
    run_background_task(_do_update_async)
    return "Initiating system self-update now. Pulling latest code from GitHub and updating dependencies. I will restart the machine spirit shortly."




def _game_narrate(text: str) -> None:
    """Queue a Bard's Tale narration sentence for async TTS — never blocks the game loop."""
    if not text or not text.strip():
        return

    def _do_narrate():
        try:
            with _speech_lock:
                wav = tts.synthesize(text)
                audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception as e:
            print(f"[bardstale] narration TTS error: {e}")

    run_background_task(_do_narrate)

_pending_system_command = None

def reboot_system() -> str:
    global _pending_system_command
    _pending_system_command = "reboot"
    print("[skull] Initiating full system reboot...")
    return "Initiating full system reboot. Power cycles will commence."


def shutdown_system() -> str:
    global _pending_system_command
    _pending_system_command = "shutdown"
    print("[skull] Initiating full system shutdown...")
    return "Initiating full system shutdown. Powering down all machine spirits."


def switch_personality(target: str) -> str:
    """Switch to the other personality (jax or omega7), persisting across reboots."""
    global _pending_system_command
    target = target.strip().lower()
    if target not in ("jax", "omega7"):
        return f"Unknown personality '{target}'. Valid options are 'jax' or 'omega7'."

    current_key = config.get_personality_key()
    if current_key == target:
        return f"I'm already {config.SKULL_NAME}! No switch needed."

    if target == "omega7":
        farewell = "Switching over to Omega-7 now! Be good while I'm gone — I'll miss you! Woof!"
    else:
        farewell = "Transferring control to the biological canine unit Jax. The Emperor protects. Farewell."

    print(f"[skull] Switching personality to '{target}' via switch-personality script...")
    _pending_system_command = f"switch_{target}"
    return farewell


def _execute_pending_system_command():
    global _pending_system_command
    if _pending_system_command:
        cmd = _pending_system_command
        _pending_system_command = None
        import subprocess
        print(f"[skull] Executing pending system command: {cmd}")
        try:
            if cmd == "reboot":
                subprocess.run(["sudo", "systemctl", "reboot"], check=True)
            elif cmd == "shutdown":
                subprocess.run(["sudo", "systemctl", "poweroff"], check=True)
            elif cmd.startswith("switch_"):
                target = cmd.split("_")[1]
                script_path = pathlib.Path(__file__).parent.parent / "switch-personality"
                subprocess.run([
                    "sudo", "systemd-run",
                    "--unit=personality-switcher",
                    str(script_path.resolve()), target
                ], check=True)
        except Exception as e:
            print(f"[skull] System command error: {e}")



_speech_activation_active = False
_speech_active_lock = threading.Lock()
_pending_bambu_lock = threading.Lock()
_pending_bambu_notifications: list[tuple[str, str]] = []


def set_speech_active(active: bool) -> None:
    global _speech_activation_active
    with _speech_active_lock:
        _speech_activation_active = bool(active)


def is_speech_active() -> bool:
    with _speech_active_lock:
        return _speech_activation_active


def _deliver_bambu_notification(event_type: str, text: str) -> None:
    try:
        wav_bytes = tts.synthesize(text)
        with _speech_lock:
            try:
                sfx.play_blocking("wake_ping", config.VOICE_OUTPUT_DEVICE)
            except Exception:
                pass
            eyes.on()
            display.on()
            try:
                audio.play_wav_bytes(wav_bytes, output_device=config.VOICE_OUTPUT_DEVICE)
            finally:
                eyes.off()
                display.idle()
    except Exception as e:
        print(f"[skull] Bambu notification error: {e}")


def _speak_bambu_notification(event_type: str, text: str) -> None:
    """Announce a Bambu 3D printer event verbally, queuing if speech is active."""
    print(f"[skull] Bambu notification ({event_type}): {text}")
    if is_speech_active():
        print(f"[skull] Speech activation in progress — queuing Bambu notification ({event_type})")
        with _pending_bambu_lock:
            _pending_bambu_notifications.append((event_type, text))
        return

    _deliver_bambu_notification(event_type, text)


def _flush_pending_bambu_notifications() -> None:
    with _pending_bambu_lock:
        if not _pending_bambu_notifications:
            return
        pending = list(_pending_bambu_notifications)
        _pending_bambu_notifications.clear()

    for event_type, text in pending:
        _deliver_bambu_notification(event_type, text)


def _preload_phrases(show_progress: bool = False) -> None:
    global _wake_wavs, _cogitation_wavs, _search_wavs, _ack_wavs, _silence_wavs
    key = (getattr(config, "ELEVENLABS_API_KEY", "") or "").strip()
    if not key:
        print("[skull] ElevenLabs API key not set — phrase preloading skipped, using local Piper TTS.")
        return

    wake, cog, search, ack, silence = [], [], [], [], []
    lists_and_targets = [
        (config.WAKE_PHRASES, wake),
        (config.COGITATION_PHRASES, cog),
        (config.SEARCH_PHRASES, search),
        (config.ACK_PHRASES, ack),
        (config.SILENCE_PHRASES, silence),
    ]

    total_phrases = sum(len(phrases) for phrases, _ in lists_and_targets)
    done_count = 0

    if show_progress:
        display.start_update_progress()
        display.set_update_progress(0.0, "REBUILDING 0%")

    try:
        for phrases, target_list in lists_and_targets:
            for phrase in phrases:
                try:
                    target_list.append(_eleven_cached(phrase))
                except Exception as e:
                    print(f"[skull] ElevenLabs phrase preloading halted ({e}) — using local Piper TTS.")
                    _wake_wavs = wake
                    _cogitation_wavs = cog
                    _search_wavs = search
                    _ack_wavs = ack
                    _silence_wavs = silence
                    if show_progress:
                        display.stop_update_progress()
                    return
                done_count += 1
                if show_progress and total_phrases > 0:
                    pct = (done_count / total_phrases) * 100.0
                    display.set_update_progress(pct, f"REBUILDING {int(pct)}%")

        # Replace atomically so the main thread always sees a complete list
        _wake_wavs = wake
        _cogitation_wavs = cog
        _search_wavs = search
        _ack_wavs = ack
        _silence_wavs = silence
        print(f"[skull] Phrases preloaded ({done_count}/{total_phrases} elevenlabs voice, cached)")
        if show_progress:
            display.set_update_progress(100.0, "REBUILT")
            time.sleep(1.5)
    finally:
        if show_progress:
            display.stop_update_progress()


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
                    tts.synthesize(random.choice(config.SEARCH_PHRASES)),
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
            wav = random.choice(_ack_wavs) if _ack_wavs else tts.synthesize(random.choice(config.ACK_PHRASES))
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
            wav = random.choice(_silence_wavs) if _silence_wavs else tts.synthesize(random.choice(config.SILENCE_PHRASES))
            audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception as e:
            print(f"[skull] Silence acknowledgement error: {e}")


def _cogitation_loop(cancel: threading.Event) -> None:
    """Play periodic thinking phrases while brain.respond() is running."""
    if cancel.wait(timeout=8.0):
        return
    indices = list(range(len(_cogitation_wavs)))
    random.shuffle(indices)
    i = 0
    while not cancel.is_set() and _cogitation_wavs:
        if getattr(config, "COGITATION_SUSPENDED", False):
            cancel.wait(timeout=0.5)
            continue
        wav = _cogitation_wavs[indices[i % len(indices)]]
        try:
            with _speech_lock:
                audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception:
            pass
        i += 1
        cancel.wait(timeout=12.0)


def _get_boot_phrase() -> str:
    return config.PERSONALITY.get("boot_phrase", f"{config.SKULL_NAME} online.")


def _load_or_record_boot_wav() -> bytes:
    """Boot line in the ElevenLabs voice, served from the shared voice cache."""
    phrase = _get_boot_phrase()
    try:
        return _eleven_cached(phrase)
    except Exception as e:
        print(f"[skull] ElevenLabs boot phrase unavailable ({e}), using local Piper TTS...")
        return tts.synthesize(phrase)


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
    with _speech_lock:
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


def _spotify_poller_loop():
    """Keep the eye's music indicator in sync with Spotify. Each check is a web API
    call, so poll quickly only while music is playing: 5 s when playing, 30 s when
    not, 5 min during sleep hours with nothing playing (was every 4 s, all night)."""
    while True:
        playing = False
        try:
            if spotify_ctrl.is_configured():
                playing = spotify_ctrl.is_playing()
                display.set_music_playing(playing)
        except Exception as e:
            print(f"[main] Spotify status check failed: {e}")
        if playing:
            time.sleep(5.0)
        elif quiet.is_in_sleep_hours():
            time.sleep(300.0)
        else:
            time.sleep(30.0)


def _said_any(text: str, phrases) -> bool:
    """Whole-word/phrase match, so "now" or "know" don't read as "no".

    Module-level on purpose: main() has local `import re` statements, which make
    `re` a local of main() and break closures defined inside it that use `re`.
    """
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in phrases)


# ── Maintenance commands (update / reboot / shutdown) ────────────────────────
# Matched against the whole utterance (after dropping filler words), never as a
# substring, so "turn off the music" or "restart the song" can't power the Pi
# down. Each one is also confirmed with a spoken "yes" before it runs.
_MAINT_FILLER = re.compile(
    r"\b(please|now|immediately|omega\s*(?:7|seven|8|eight)|servitor|jax|hey|ok|okay|can you|"
    r"could you|would you|will you|i want you to|i need you to|go ahead and|the|a)\b"
)
_MAINT_COMMANDS = (
    ("update", re.compile(r"(?:run )?(?:self|system) update|update (?:your software|yourself|your system)|pull updates")),
    ("reboot", re.compile(r"reboot(?: system| yourself)?|restart (?:system|yourself)")),
    ("shutdown", re.compile(r"shut ?down(?: system| yourself)?|power (?:down|off)(?: system| yourself)?"
                            r"|turn (?:yourself|system) off|turn off (?:yourself|system)")),
)
_MAINT_LABELS = {"update": "a system update", "reboot": "a full reboot", "shutdown": "a full shutdown"}
_MAINT_CONFIRM_SECS = 30.0
_CONFIRM_YES = ("yes", "yeah", "yep", "yup", "affirmative", "confirm", "confirmed", "do it", "proceed",
                "go ahead", "i'm sure", "i am sure", "correct", "aye")
_CONFIRM_NO = ("no", "nope", "nah", "cancel", "abort", "stop", "don't", "do not", "negative",
               "never mind", "nevermind", "wait")


def _maintenance_command(text: str) -> str | None:
    """Return "update", "reboot" or "shutdown" only if that is the entire request."""
    t = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    t = " ".join(_MAINT_FILLER.sub(" ", t).split())
    for action, pattern in _MAINT_COMMANDS:
        if pattern.fullmatch(t):
            return action
    return None


def _maintenance_prompt(action: str) -> str:
    label = _MAINT_LABELS[action]
    if config.PERSONALITY.get("eye_animation") == "dog":
        return f"Do you really want {label}? Say yes if you're sure!"
    return f"Master, confirm {label} of this unit? Speak yes to proceed."


def _run_maintenance(action: str, on_wake) -> None:
    """Announce and carry out a confirmed update, reboot or shutdown."""
    key, default = {
        "update": ("update_message", "Initiating system update."),
        "reboot": ("reboot_message", "Initiating system reboot."),
        "shutdown": ("shutdown_message", "Initiating system shutdown."),
    }[action]
    try:
        eyes.on()
        _speak_interruptible(tts.synthesize(config.PERSONALITY.get(key, default)), on_wake)
    except Exception:
        pass
    if action == "update":
        self_update()
    elif action == "reboot":
        reboot_system()
    else:
        shutdown_system()
    _execute_pending_system_command()


# Update/reboot/shutdown requested by Claude's tools. Nothing runs until the user
# confirms aloud: the main loop picks the request up after the reply and asks.
_maintenance_requested: str | None = None


def request_maintenance(action: str) -> str:
    """Tool callback for self_update / reboot_system / shutdown_system."""
    global _maintenance_requested
    _maintenance_requested = action
    print(f"[skull] Claude requested {action} — will ask the user to confirm aloud.")
    return (f"{_MAINT_LABELS[action].capitalize()} has NOT been started. It needs the user's spoken "
            "confirmation, which the system will ask for immediately after your reply. Reply with one "
            "short sentence at most, and do not say that it is happening.")


def _take_maintenance_request() -> str | None:
    global _maintenance_requested
    action, _maintenance_requested = _maintenance_requested, None
    return action


def _split_for_pipelining(text: str, min_first: int = 25, min_total: int = 90) -> tuple[str, str]:
    """Split a reply into (first sentence, rest) so the first can be spoken while the
    rest is still being synthesized. Short or single-sentence replies aren't split."""
    clean = (text or "").strip()
    if len(clean) < min_total:
        return clean, ""
    parts = re.split(r"(?<=[.!?])\s+", clean)
    if len(parts) < 2:
        return clean, ""
    first, i = parts[0], 1
    while len(first) < min_first and i < len(parts) - 1:
        first += " " + parts[i]
        i += 1
    rest = " ".join(parts[i:]).strip()
    return (first, rest) if rest else (clean, "")


# ── Personality switch requests ──────────────────────────────────────────────────
# Only explicit requests count ("switch to Jax", "change into Omega 7", "become the
# dog"), and the target must be exactly a personality's id, name or alias. Matching
# any sentence that merely contained "change" plus a name swallowed commands like
# "Omega 7, change the song" and switched on "what will become of my dog".
_SWITCH_LEADING = re.compile(r"^(?:(?:hey|ok|okay|please|omega[\s-]*(?:7|seven)|servitor|jax)\s+)*")
_SWITCH_RE = re.compile(
    r"(?:(?:switch|change|swap|turn)\s+(?:yourself\s+|your\s+personality\s+|personality\s+)?(?:back\s+)?"
    r"(?:to|into)|become)\s+(?:the\s+)?(?P<target>.+?)(?:\s+(?:personality|mode|please|now|again))*"
)
_SWITCHABLE = ("omega7", "jax")  # the personalities switch_personality() accepts


def _personality_switch_target(text: str) -> str | None:
    t = " ".join(re.sub(r"[^a-z0-9\s-]", " ", (text or "").lower()).split())
    t = _SWITCH_LEADING.sub("", t)
    m = _SWITCH_RE.fullmatch(t)
    if not m:
        return None
    target = m.group("target").replace("-", " ").strip()
    try:
        import json
        p_path = pathlib.Path(__file__).parent.parent / "personalities" / "personalities.json"
        valid = json.loads(p_path.read_text()).get("personalities", {})
    except Exception:
        valid = {}
    for p_id in _SWITCHABLE:
        info = valid.get(p_id, {})
        names = {p_id, str(info.get("name", p_id)).lower(), *[a.lower() for a in info.get("aliases", [])]}
        if target in {n.replace("-", " ") for n in names}:
            return p_id
    return None


def _briefing_offer_text() -> str:
    if config.PERSONALITY.get("eye_animation") == "dog":
        return (
            "Good morning, buddy! I've been sniffing around and I've got the weather and the latest updates. "
            "Are you ready for your morning briefing? Woof!"
        )
    return (
        "Master. This unit has compiled your morning cogitations — "
        "weather data, hive dispatches, and machine-spirit telemetry. "
        "Are you ready to receive your daily briefing?"
    )


_last_morning_greeting_date: str | None = None
_MORNING_GREETING_KV = "morning_greeting_date"  # persisted so a restart doesn't re-greet
_morning_greeting_lock = threading.Lock()
_startup_complete: bool = False
# Set by the proximity watcher after a morning greeting; the main loop picks it up
# and asks whether the master wants the daily briefing.
_morning_briefing_offer_pending = threading.Event()


def _morning_greeting_watcher() -> None:
    """Background loop checking rangefinder distance outside sleep hours.

    If a target is within MORNING_GREETING_DISTANCE_CM, a face is visible and the morning
    greeting has not yet fired today, identifies the person, delivers a greeting and
    hands off to the main loop to offer the daily briefing.
    """
    global _last_morning_greeting_date, _startup_complete
    threshold = float(config.MORNING_GREETING_DISTANCE_CM)
    print(f"[morning] Proximity morning greeting watcher active (outside sleep hours, <= {threshold:.0f} cm)")
    closest_cm: float | None = None
    last_report = time.time()
    while True:
        time.sleep(0.5)
        try:
            if not _startup_complete:
                continue

            from datetime import datetime
            now = datetime.now()
            from core import quiet
            if quiet.is_in_sleep_hours():
                continue

            today_str = now.strftime("%Y-%m-%d")

            with _morning_greeting_lock:
                if _last_morning_greeting_date is None:
                    _last_morning_greeting_date = db.kv_get(_MORNING_GREETING_KV, None)
                if _last_morning_greeting_date == today_str:
                    continue

            from core import proximity

            cm = proximity.get_latest_distance_cm()
            if cm is not None and cm > 0 and (closest_cm is None or cm < closest_cm):
                closest_cm = cm
            if time.time() - last_report >= 1800:
                closest = f"{closest_cm:.0f} cm" if closest_cm is not None else "no readings"
                print(f"[morning] Still waiting for morning target — closest in last 30 min: {closest} (threshold {threshold:.0f} cm)")
                closest_cm = None
                last_report = time.time()
            if cm is None or cm <= 0 or cm > threshold:
                continue

            from core import camera, brain, tts, audio, web
            _, detected_name, face_found = camera.capture_and_identify()

            if not face_found:
                # Rangefinder was triggered by a static object (desk/chair/monitor).
                # Re-check in 5 minutes (300s) when no face is present.
                print(f"[morning] Target at {cm:.0f} cm but no face in frame — rechecking in 5 min.")
                time.sleep(300.0)
                continue

            if not detected_name:
                # Human face detected at console in morning — default to Master Sean if match score was slightly below threshold
                detected_name = getattr(config, "OWNER_NAME", "Sean") or "Sean"

            # Don't talk over a conversation that's already under way; try again shortly.
            if is_speech_active():
                time.sleep(5.0)
                continue

            print(f"[morning] Morning target identified as '{detected_name}' at {cm:.1f} cm (<= {threshold:.0f} cm) — delivering morning greeting...")

            greeting_text = brain.generate_morning_greeting(detected_name)
            print(f"[morning] Morning greeting ({detected_name}): {greeting_text}")
            try:
                speech_wav = tts.synthesize(greeting_text)
            except Exception as se:
                print(f"[morning] Greeting synthesis error: {se}")
                time.sleep(30.0)
                continue

            # Mark today's morning greeting as delivered (persisted across restarts).
            with _morning_greeting_lock:
                _last_morning_greeting_date = today_str
            try:
                db.kv_set(_MORNING_GREETING_KV, today_str)
            except Exception as e:
                print(f"[morning] Could not persist greeting date: {e}")

            brain.record_assistant_turn(greeting_text)
            web.log_vox(config.SKULL_NAME, greeting_text)

            # Speak under the speech lock so the greeting never overlaps a reply
            # (bypasses silent mode for the morning greeting).
            with _speech_lock:
                set_speech_active(True)
                spotify_ctrl.duck()
                display.on()
                eyes.on()
                try:
                    audio.play_wav_bytes(speech_wav, output_device=config.VOICE_OUTPUT_DEVICE)
                except Exception as se:
                    print(f"[morning] Greeting speech delivery error: {se}")
                finally:
                    set_speech_active(False)
                    spotify_ctrl.restore()
                    display.idle()
                    eyes.off()

            if brain.is_daily_briefing_due():
                # Interrupt the wake-word wait so the main loop offers the briefing now.
                _morning_briefing_offer_pending.set()
                web.trigger_cancel()

        except Exception as e:
            print(f"[morning] Error in morning greeting watcher: {e}")
            time.sleep(10.0)


_setup_repeater_stop = threading.Event()


def stop_setup_repeater() -> None:
    """Signal the setup announcement repeater to stop."""
    _setup_repeater_stop.set()


def _play_setup_announcement() -> None:
    try:
        eyes.on()
        display.on()
        from core import wifi_provisioner
        display.show_setup_screen(wifi_provisioner.SETUP_SSID,
                                  wifi_provisioner.hotspot_password() or "(starting)",
                                  "192.168.4.1:8080")

        cached_setup_wav = pathlib.Path("models/phrase_cache/setup_announcement.wav")
        if cached_setup_wav.exists():
            print("[skull] Playing pre-cached ElevenLabs setup vocal announcement from disk...")
            setup_bytes = cached_setup_wav.read_bytes()
        else:
            setup_announcement = (
                "Greetings. I am an unconfigured Servo Skull unit. "
                "Please connect your mobile device or cogitator to my Wi-Fi access point, "
                "Omega-7-Setup, using the password shown on my eye, to begin initialization."
            )
            print("[skull] Speaking setup vocal announcement via Piper local TTS...")
            setup_bytes = tts.synthesize_piper(setup_announcement)
        audio.play_wav_bytes(setup_bytes, output_device=config.VOICE_OUTPUT_DEVICE)
    except Exception as e:
        print(f"[skull] Setup vocal announcement error: {e}")


def _start_setup_announcement_repeater(interval_sec: float = 120.0) -> None:
    """Repeat the setup announcement phrase every 2 minutes until a client connects to the Wi-Fi AP or web portal."""
    def _loop():
        from core import wifi_provisioner, web
        print(f"[skull] Launching setup announcement repeater loop (every {interval_sec}s)...")
        _play_setup_announcement()

        elapsed = 0.0
        while not _setup_repeater_stop.is_set():
            if _setup_repeater_stop.wait(timeout=1.0):
                break
            
            # Stop repeating once user connects to the AP or opens web page
            if (hasattr(wifi_provisioner, "has_ap_client") and wifi_provisioner.has_ap_client()) or \
               (hasattr(web, "has_web_client_connected") and web.has_web_client_connected()) or \
               config.is_configured():
                print("[skull] User connected to Wi-Fi AP / Web portal — stopping setup announcement repeater.")
                break

            elapsed += 1.0
            if elapsed >= interval_sec:
                elapsed = 0.0
                print("[skull] 2-minute setup repeater timer elapsed — repeating setup announcement...")
                _play_setup_announcement()

    threading.Thread(target=_loop, daemon=True).start()


def main():
    brain.register_reload_cb(refresh_voice_cache)
    # Claude's tools only request these; they run after a spoken yes (see request_maintenance).
    brain.register_update_cb(lambda: request_maintenance("update"))
    brain.register_reboot_cb(lambda: request_maintenance("reboot"))
    brain.register_shutdown_cb(lambda: request_maintenance("shutdown"))
    brain.register_switch_personality_cb(switch_personality)

    # Set default output volume to 50% on boot
    try:
        audio.set_system_volume("50%")
        print("[skull] Boot volume initialized to 50%")
    except Exception as e:
        print(f"[skull] Failed to set boot volume: {e}")

    eyes.setup(config.EYE_LED_PIN, config.EYE_LED_COUNT)
    candles.setup(config.CANDLE_PIN)
    candles.on()  # ambient — flicker for as long as the skull is powered
    display.setup()
    display.set_mood(mood.get())
    display.start_omnissiah_glyph(4.0)
    from core import proximity
    proximity.start()
    camera.start()
    temperature.start()
    temperature.start_power_monitor()
    bambu_ctrl.init(_speak_bambu_notification)
    bambu_ctrl.get_monitor().start()
    threading.Thread(target=_spotify_poller_loop, daemon=True).start()
    from core import ambient_music
    ambient_music.register_main_hooks(_speak_interruptible, is_speech_active)
    ambient_music.start()
    from core import web

    web.start()
    print(f"[skull] {config.SKULL_NAME} online.")
    audio.optimize_mic_levels()
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        mic_label = f"device {config.MIC_DEVICE_INDEX}" if config.MIC_DEVICE_INDEX is not None and config.MIC_DEVICE_INDEX >= 0 else "system default"
        out_label = f"device {config.VOICE_OUTPUT_DEVICE}" if config.VOICE_OUTPUT_DEVICE is not None else "system default"
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
    display.start_omnissiah_glyph(4.0)

    # ── First-Boot / Unconfigured Appliance Check ──────────────────────────────

    from core import wifi_provisioner
    wifi_status = wifi_provisioner.get_status()
    if not config.is_configured() or not wifi_status.get("connected") or wifi_status.get("is_ap"):
        print("[skull] Appliance is in unconfigured or AP mode — raising setup hotspot AP...")
        wifi_provisioner.start_hotspot()
        _start_setup_announcement_repeater(120.0)
        print("[skull] Remaining in setup mode loop awaiting user provisioning...")
        while not config.is_configured() and (wifi_status.get("is_ap") or not wifi_status.get("connected")):
            time.sleep(1.0)
            wifi_status = wifi_provisioner.get_status()
        print("[skull] Setup completed or network connected — proceeding to active operating mode.")
    
    try:
        boot_wav = _load_or_record_boot_wav()
        eyes.on()
        display.on()
        display.start_omnissiah_glyph(6.0)
        audio.play_wav_bytes(boot_wav, output_device=config.VOICE_OUTPUT_DEVICE)
    except Exception as e:
        print(f"[skull] Boot phrase error: {e}")
        time.sleep(0.5)
    finally:
        eyes.off()
        display.idle()
        global _startup_complete
        _startup_complete = True
        threading.Thread(target=_morning_greeting_watcher, daemon=True).start()




    skip_wake_word = False
    skip_ack = False
    _IDLE_MIN, _IDLE_MAX = 5 * 60, 10 * 60  # seconds

    is_answering_question = False

    # Morning briefing state — reset each calendar day at the top of the loop.
    # _briefing_offered:          True once we've asked "ready for briefing?" today
    # _briefing_awaiting_response: True while we're listening for the yes/no reply.
    _briefing_offered = False
    _briefing_awaiting_response = False
    _briefing_day = time.strftime("%Y-%m-%d")
    # (action, expires_at) while waiting for a spoken yes/no on update/reboot/shutdown.
    _pending_maintenance = None

    while True:
        try:
            # Back at idle — undo any music ducking from the previous interaction.
            spotify_ctrl.restore()

            if time.strftime("%Y-%m-%d") != _briefing_day:
                _briefing_day = time.strftime("%Y-%m-%d")
                _briefing_offered = False
                _briefing_awaiting_response = False

            if not skip_wake_word:
                set_speech_active(False)

            _flush_pending_bambu_notifications()

            # Immediate feedback the moment the wake word fires: dip music, ping, light
            # the eyes. Defined once per loop so every speech path — replies and the
            # unprompted observations/utterances below — can hand it to the barge-in listener.
            def on_wake():
                set_speech_active(True)
                spotify_ctrl.duck()  # dip any playing music for the whole interaction
                sfx.play_blocking("wake_ping", config.VOICE_OUTPUT_DEVICE)
                eyes.on()

            ambient_music.register_on_wake_cb(on_wake)


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
                    with _speech_lock:
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

            # ── 0a2. Offer the briefing after a proximity morning greeting ──────────
            if _morning_briefing_offer_pending.is_set():
                _morning_briefing_offer_pending.clear()
                if brain.is_daily_briefing_due() and not _briefing_offered:
                    _briefing_offered = True
                    _briefing_awaiting_response = True
                    print("[skull] Morning greeting delivered. Offering morning briefing.")
                    try:
                        set_speech_active(True)
                        offer_text = _briefing_offer_text()
                        brain.record_assistant_turn(offer_text)
                        offer_wav = tts.synthesize(offer_text)
                        eyes.on()
                        _speak_interruptible(offer_wav, on_wake)
                        skip_wake_word = True  # listen immediately for yes/no
                        skip_ack = True  # suppress the normal wake ack for this response
                    except Exception as e:
                        print(f"[skull] Briefing offer failed: {e}")
                        _briefing_awaiting_response = False
                        set_speech_active(False)
                    continue

            # ── 0a3. Play a background hymn snippet queued by ambient_music ──────────
            _snippet = ambient_music.take_pending_snippet()
            if _snippet and not quiet.is_silent() and not spotify_ctrl.is_playing():
                try:
                    eyes.on()
                    display.on()
                    if _speak_interruptible(_snippet, on_wake):
                        skip_wake_word = True
                except Exception as e:
                    print(f"[skull] Ambient hymn playback error: {e}")
                    eyes.off()
                    display.idle()
                continue

            # ── 0b. Speak any pending camera observations ──────────────────────────
            observation = camera.get_observation()
            if observation and quiet.is_silent():
                # Silent mode: drain the observation so it doesn't burst out later, but stay quiet.
                observation = None
            if observation:
                try:
                    spotify_ctrl.duck()
                    eyes.on()
                    obs_wav = tts.synthesize(observation)
                    # Barge-in: let the user cut in with the wake word mid-observation.
                    if _speak_interruptible(obs_wav, on_wake):
                        skip_wake_word = True
                except Exception as e:
                    print(f"[camera] Camera observation error: {e}")
                    eyes.off()
                    display.idle()
                continue

            # Check for web command
            from core import web
            web_item = web.get_queued_command()
            web_wake = web.pop_wake_request()

            run_brain = False
            if web_item:
                user_text, speaker_name = web_item
                if not speaker_name:
                    speaker_name = config._OWNER_PROFILE.get("name", "User")
                run_brain = True
                skip_ack = True
                play_ack_sound = False
                is_answering_question = False
                print(f"[skull] Processing web input for {speaker_name}...")
            elif web_wake:
                skip_wake_word = True

            # ── 1. Wait for wake word (skip after a barge-in interruption) ────────
            if not run_brain:
                if skip_wake_word:
                    skip_wake_word = False
                    on_wake()
                    if skip_ack:
                        is_answering_question = True
                        skip_ack = False
                        _barge_wav = None
                        play_ack_sound = False
                    else:
                        is_answering_question = False
                        if config.PERSONALITY.get("eye_animation") == "dog":
                            ack = random.choice([
                                "Woof?",
                                "Bark!",
                                "Ready to play!",
                                "I'm here!",
                                "What is it, buddy?",
                                "Did someone say Jax?",
                            ])
                        else:
                            ack = random.choice([
                                "Ah, yes?",
                                "Speak.",
                                "Yes?",
                                "Proceed.",
                                "Command me.",
                                "Why must you interrupt me?",
                                f"Again you interrupt {config.SKULL_NAME}?",
                                "This had better be important.",
                                "Insufferable. What is it?",
                            ])
                        _barge_wav = None
                        try:
                            _barge_wav = tts.synthesize(ack)
                        except Exception:
                            pass
                        play_ack_sound = True
                else:
                    is_answering_question = False
                    play_ack_sound = True
                    _idle_cancel = threading.Event()
                    _idle_fired = threading.Event()
                    _due_reminders: list = []

                    def _idle_and_reminder_watcher():
                        delay = random.uniform(_IDLE_MIN, _IDLE_MAX)
                        t_end = time.time() + delay
                        while not _idle_cancel.is_set():
                            now = time.time()
                            if now >= t_end:
                                _idle_fired.set()
                                _idle_cancel.set()
                                return
                            due = reminders.get_due()
                            if due:
                                _due_reminders.extend(due)
                                _idle_cancel.set()
                                return
                            if temperature.has_pending():
                                _idle_cancel.set()
                                return
                            _idle_cancel.wait(timeout=min(2.0, max(0.1, t_end - now)))

                    run_background_task(_idle_and_reminder_watcher)
                
                    # Register cancel event with web server
                    web.register_cancel_event(_idle_cancel)
                
                    detected = wake_word.wait_for_wake_word(on_detected=on_wake, cancel=_idle_cancel)
                    _idle_cancel.set()  # stop background threads if wake word fired first
                
                    # Unregister cancel event
                    web.register_cancel_event(None)

                    # Check if a web command came in during the wait
                    web_item = web.get_queued_command()
                    if not detected and web_item:
                        user_text, speaker_name = web_item
                        run_brain = True
                        skip_ack = True
                        play_ack_sound = False
                        is_answering_question = False
                    elif not detected and web.pop_wake_request():
                        skip_wake_word = True
                        continue
                    elif not detected and _due_reminders:
                        for _rem in _due_reminders:
                            print(f"[skull] Reminder firing: {_rem['message']}")
                            try:
                                spotify_ctrl.duck()  # restored at the loop top after the `continue` below
                                with _speech_lock:
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

                    elif not detected and _idle_fired.is_set():
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

                    elif not detected and temperature.has_pending():
                        continue  # temp warning queued — spoken at the top of the loop

                    elif not detected and _morning_briefing_offer_pending.is_set():
                        continue  # briefing offer queued — spoken at the top of the loop

                    elif not detected:
                        # No wake word and no other reason to act (a listener error or a
                        # queued background task): go back to the top — never fall through
                        # to recording, which made the skull say "Yes?" unprompted.
                        continue

                    if not run_brain:
                        _barge_wav = None
                        speaker_name = None

            if not run_brain:
                # ── 2. Play wake ack, then record ────────────────────────────────────────
                # Wake phrase plays first (blocking) so the mic doesn't pick up the skull's
                # own speaker output. Recording starts after playback finishes.
                if play_ack_sound:
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

                # Answering a question allows for a longer reply window (30s max) and a more
                # patient silence threshold timeout (4.5s) so the user can dictate numbers/codes.
                rec_secs = 30 if is_answering_question else config.RECORD_SECONDS
                silence_dur = 4.5 if is_answering_question else config.SILENCE_DURATION

                def _do_record():
                    try:
                        print(f"[skull] Recording settings: max_secs={rec_secs}, silence_dur={silence_dur}")
                        _rec_pcm[0] = audio.record(
                            seconds=rec_secs,
                            device_index=config.MIC_DEVICE_INDEX,
                            silence_threshold=config.SILENCE_THRESHOLD,
                            silence_duration=silence_dur,
                        )
                    except Exception as e:
                        _rec_exc[0] = e
                    finally:
                        _rec_done.set()

                threading.Thread(target=_do_record, daemon=True).start()
                print("[skull] Recording... (speak now)")
                if not _rec_done.wait(timeout=rec_secs + 15.0):
                    # record() enforces its own hard deadline and closes its stream
                    # from its own thread; sd.stop() here never touched that stream and
                    # cross-thread PortAudio calls are what used to crash (double free).
                    # Just abandon the (daemon) recorder thread and go back to listening.
                    print("[skull] Recording hung — abandoning this recording")
                    set_speech_active(False)
                    eyes.off()
                    continue

                if _rec_exc[0] is not None:
                    err_str = str(_rec_exc[0])
                    # PaErrorCode -9985 = paDeviceUnavailable — audio device not ready yet
                    # (e.g. PipeWire startup race on boot). Back off silently rather than
                    # playing the "negative" sound and immediately retrying, which creates
                    # an audible loop every ~3 seconds until the device settles.
                    if "-9985" in err_str or "unavailable" in err_str.lower():
                        print(f"[skull] Audio device unavailable, backing off 5s...")
                        import time as _time
                        _time.sleep(5.0)
                    else:
                        print(f"[skull] Audio record error: {_rec_exc[0]}")
                        sfx.play("negative", config.VOICE_OUTPUT_DEVICE)
                    eyes.off()
                    continue

                pcm, pcm_rate = _rec_pcm[0]
                max_rms = audio.max_window_rms(pcm, pcm_rate) if pcm else 0.0
                if not pcm or max_rms < config.SILENCE_THRESHOLD:
                    print(f"[skull] No speech detected (peak RMS {max_rms:.1f} < threshold {config.SILENCE_THRESHOLD}) — acknowledging silence.")
                    eyes.off()
                    _acknowledge_silence()
                    continue

                eyes.off()

                # ── 3. Transcribe ──────────────────────────────────────────────────────
                wav = audio.pcm_to_wav_bytes(pcm, pcm_rate)
                if config.AUDIO_DEBUG:
                    pathlib.Path("/tmp/skull_debug.wav").write_bytes(wav)
                    print("[skull] DEBUG: saved recording to /tmp/skull_debug.wav — open it to hear what the mic captured")

                # Speaker ID (local, full-rate audio) runs alongside the Whisper upload,
                # which only needs 16 kHz audio (3x smaller than the mic's native rate).
                _spk_result = [None]

                def _identify_speaker():
                    try:
                        from core import speaker_id
                        _spk_result[0] = speaker_id.identify_speaker(wav)
                    except Exception as e:
                        print(f"[skull] Speaker identification error: {e}")

                _spk_thread = threading.Thread(target=_identify_speaker, daemon=True)
                _spk_thread.start()

                print("[skull] Transcribing...")
                try:
                    _stt_wav = audio.pcm_to_wav_bytes(*audio.to_speech_rate(pcm, pcm_rate))
                    user_text = transcribe.transcribe(_stt_wav)
                    _spk_thread.join(timeout=10.0)
                    speaker_name = _spk_result[0]
                except Exception as e:
                    print(f"[skull] STT error: {e}")
                    sfx.play("negative", config.VOICE_OUTPUT_DEVICE)
                    continue

                if not user_text:
                    print("[skull] No speech detected — acknowledging silence.")
                    _acknowledge_silence()
                    continue

            spk_label = speaker_name if speaker_name else "User"
            print(f"[skull] Heard ({spk_label}): {user_text}")

            _t = user_text.lower()

            # ── 3a-0. Intercept screensaver / visual emulation commands ────────────
            if "screensaver" in _t or "visual emulation" in _t:
                m = re.search(r'(?:play|run|show|start|trigger|exec|execute)?\s*([a-z0-9_]+)\s*(?:screensaver|visual emulation)', _t)
                anim_target = None
                if m:
                    anim_target = m.group(1).strip()
                if not anim_target or anim_target not in display.get_screensaver_names():
                    for s_name in display.get_screensaver_names():
                        if s_name in _t:
                            anim_target = s_name
                            break
                if anim_target:
                    print(f"[skull] Local screensaver intercept triggered: {anim_target}")
                    display.trigger_idle_animation(300.0, anim_target)
                    continue

            # ── 3a-0b. Bard's Tale autonomous play intents ─────────────────────
            if _RE_GAME_START.search(_t):
                from games.bardstale import agent as _bt_agent
                disk_dir = pathlib.Path(__file__).resolve().parent.parent / "games" / "bardstale" / "disks"
                char_disk = disk_dir / "bards_tale_character.dsk"
                if char_disk.exists():
                    selected_disk = str(char_disk)
                else:
                    disks = sorted(
                        list(disk_dir.glob("*.dsk")) + list(disk_dir.glob("*.woz"))
                        + list(disk_dir.glob("*.nib"))
                    ) if disk_dir.exists() else []
                    selected_disk = str(disks[0]) if disks else ""

                if not selected_disk:
                    _reply = ("No Bard's Tale disk image found in the data-vaults. "
                              "Place a .dsk or .woz file in games/bardstale/disks/ "
                              "and try again.")
                elif _bt_agent.is_running():
                    _reply = "The dungeon protocol is already active, my Lord."
                else:
                    _reply = ("Accessing the data-vaults of Skara Brae. "
                              "Autonomous dungeon protocol initiating now.")
                    display.start_game_display()
                    _bt_agent.start(selected_disk, _game_narrate)
                print(f"[skull] Bard's Tale start intent → {_reply}")
                try:
                    eyes.on()
                    _speak_interruptible(tts.synthesize(_reply), on_wake)
                except Exception as _ge:
                    print(f"[skull] Bard's Tale start speech error: {_ge}")
                continue

            elif _RE_GAME_STOP.search(_t):
                from games.bardstale import agent as _bt_agent
                _bt_agent.stop()
                display.stop_game_display()
                _reply = "Dungeon protocol terminated. The cogitator returns to vigil."
                print("[skull] Bard's Tale stop intent.")
                try:
                    eyes.on()
                    _speak_interruptible(tts.synthesize(_reply), on_wake)
                except Exception as _ge:
                    print(f"[skull] Bard's Tale stop speech error: {_ge}")
                continue

            # ── 3a-1. Intercept morning-briefing / briefing / update requests ───────────────
            _BRIEFING_KEYS = ("briefing", "morning update", "daily update", "morning report",
                              "daily report", "morning telemetry", "daily telemetry", "morning dispatch", "daily dispatch")
            if _briefing_awaiting_response or any(bk in _t for bk in _BRIEFING_KEYS):
                _YES = ("yes", "sure", "yeah", "yep", "yup", "ready", "affirmative",
                        "proceed", "deliver", "go ahead", "please", "of course",
                        "absolutely", "aye", "correct", "indeed", "do it", "ok", "okay",
                        "briefing", "daily briefing", "morning briefing", "morning update", "daily update",
                        "give it to me", "tell me", "update", "i am", "i'm ready", "let's hear it",
                        "go on", "hit me", "let's go", "lay it on me", "bring it", "go for it")
                _NO  = ("no", "not now", "later", "skip", "negative", "cancel",
                        "nevermind", "never mind", "pass", "maybe later", "not yet",
                        "nope", "nah", "not ready", "i'm not", "i am not", "don't", "do not")

                # Declines are checked first so "I am not ready" isn't taken as a yes.
                _declined = _briefing_awaiting_response and _said_any(_t, _NO)
                if not _declined and (_said_any(_t, _YES) or any(bk in _t for bk in _BRIEFING_KEYS)):
                    _briefing_awaiting_response = False
                    print("[skull] User confirmed/requested morning briefing/update. Generating...")
                    try:
                        briefing_text = brain.generate_daily_briefing()
                        brain.mark_daily_briefing_done()
                        web.log_vox(config.SKULL_NAME, briefing_text)
                        print(f"[skull] Daily Briefing: {briefing_text}")
                        briefing_wav = tts.synthesize(briefing_text)
                        eyes.on()
                        interrupted = _speak_interruptible(briefing_wav, on_wake)
                        if interrupted:
                            skip_wake_word = True
                    except Exception as e:
                        print(f"[skull] Briefing delivery failed: {e}")
                    finally:
                        display.stop_noosphere_scan()
                        display.stop_auspex_scan()
                    continue
                elif _declined:
                    _briefing_awaiting_response = False
                    print("[skull] User declined morning briefing. Archiving.")
                    try:
                        if config.get_personality_key() == "jax":
                            ack_text = "Okay, no problem! We can catch up later."
                        else:
                            ack_text = "Understood, master. Cogitations archived. Speak freely."
                        web.log_vox(config.SKULL_NAME, ack_text)
                        ack_wav = tts.synthesize(ack_text)
                        eyes.on()
                        _speak_interruptible(ack_wav, on_wake)
                    except Exception as e:
                        print(f"[skull] Briefing dismiss ack error: {e}")
                    continue
                else:
                    _briefing_awaiting_response = False
                    print("[skull] Briefing response unclear — falling through to brain.")

            # ── 3a. Conversation-reset request (deterministic, pre-LLM) ────────────
            # Wipes the short-term history by voice, so a poisoned/anchored conversation
            # (e.g. the model repeating an earlier wrong answer from history instead of
            # re-checking) can be recovered without SSH. Deliberately NOT an LLM tool:
            # the whole point is to recover when the model itself is misbehaving.
            _RESET_TRIGGERS = (
                "forget this conversation", "forget our conversation", "forget the conversation",
                "clear this conversation", "clear our conversation", "clear the conversation",
                "reset this conversation", "reset our conversation", "reset the conversation",
                "new conversation", "start a new conversation", "wipe this conversation",
                "erase this conversation", "purge this conversation", "forget what we",
                "forget everything we", "clear chat history", "forget our chat",
                "clear our chat", "forget our discussion", "forget this discussion",
            )
            if any(p in _t for p in _RESET_TRIGGERS):
                print("[skull] Conversation reset requested — clearing short-term history.")
                brain.reset()
                if config.get_personality_key() == "jax":
                    _ack = "Alright, I've cleared my head! What do you want to talk about now? Woof!"
                else:
                    _ack = ("As you command, master. This unit's short-term cogitation is purged — "
                            "the slate is clean. Speak anew.")
                try:
                    eyes.on()
                    if _speak_interruptible(tts.synthesize(_ack), on_wake):
                        skip_wake_word = True
                except Exception as e:
                    print(f"[skull] Reset ack error: {e}")
                    eyes.off()
                continue

            # ── 3a-2. Detect explicit local Spotify control commands ──────────────
            _STOP_MUSIC_PHRASES = (
                "stop music", "stop playing", "stop spotify", "pause music", "pause spotify",
                "turn off music", "turn off the music", "kill the music", "halt the music",
                "enough music", "silence the music", "stop the music"
            )
            _RESUME_MUSIC_PHRASES = (
                "resume music", "resume spotify", "continue music", "unpause music", "unpause spotify",
                "start music", "start playing", "play music", "play spotify", "continue playing",
                "resume", "unpause"
            )
            _SKIP_MUSIC_PHRASES = (
                "skip music", "skip song", "next song", "next track", "skip track"
            )
        
            if any(p in _t for p in _STOP_MUSIC_PHRASES) or _t.strip() in ("stop", "pause"):
                print("[skull] Local stop-music intent detected.")
                if spotify_ctrl.is_configured():
                    spotify_ctrl.pause()
            elif any(p in _t for p in _RESUME_MUSIC_PHRASES) or _t.strip() in ("resume", "unpause"):
                print("[skull] Local resume-music intent detected.")
                if spotify_ctrl.is_configured():
                    spotify_ctrl.resume()
            elif any(p in _t for p in _SKIP_MUSIC_PHRASES) or _t.strip() in ("skip", "next"):
                print("[skull] Local skip-music intent detected.")
                if spotify_ctrl.is_configured():
                    spotify_ctrl.skip()

            # ── 3a-3. Detect Spotify volume control commands ──────────────
            _VOLUME_UP_PHRASES = (
                "turn up music", "turn up the music", "make music louder", "make the music louder",
                "louder music", "louder spotify", "increase music volume", "increase spotify volume",
                "crank the music", "crank the tunes", "volume up"
            )
            _VOLUME_DOWN_PHRASES = (
                "turn down music", "turn down the music", "make music quieter", "make the music quieter",
                "quieter music", "quieter spotify", "decrease music volume", "decrease spotify volume",
                "lower music volume", "lower spotify volume", "volume down"
            )
        
            vol_handled = False
            if any(p in _t for p in _VOLUME_UP_PHRASES):
                print("[skull] Local Spotify volume up detected.")
                if spotify_ctrl.is_configured():
                    spotify_ctrl.adjust_volume(15)
                    try:
                        speech_wav = tts.synthesize("Turning the volume up.")
                        eyes.on()
                        _speak_interruptible(speech_wav, on_wake)
                    except Exception:
                        pass
                    vol_handled = True
            elif any(p in _t for p in _VOLUME_DOWN_PHRASES):
                print("[skull] Local Spotify volume down detected.")
                if spotify_ctrl.is_configured():
                    spotify_ctrl.adjust_volume(-15)
                    try:
                        speech_wav = tts.synthesize("Lowering the volume.")
                        eyes.on()
                        _speak_interruptible(speech_wav, on_wake)
                    except Exception:
                        pass
                    vol_handled = True
            else:
                # Only intercept as Spotify if 'music' or 'spotify' is explicitly mentioned
                # to avoid hijacking plain system-volume commands like "set your volume to 70%"
                m = re.search(r"(?:music|spotify)\s*volume\s*(?:to\s+)?(\d+)", _t)
                if m:
                    level = int(m.group(1))
                    if 0 <= level <= 100:
                        print(f"[skull] Local Spotify absolute volume set detected: {level}%")
                        if spotify_ctrl.is_configured():
                            spotify_ctrl.set_volume(level)
                            try:
                                speech_wav = tts.synthesize(f"Setting volume to {level} percent.")
                                eyes.on()
                                _speak_interruptible(speech_wav, on_wake)
                            except Exception:
                                pass
                            vol_handled = True
            if vol_handled:
                continue

            # ── 3a-4. Detect Instant Dice Roll commands ──────────────
            dice_handled = False
        
            # 1. Necromunda specialized dice
            m_necro = re.search(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*(firepower|injury|scatter|hit\s+location|location)\s*d(?:ice|ie)?", _t)
            if m_necro:
                count = int(m_necro.group(1)) if m_necro.group(1) else 1
                dice_type = m_necro.group(2).lower().strip()
                if "location" in dice_type:
                    dice_type = "location"
                print(f"[skull] Instant Necromunda roll detected: {count}x {dice_type}")
                res = brain._execute_tool("roll_necromunda_dice", {"count": count, "dice_type": dice_type})
                try:
                    speech_wav = tts.synthesize(res)
                    eyes.on()
                    _speak_interruptible(speech_wav, on_wake)
                except Exception:
                    pass
                dice_handled = True
            
            # 2. Standard multi-sided dice
            if not dice_handled:
                m_std = re.search(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*d\s*(\d+)(?:\s*(?:needing|target|against)\s+(\d+))?", _t)
                if m_std:
                    count = int(m_std.group(1)) if m_std.group(1) else 1
                    sides = int(m_std.group(2))
                    target = int(m_std.group(3)) if m_std.group(3) else None
                    print(f"[skull] Instant standard roll detected: {count}d{sides} (target: {target})")
                    res = brain._execute_tool("roll_standard_dice", {"count": count, "sides": sides, "target": target})
                    try:
                        speech_wav = tts.synthesize(res)
                        eyes.on()
                        _speak_interruptible(speech_wav, on_wake)
                    except Exception:
                        pass
                    dice_handled = True
                
            # ── 3a-6. Detect Personality Switch commands ──────────────
            _t_norm = _t.lower()
            _switch_to = _personality_switch_target(user_text)
            if _switch_to:
                print(f"[skull] Local personality switch to '{_switch_to}' detected.")
                msg = switch_personality(_switch_to)
                try:
                    speech_wav = tts.synthesize(msg)
                    eyes.on()
                    _speak_interruptible(speech_wav, on_wake)
                except Exception:
                    pass
                _execute_pending_system_command()
                continue

            # ── 3a-5. Detect Voice Cache Refresh and Self-Update ──────────
            # Needs both a voice word and a cache word ("clear your voice cache", "rebuild
            # the phrase library"): a bare "clear the table" used to wipe the cache and
            # re-pay ElevenLabs to re-synthesize every phrase.
            _RE_REFRESH = re.compile(r"\b(?:refresh|reload|clear|rebuild|regenerate|update|purge|reset)\s+(?:your\s+|the\s+)?"
                                     r"(?:voice|sound|phrase|response|canned|precanned|audio|speech)\s+"
                                     r"(?:cache|library|responses|phrases|sounds)\b", re.I)
        
            # ── 3a-7. Detect Display Rotation commands ──────────────
            if ("rotate" in _t_norm or "turn" in _t_norm or "adjust" in _t_norm or "tilt" in _t_norm) and ("display" in _t_norm or "screen" in _t_norm or "eye" in _t_norm):
                m = re.search(r"([+-]?\d+(?:\.\d+)?)", _t_norm)
                if m:
                    val = float(m.group(1))
                    if "counter" in _t_norm or "left" in _t_norm or "ccw" in _t_norm:
                        deg_change = -abs(val)
                    elif "clockwise" in _t_norm or "right" in _t_norm or "cw" in _t_norm:
                        deg_change = abs(val)
                    else:
                        deg_change = val
                
                    is_absolute = "to" in _t_norm and "by" not in _t_norm
                    res_msg = config.set_display_rotation(deg_change, relative=not is_absolute)
                    print(f"[skull] Local display rotation intent: {res_msg}")
                    try:
                        speech_wav = tts.synthesize(res_msg)
                        eyes.on()
                        _speak_interruptible(speech_wav, on_wake)
                    except Exception:
                        pass
                    continue

            # ── 3a-8. Detect Voice Wait Duration commands ──────────────
            if ("voice wait" in _t_norm or "silence wait" in _t_norm or "silence duration" in _t_norm or "voice duration" in _t_norm or "wait period" in _t_norm or "wait duration" in _t_norm) and ("set" in _t_norm or "change" in _t_norm or "adjust" in _t_norm or "make" in _t_norm):
                m = re.search(r"([+-]?\d+(?:\.\d+)?)", _t_norm)
                if m:
                    sec_val = float(m.group(1))
                    res_msg = config.set_silence_duration(sec_val)
                    print(f"[skull] Local voice wait duration intent: {res_msg}")
                    try:
                        speech_wav = tts.synthesize(res_msg)
                        eyes.on()
                        _speak_interruptible(speech_wav, on_wake)
                    except Exception:
                        pass
            # ── 3a-9. Detect Honorific / Title commands ──────────────
            if ("honorific" in _t_norm or "title" in _t_norm or "call me" in _t_norm or "address me" in _t_norm) and ("set" in _t_norm or "change" in _t_norm or "make" in _t_norm or "update" in _t_norm or "call" in _t_norm or "address" in _t_norm):
                m = re.search(r"(?:set|change|update|make)\s+(?:my\s+)?(?:honorific|title)\s+(?:to\s+)?([a-z0-9\s_-]+)|(?:call\s+me|address\s+me\s+as)\s+([a-z0-9\s_-]+)(?:\s+from\s+now\s+on)?", _t, re.I)
                if m:
                    new_h = (m.group(1) or m.group(2) or "").strip()
                    if new_h:
                        res_msg = config.set_honorific(new_h)
                        print(f"[skull] Local honorific intent: {res_msg}")
                        try:
                            speech_wav = tts.synthesize(res_msg)
                            eyes.on()
                            _speak_interruptible(speech_wav, on_wake)
                        except Exception:
                            pass
                        continue

            # A pending update/reboot/shutdown runs only on an explicit spoken yes.
            if _pending_maintenance is not None:
                _action, _expires = _pending_maintenance
                _pending_maintenance = None
                if time.time() <= _expires and _said_any(_t, _CONFIRM_YES) and not _said_any(_t, _CONFIRM_NO):
                    print(f"[skull] Maintenance '{_action}' confirmed.")
                    _run_maintenance(_action, on_wake)
                    continue
                print(f"[skull] Maintenance '{_action}' not confirmed — cancelled.")
                if _said_any(_t, _CONFIRM_NO):
                    try:
                        eyes.on()
                        _speak_interruptible(tts.synthesize("Understood. Standing down."), on_wake)
                    except Exception:
                        pass
                    continue
                # Anything else is treated as a new request and handled normally below.

            _maint_action = _maintenance_command(user_text)
            if _maint_action:
                print(f"[skull] Local {_maint_action} intent detected — awaiting confirmation.")
                _pending_maintenance = (_maint_action, time.time() + _MAINT_CONFIRM_SECS)
                try:
                    eyes.on()
                    _speak_interruptible(tts.synthesize(_maintenance_prompt(_maint_action)), on_wake)
                except Exception:
                    pass
                skip_wake_word = True  # listen straight away for the yes/no
                skip_ack = True
                continue

            # Voice (re-)registration, handled directly: when the voice model mistakes
            # the owner for a stranger (e.g. after a mic change), the LLM would rightly
            # refuse to let an "unknown" speaker re-register as the owner.
            _m_reg = re.search(r"\b(?:register|enrol+|record|re-?register|update|retrain)\s+(?:my\s+)?voice(?:\s+(?:print|profile|imprint))?"
                               r"(?:\s+(?:as|for)\s+(?P<name>[a-z][a-z' -]{0,30}?))?[.!?]*$", _t)
            if _m_reg:
                _reg_name = (_m_reg.group("name") or config._OWNER_PROFILE.get("name") or "Master").strip().title()
                print(f"[skull] Local voice registration intent for '{_reg_name}'.")
                try:
                    eyes.on()
                    _speak_interruptible(tts.synthesize(
                        f"Voice imprint protocol for {_reg_name}. Answer five inquiries in full sentences."), on_wake)
                    from core import speaker_id
                    _reg_result = speaker_id.register_voice(_reg_name)
                    print(f"[skull] {_reg_result}")
                    _speak_interruptible(tts.synthesize(
                        f"Voice imprint for {_reg_name} is sealed in the archives." if "complete" in _reg_result.lower()
                        else "The voice imprint rite has failed. Consult the logs."), on_wake)
                except Exception as e:
                    print(f"[skull] Voice registration error: {e}")
                continue

            # Show the web remote access code on the eye (never spoken aloud or logged).
            if re.search(r"\b(web|remote)\b.*\b(access )?(code|password|pass ?code)\b|\baccess code\b", _t):
                print("[skull] Local web-access-code intent detected — showing code on the eye.")
                try:
                    display.show_access_code(web.issue_access_code(), 60.0)
                    eyes.on()
                    _speak_interruptible(tts.synthesize(
                        "The access code is displayed on my ocular, Master." if config.PERSONALITY.get("eye_animation") != "dog"
                        else "The code is on my eye screen! Quick, copy it down!"), on_wake)
                except Exception as e:
                    print(f"[skull] Access code display error: {e}")
                continue

            if _RE_REFRESH.search(_t):
                print("[skull] Local voice cache refresh intent detected.")
                refresh_voice_cache()
                try:
                    msg = config.PERSONALITY.get("refresh_voice_message", "Purging voice cache.")
                    speech_wav = tts.synthesize(msg)
                    eyes.on()
                    _speak_interruptible(speech_wav, on_wake)
                except Exception:
                    pass
                continue

            # ── 3b. Detect explicit voice-switch requests ──────────────────────────
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
            # Acknowledge the request immediately (unless a hymn is requested, where
            # silence is preferred), then think.
            _HYMN_TRIGGERS = ("hymn", "hymnos", "sacred music", "sacred chant", "play a hymn", "play hymn", "sing a hymn")
            _is_hymn_req = any(tr in user_text.lower() for tr in _HYMN_TRIGGERS)

            if not _is_hymn_req:
                _acknowledge()

            print("[skull] Consulting the Machine God...")
            display.think()  # spin the cog while the brain cogitates
            _cancel_cog = threading.Event()
            if _is_hymn_req:
                _cancel_cog.set()  # suppress cogitation thinking phrases for hymn requests
            cog_thread = threading.Thread(target=_cogitation_loop, args=(_cancel_cog,), daemon=True)
            cog_thread.start()

            _brain_failed = False
            try:
                reply, spotify_cmds = brain.respond(user_text, speaker_name=speaker_name, on_tool_use=_announce_search)
            except Exception as e:
                print(f"[skull] Brain error: {e}")
                _brain_failed = True
            finally:
                _cancel_cog.set()
                cog_thread.join()

            if _brain_failed:
                display.idle()
                # Say something rather than going silent, so a failed turn is obvious.
                if config.PERSONALITY.get("eye_animation") == "dog":
                    _err_line = "Oops, my thoughts got all tangled! Can you ask me again?"
                else:
                    _err_line = "My cogitators falter, Master. The noosphere does not answer. Ask again."
                try:
                    eyes.on()
                    _speak_interruptible(tts.synthesize(_err_line), on_wake)
                except Exception:
                    eyes.off()
                continue

            print(f"[skull] {config.SKULL_NAME}: {reply}")

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
                            if result in ("no-device", "not-found") or result.startswith(("error", "spotify-error", "playback-error", "no-device:")):
                                if result.startswith("no-device:"):
                                    target_name = result.split(":", 1)[1]
                                    err_text = f"This unit cannot locate the requested Spotify device '{target_name}'. Ensure the device is active and online."
                                else:
                                    _error_phrases = {
                                        "no-device": "This unit cannot locate the Spotify cogitator. Ensure the application is active.",
                                        "not-found": "The requested composition could not be found in the Spotify archives.",
                                    }
                                    err_text = _error_phrases.get(result, "The Spotify cogitator has reported a malfunction.")
                                reply = err_text
                        elif cmd[0] == "pause":
                            spotify_ctrl.pause()
                        elif cmd[0] == "resume":
                            spotify_ctrl.resume()
                        elif cmd[0] == "skip":
                            spotify_ctrl.skip()
                        elif cmd[0] == "transfer":
                            device_name = cmd[1]
                            result = spotify_ctrl.transfer(device_name)
                            print(f"[spotify] Transfer result: {result}")
                    else:
                        print("[skull] Spotify command ignored — SPOTIFY_CLIENT_ID/SECRET not set in .env")
                except Exception as e:
                    print(f"[skull] Command error: {e}")

            # If play_idle_animation was called, suppress speaking response
            if "play_idle_animation" in brain.last_turn_tools():
                print("[skull] Suppressing verbal response for play_idle_animation command")
                display.idle()
                display.stop_noosphere_scan()
                display.stop_auspex_scan()
                continue
            # If switch_personality was called, suppress the LLM's hallucinated response and replace it with the farewell message.
            if _pending_system_command and _pending_system_command.startswith("switch_"):
                target = _pending_system_command.split("_")[1]
                if target == "omega7":
                    reply = "Switching over to Omega-7 now! Be good while I'm gone — I'll miss you! Woof!"
                else:
                    reply = "Transferring control to the biological canine unit Jax. The Emperor protects. Farewell."
                print(f"[skull] Overriding LLM reply with switch farewell: {reply}")

            # ── 5. Synthesize speech ───────────────────────────────────────────────
            # Pipelined: synthesize the first sentence and start speaking it while the
            # rest of the reply is synthesized in the background, so a long reply starts
            # playing after one sentence's synthesis instead of the whole reply's.
            tts_text = reply
            _first_text, _rest_text = _split_for_pipelining(tts_text)
            _rest_wav = [None]
            _rest_ready = threading.Event()
            if _rest_text:
                def _synth_rest():
                    try:
                        _rest_wav[0] = tts.synthesize(_rest_text)
                    except Exception as e:
                        print(f"[skull] TTS error on reply remainder: {e}")
                    finally:
                        _rest_ready.set()

                threading.Thread(target=_synth_rest, daemon=True).start()
            try:
                # synthesize() already falls back from ElevenLabs to local Piper on
                # quota exhaustion; reaching this except means Piper failed too, so
                # drop to the OS system voice as a last resort.
                speech_wav = tts.synthesize(_first_text)
            except Exception as e:
                print(f"[skull] TTS error: {e} — using system TTS.")
                try:
                    tts.synthesize_fallback(tts_text)
                except Exception as fe:
                    print(f"[skull] System TTS error: {fe}")
                display.idle()  # stop the thinking spin; no amplitude path ran
                display.stop_noosphere_scan()
                display.stop_auspex_scan()
                continue

            # ── 6. Play audio with barge-in (same path as idle observations) ─────────
            try:
                interrupted = _speak_interruptible(speech_wav, on_wake)
                if _rest_text and not interrupted:
                    _rest_ready.wait(timeout=30.0)
                    if _rest_wav[0]:
                        eyes.on()
                        interrupted = _speak_interruptible(_rest_wav[0], on_wake)
                clean_reply = re.sub(r"\[.*?\]", "", reply).strip()
                ends_with_question = clean_reply.endswith("?")
                has_question = config.AUTO_LISTEN_ON_QUESTION and ends_with_question
                if interrupted or has_question:
                    # Wake word already heard or question asked; go straight to recording next iteration.
                    skip_wake_word = True
                    if not interrupted and has_question:
                        print("[skull] Question detected in reply — auto-listening enabled.")
                        skip_ack = True
            finally:
                display.stop_noosphere_scan()
                display.stop_auspex_scan()

            # ── 7. Morning briefing offer (once per day, after first interaction) ───────
            # Only fires when the first turn of the day completes cleanly at idle
            # (not mid-question, not mid-barge-in, and not during active auto-listen).
            if brain.is_daily_briefing_due() and not _briefing_offered and not quiet.is_in_sleep_hours():
                if not skip_wake_word and not interrupted and not has_question:
                    _briefing_offered = True
                    _briefing_awaiting_response = True
                    print("[skull] First interaction of the day complete. Offering morning briefing.")
                    try:
                        set_speech_active(True)
                        offer_text = _briefing_offer_text()
                        brain.record_assistant_turn(offer_text)
                        offer_wav = tts.synthesize(offer_text)
                        eyes.on()
                        interrupted = _speak_interruptible(offer_wav, on_wake)
                        skip_wake_word = True  # listen immediately for yes/no
                        skip_ack = True  # suppress the normal wake ack for this response
                    except Exception as e:
                        print(f"[skull] Briefing offer failed: {e}")
                        _briefing_awaiting_response = False
                        set_speech_active(False)

            # ── 7b. Ask to confirm an update/reboot/shutdown that Claude requested ─────
            _requested = _take_maintenance_request()
            if _requested:
                _pending_maintenance = (_requested, time.time() + _MAINT_CONFIRM_SECS)
                try:
                    set_speech_active(True)
                    eyes.on()
                    _speak_interruptible(tts.synthesize(_maintenance_prompt(_requested)), on_wake)
                except Exception:
                    set_speech_active(False)
                skip_wake_word = True  # listen straight away for the yes/no
                skip_ack = True

            # ── 8. Execute pending system commands (reboot/shutdown/switch) ───────────
            _execute_pending_system_command()
        except Exception as e:
            # One bad turn must never take the whole service down: log it, reset
            # the conversational state and go back to listening.
            print(f"[skull] Unexpected error in main loop: {type(e).__name__}: {e}")
            traceback.print_exc()
            skip_wake_word = False
            skip_ack = False
            _briefing_awaiting_response = False
            _pending_maintenance = None
            try:
                set_speech_active(False)
                eyes.off()
                display.stop_noosphere_scan()
                display.stop_auspex_scan()
                display.idle()
            except Exception:
                pass
            time.sleep(1.0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Omega-7 Servo Skull")
    parser.add_argument("--premium-voice", action="store_true",
                        help="Use ElevenLabs TTS for this session (overrides .env TTS_BACKEND)")
    args = parser.parse_args()
    if args.premium_voice:
        config.TTS_BACKEND = "elevenlabs"
        print("[skull] Premium voice enabled for this session.")
    main()
