import argparse
import time
import signal
import sys
import threading
import random

from skull import config
from skull import audio, wake_word, transcribe, brain, tts, eyes, sfx, reminders, mood
from skull import spotify_ctrl, cast_audio, camera, quiet, display, temperature, candles, bambu_ctrl


def shutdown(sig=None, frame=None):
    print("\n[skull] Powering down. The Emperor protects.")
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
    "This unit is roused.",
    "At your service, my Lord.",
    "Vox-link open. Speak.",
    "The skull attends you.",
    "Command me.",
    "I hear you, my Lord.",
    "Systems attentive. Proceed.",
    "What is thy bidding?",
    "This unit stands ready.",
    "Ready to serve.",
    "You have my attention.",
    "Say the word, my Lord.",
    "The machine spirit stirs. Speak.",
    "Attending. State your need.",
    "Awakened and listening.",
    "I am summoned. What is required?",
    "Your servant awaits.",
    "Cogitators warm. Proceed.",
    "How may this unit assist?",
    "Speak, and it shall be done.",
    "This unit answers your call.",
    "Online and attentive.",
    "The Omnissiah's servant listens.",
    "Yes? This unit stands by.",
    "I attend your word.",
    "Awaiting instruction, my Lord.",
    "Roused from vigil. Command me.",
    "What service do you require?",
    "The skull turns to you.",
    "Speak your need, my Lord.",
    "This unit is at your command.",
    "Listening. Proceed when ready.",
    "Your will, my Lord?",
    "Auspex fixed upon you. Speak.",
    "Ready and awaiting your word.",
    "The vox awaits your voice.",
    "This unit heeds you.",
    "Standing ready, my Lord.",
    "Command received channel open.",
    "I am here. Speak.",
]

_COGITATION_PHRASES = [
    "Cogitating.",
    "Consulting the archives.",
    "Accessing the data-vaults.",
    "The machine spirits deliberate.",
    "Searching the cogitator.",
    "Processing.",
    "Parsing the datastreams.",
    "Querying the noosphere.",
    "Consulting the sacred protocols.",
    "Cross-referencing the lexicanum.",
    "The logic-engines turn.",
    "Sifting the memory-coils.",
    "Invoking the calculus of the Omnissiah.",
    "Communing with the machine spirit.",
    "Retrieving from deep storage.",
    "Decrypting the archive-runes.",
    "The cogitator banks whir.",
    "Aligning the data-matrices.",
    "Interrogating the datacore.",
    "Threading the logic-circuits.",
    "Consulting the Standard Template Construct.",
    "Sanctifying the calculation.",
    "The valves warm to their task.",
    "Scanning the sacred registries.",
    "Compiling the response.",
    "Weighing the variables.",
    "The data-djinn stir.",
    "Traversing the memory-stacks.",
    "Reconciling the archive fragments.",
    "The binary cant flows.",
    "Enumerating the possibilities.",
    "Consulting the codified wisdom.",
    "The thought-engines labour.",
    "Filtering the vox-static.",
    "Unspooling the data-scrolls.",
    "Correlating the auspex returns.",
    "The relays click and settle.",
    "Distilling the archive-truth.",
    "Summoning the relevant lore.",
    "The cogitation deepens.",
    "Rousing the dormant subroutines.",
    "Tracing the query through the datavaults.",
    "The machine spirit ponders.",
    "Assembling the verdict.",
    "Consulting the Rites of Recall.",
    "Marshalling the archive-daemons.",
]

# Short "stand by" lines spoken the instant Omega-7 starts a slow tool call
# (web search, news, rules lookup, Bluetooth scan) so the user gets immediate feedback.
_SEARCH_PHRASES = [
    "One moment. This unit consults the archives.",
    "Accessing the data-vaults. Stand by.",
    "Querying the noosphere. A moment, my Lord.",
    "Searching the cogitator banks.",
    "Reaching into the datastreams. Stand by.",
    "This unit interrogates the archives. A moment.",
    "Consulting distant data-shrines. Hold.",
    "Casting the query wide. One moment, my Lord.",
    "Auspex sweeping the noosphere. Stand by.",
    "Retrieving the record. A moment.",
    "Delving the deep archives. Hold, my Lord.",
    "Opening a channel to the data-vaults. Stand by.",
    "This unit seeks the answer. One moment.",
    "Trawling the memory-coils. A moment, my Lord.",
    "Dispatching the query-daemons. Stand by.",
    "Consulting the lexicanum. Hold a moment.",
    "Scanning the sacred registries. Stand by.",
    "The cogitators reach outward. One moment.",
    "Summoning the record from deep storage. Hold.",
    "This unit queries the wider web. A moment, my Lord.",
    "Threading the datastreams. Stand by.",
    "Seeking through the archive-strata. One moment.",
    "Reaching across the vox-net. Hold, my Lord.",
    "The query is dispatched. Stand by.",
    "Cross-referencing the data-shrines. A moment.",
    "Sifting the far archives. One moment, my Lord.",
    "Engaging the search-rites. Stand by.",
    "This unit consults the wider record. Hold.",
    "Combing the noosphere for your answer. A moment.",
    "Data-daemons are dispatched. Stand by, my Lord.",
    "Opening the sacred conduits. One moment.",
    "Requesting the record. Hold a moment.",
    "The auspex ranges far. Stand by.",
    "Interrogating distant cogitators. A moment, my Lord.",
    "Casting into the datavaults. Hold.",
    "This unit gathers the intelligence. One moment.",
    "Querying the archive-network. Stand by.",
    "Retrieving from the wider web. A moment, my Lord.",
    "Consulting the outer data-shrines. Hold.",
    "Search-rites underway. Stand by.",
    "Reaching for the answer. One moment, my Lord.",
    "The vox carries your query outward. Hold.",
    "Delving for the record. Stand by.",
    "Fetching the data. One moment, my Lord.",
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
    "It shall be done.",
    "As you will, my Lord.",
    "Command received.",
    "Understood. One moment.",
    "Compliance.",
    "This unit obeys.",
    "At once, my Lord.",
    "Very well. Processing.",
    "Your word is heard.",
    "Acknowledged. Working.",
    "So ordered.",
    "Attending to it now.",
    "By the Omnissiah, it shall be so.",
    "Received and understood.",
    "As directed. Stand by.",
    "This unit complies.",
    "Noted. One moment, my Lord.",
    "Affirmative.",
    "Your command is registered.",
    "Understood, my Lord. Working.",
    "It is being done.",
    "Instruction accepted.",
    "Consider it done.",
    "At your word. Processing.",
    "This unit sets to the task.",
    "Very good, my Lord.",
    "Order confirmed.",
    "As you say. One moment.",
    "The task is begun.",
    "Heard and obeyed.",
    "Processing your command.",
    "Right away, my Lord.",
    "Understood. Attending.",
    "By your command.",
    "Acknowledged, my Lord.",
    "This unit takes it in hand.",
    "So it shall be.",
    "Compliance. Working now.",
    "Your bidding is done.",
    "Understood. This unit proceeds.",
]

# Spoken when the wake word fires but no speech follows. Without this, a silent
# recording reaches Whisper, which (biased by its domain prompt) hallucinates 40k
# lore words and the brain rambles about the Mechanicum / Necromunda. Instead,
# Omega-7 simply acknowledges the silence and signals he is waiting.
_SILENCE_PHRASES = [
    "This unit awaits your command.",
    f"Silence. {config.SKULL_NAME} stands ready when you are.",
    "I am listening, my Lord. Speak when you will.",
    "The vox is open. State your need.",
    "Nothing? This unit holds its vigil, awaiting your word.",
    "No words reach this unit. I await you still.",
    "Only silence. Speak when you are ready, my Lord.",
    "The vox carries nothing. This unit waits.",
    "I hear only quiet. State your need when you will.",
    "Silence on the vox. This unit keeps its watch.",
    "Nothing spoken. I remain attentive, my Lord.",
    "The channel is open, yet empty. I await your voice.",
    "This unit detects no command. Speak when ready.",
    "Awaiting your word still, my Lord.",
    "No speech received. This unit holds ready.",
    "Quiet reigns. I stand by for your command.",
    f"{config.SKULL_NAME} waits. Speak when you are ready.",
    "The auspex hears nothing. I remain at your service.",
    "You summoned this unit, yet said nothing. I wait.",
    "Silence noted. This unit stands ready.",
    "No instruction given. I hold my vigil, my Lord.",
    "The vox is clear but silent. Speak your need.",
    "This unit listens still. Command me when ready.",
    "Nothing heard. I await your word, my Lord.",
    "Only stillness. This unit remains attentive.",
    "No voice on the channel. I stand ready.",
    "This unit waits in silence for your command.",
    "You have my attention, though no word has come.",
    "Empty vox. Speak when it pleases you, my Lord.",
    "I detect no speech. This unit holds its post.",
    "Silence answers. Yet this unit remains ready.",
    "Awaiting speech. The channel stays open, my Lord.",
    "No command discerned. I keep the vox open.",
    "This unit hears no order. I stand by.",
    "Quiet still. Speak your will when ready, my Lord.",
    "The moment passes in silence. I await you.",
    "Nothing yet. This unit remains at the ready.",
    "No words. This unit maintains its vigil.",
    "The vox waits, empty. Speak when you will.",
    "Silence, my Lord. I remain wholly at your service.",
    "This unit stands attentive, though none has spoken.",
    "I await your voice. The channel remains open.",
    "No utterance received. This unit holds ready.",
    "Still listening, my Lord. Speak when the moment comes.",
    "The vigil continues. Command me when you are ready.",
]

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
    if not config.RESET_VOICE_CACHE:
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


def refresh_voice_cache() -> str:
    import shutil
    try:
        if _VOICE_CACHE_DIR.exists():
            shutil.rmtree(_VOICE_CACHE_DIR)
        legacy = pathlib.Path(_BOOT_CACHE)
        if legacy.exists():
            legacy.unlink()
        
        threading.Thread(target=_preload_phrases, daemon=True).start()
        print("[skull] Voice cache refresh triggered.")
        return "Voice cache cleared and background synthesis initiated successfully."
    except Exception as e:
        print(f"[skull] Voice cache refresh error: {e}")
        return f"Failed to refresh voice cache: {e}"


def self_update() -> str:
    import subprocess
    import sys
    try:
        print("[skull] Initiating system self-update...")
        pull_res = subprocess.run(["git", "pull"], capture_output=True, text=True, check=True)
        print(f"[update] Git Pull Output: {pull_res.stdout}")
        
        venv_pip = pathlib.Path(sys.prefix) / "bin" / "pip"
        if venv_pip.exists():
            req_file = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"
            if req_file.exists():
                subprocess.run([str(venv_pip), "install", "-r", str(req_file)], check=True)
        
        display.start_omnissiah_glyph(6.0)
        subprocess.Popen("sleep 7 && sudo systemctl restart omega7", shell=True)
        return "System update downloaded successfully. Restarting the machine spirit now."
    except subprocess.CalledProcessError as ce:
        print(f"[skull] Update failed: {ce.stderr or ce}")
        return f"System update failed during command execution: {ce.stderr or ce}"
    except Exception as e:
        print(f"[skull] Update error: {e}")
        return f"System update encountered an error: {e}"


def reboot_system() -> str:
    import subprocess
    try:
        print("[skull] Initiating full system reboot...")
        subprocess.Popen("sleep 1 && sudo reboot", shell=True)
        return "Initiating full system reboot. Power cycles will commence."
    except Exception as e:
        print(f"[skull] Reboot error: {e}")
        return f"Failed to reboot system: {e}"


def shutdown_system() -> str:
    import subprocess
    try:
        print("[skull] Initiating full system shutdown...")
        subprocess.Popen("sleep 1 && sudo poweroff", shell=True)
        return "Initiating full system shutdown. Powering down all machine spirits."
    except Exception as e:
        print(f"[skull] Shutdown error: {e}")
        return f"Failed to shutdown system: {e}"


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


def _speak_bambu_notification(event_type: str, text: str) -> None:
    """Announce a Bambu 3D printer event verbally."""
    print(f"[skull] Bambu notification ({event_type}): {text}")
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
    if cancel.wait(timeout=8.0):
        return
    indices = list(range(len(_cogitation_wavs)))
    random.shuffle(indices)
    i = 0
    while not cancel.is_set() and _cogitation_wavs:
        wav = _cogitation_wavs[indices[i % len(indices)]]
        try:
            with _speech_lock:
                audio.play_wav_bytes(wav, output_device=config.VOICE_OUTPUT_DEVICE)
        except Exception:
            pass
        i += 1
        cancel.wait(timeout=12.0)


_BOOT_PHRASE = (
    f"{config.SKULL_NAME} online. Neural cortex active. Ready to serve the Omnissiah."
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
    while True:
        try:
            if spotify_ctrl.is_configured():
                playing = spotify_ctrl.is_playing()
                display.set_music_playing(playing)
        except Exception as e:
            print(f"[main] Spotify status check failed: {e}")
        time.sleep(4.0)


def main():
    brain.register_reload_cb(refresh_voice_cache)
    brain.register_update_cb(self_update)
    brain.register_reboot_cb(reboot_system)
    brain.register_shutdown_cb(shutdown_system)

    # Set default output volume to 50% on boot
    try:
        import sys
        import subprocess
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", "set volume output volume 50"], capture_output=True)
        else:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "50%"], capture_output=True)
        print("[skull] Boot volume initialized to 50%")
    except Exception as e:
        print(f"[skull] Failed to set boot volume: {e}")

    eyes.setup(config.LED_PIN_LEFT, config.LED_PIN_CENTER, config.LED_PIN_RIGHT)
    candles.setup(config.CANDLE_PIN)
    candles.on()  # ambient — flicker for as long as the skull is powered
    display.setup()
    display.start_omnissiah_glyph(4.0)
    display.set_mood(mood.get())
    camera.start()
    temperature.start()
    bambu_ctrl.init(_speak_bambu_notification)
    bambu_ctrl.get_monitor().start()
    threading.Thread(target=_spotify_poller_loop, daemon=True).start()
    print(f"[skull] {config.SKULL_NAME} online. Awaiting the Emperor's commands.")
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
    skip_ack = False
    _IDLE_MIN, _IDLE_MAX = 5 * 60, 10 * 60  # seconds

    is_answering_question = False

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
            if skip_ack:
                is_answering_question = True
                skip_ack = False
                _barge_wav = None
                play_ack_sound = False
            else:
                is_answering_question = False
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

        # Answering a question allows for a longer reply window (25s max) and a more
        # patient silence threshold timeout (3.0s) so the user can pause to think.
        rec_secs = 25 if is_answering_question else config.RECORD_SECONDS
        silence_dur = 3.0 if is_answering_question else config.SILENCE_DURATION

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

        _t = user_text.lower()

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
            import re
            m = re.search(r"(?:set\s+)?(?:music|spotify)?\s*volume\s*(?:to\s+)?(\d+)", _t)
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
        import re
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
                
        if dice_handled:
            continue

        # ── 3a-5. Detect Voice Cache Refresh and Self-Update ──────────
        _REFRESH_VOICE_PHRASES = (
            "refresh your voice", "refresh voice", "reload your voice", "reload voice",
            "refresh voice cache", "refresh your voice cache", "clear your voice cache",
            "update voice cache", "update your voice cache"
        )
        _SELF_UPDATE_PHRASES = (
            "self update", "system update", "update your software", "update yourself",
            "run self update", "pull updates", "update your system"
        )
        
        maintenance_handled = False
        if any(p in _t for p in _REFRESH_VOICE_PHRASES):
            print("[skull] Local voice cache refresh intent detected.")
            refresh_voice_cache()
            try:
                speech_wav = tts.synthesize("Understood. I am purging my auditory cache and initiating voice regeneration.")
                eyes.on()
                _speak_interruptible(speech_wav, on_wake)
            except Exception:
                pass
            maintenance_handled = True
        elif any(p in _t for p in _SELF_UPDATE_PHRASES):
            print("[skull] Local self-update intent detected.")
            try:
                speech_wav = tts.synthesize("Initiating system update from the git archives. I will reboot the machine spirit shortly.")
                eyes.on()
                _speak_interruptible(speech_wav, on_wake)
            except Exception:
                pass
            self_update()
            maintenance_handled = True
        elif any(p in _t for p in ("reboot", "reboot system", "reboot yourself", "restart system", "restart yourself", "reboot the system")):
            print("[skull] Local reboot intent detected.")
            try:
                speech_wav = tts.synthesize("Initiating system reboot. Power cycles will commence shortly.")
                eyes.on()
                _speak_interruptible(speech_wav, on_wake)
            except Exception:
                pass
            reboot_system()
            maintenance_handled = True
        elif any(p in _t for p in ("shutdown", "shutdown system", "power down", "power off", "turn off", "shutdown yourself")):
            print("[skull] Local shutdown intent detected.")
            try:
                speech_wav = tts.synthesize("Initiating system shutdown. Powering down all machine spirits.")
                eyes.on()
                _speak_interruptible(speech_wav, on_wake)
            except Exception:
                pass
            shutdown_system()
            maintenance_handled = True
            
        if maintenance_handled:
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
            cog_thread.join()

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

        # If play_idle_animation was called, suppress speaking response
        if "play_idle_animation" in brain.last_turn_tools():
            print("[skull] Suppressing verbal response for play_idle_animation command")
            display.idle()
            display.stop_noosphere_scan()
            display.stop_auspex_scan()
            continue

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
            display.stop_noosphere_scan()
            display.stop_auspex_scan()
            continue

        # ── 6. Play audio with barge-in (same path as idle observations) ─────────
        try:
            interrupted = _speak_interruptible(speech_wav, on_wake)
            if interrupted or "?" in reply:
                # Wake word already heard or question asked; go straight to recording next iteration.
                skip_wake_word = True
                if not interrupted and "?" in reply:
                    print("[skull] Question detected in reply — auto-listening enabled.")
                    skip_ack = True
        finally:
            display.stop_noosphere_scan()
            display.stop_auspex_scan()




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Omega-7 Servo Skull")
    parser.add_argument("--premium-voice", action="store_true",
                        help="Use ElevenLabs TTS for this session (overrides .env TTS_BACKEND)")
    args = parser.parse_args()
    if args.premium_voice:
        config.TTS_BACKEND = "elevenlabs"
        print("[skull] Premium voice enabled for this session.")
    main()
