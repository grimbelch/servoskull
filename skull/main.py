import time
import signal
import sys
import threading
import random

from skull import config
from skull import audio, wake_word, transcribe, brain, tts, eyes, candle_leds
from skull import spotify_ctrl, cast_audio, camera


def shutdown(sig=None, frame=None):
    print("\n[skull] Powering down. The Emperor protects.")
    candle_leds.cleanup()
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

_wake_wavs: list = []
_cogitation_wavs: list = []


def _preload_phrases() -> None:
    global _wake_wavs, _cogitation_wavs
    wake, cog = [], []
    for phrase in _WAKE_PHRASES:
        try:
            wake.append(tts.synthesize(phrase))
        except Exception as e:
            print(f"[skull] Wake phrase preload warning: {e}")
    for phrase in _COGITATION_PHRASES:
        try:
            cog.append(tts.synthesize(phrase))
        except Exception as e:
            print(f"[skull] Cogitation preload warning: {e}")
    # Replace atomically so the main thread always sees a complete list
    _wake_wavs = wake
    _cogitation_wavs = cog
    print(f"[skull] Phrases preloaded ({config.TTS_BACKEND})")


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
            audio.play_wav_bytes(wav, stop_event=cancel, output_device=config.AUDIO_OUTPUT_DEVICE)
        except Exception:
            pass
        i += 1
        cancel.wait(timeout=5.0)


_BOOT_PHRASE = (
    "Omega-7 online. Neural cortex active. Ready to serve the Omnissiah."
)
_BOOT_CACHE = "models/boot_phrase.wav"


def _load_or_record_boot_wav() -> bytes:
    import pathlib
    cache = pathlib.Path(_BOOT_CACHE)
    if cache.exists():
        print(f"[skull] Loading cached boot phrase from {_BOOT_CACHE}")
        return cache.read_bytes()
    print("[skull] Recording boot phrase with ElevenLabs (first run — will cache for next time)...")
    saved_backend = config.TTS_BACKEND
    config.TTS_BACKEND = "elevenlabs"
    try:
        wav = tts.synthesize(_BOOT_PHRASE)
    finally:
        config.TTS_BACKEND = saved_backend
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(wav)
    print(f"[skull] Boot phrase cached to {_BOOT_CACHE}")
    return wav


def main():
    eyes.setup(config.LED_PIN_LEFT, config.LED_PIN_CENTER, config.LED_PIN_RIGHT)
    camera.start()
    print("[skull] Omega-7 online. Awaiting the Emperor's commands.")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        mic_label = f"device {config.MIC_DEVICE_INDEX}" if config.MIC_DEVICE_INDEX >= 0 else "system default"
        out_label = f"device {config.AUDIO_OUTPUT_DEVICE}" if config.AUDIO_OUTPUT_DEVICE >= 0 else "system default"
        print(f"[skull] Mic: {mic_label}  |  Output: {out_label}")
        print(f"[skull] Available devices:\n{devices}")
    except Exception:
        pass

    # Pre-synthesize phrases in background while boot phrase is being generated
    threading.Thread(target=_preload_phrases, daemon=True).start()

    try:
        boot_wav = _load_or_record_boot_wav()
        eyes.on()
        audio.play_wav_bytes(boot_wav, output_device=config.AUDIO_OUTPUT_DEVICE)
    except Exception as e:
        print(f"[skull] Boot phrase error: {e}")
        time.sleep(0.5)
    finally:
        eyes.off()

    candle_leds.idle()

    skip_wake_word = False

    while True:
        # ── 0. Speak any pending camera observations ───────────────────────────
        observation = camera.get_observation()
        if observation:
            try:
                eyes.on()
                obs_wav = tts.synthesize(observation)
                audio.play_wav_bytes(obs_wav, output_device=config.AUDIO_OUTPUT_DEVICE)
            except Exception as e:
                print(f"[skull] Camera observation error: {e}")
            finally:
                eyes.off()
            continue

        # ── 1. Wait for wake word (skip after a barge-in interruption) ────────
        def on_wake():
            eyes.on()
            candle_leds.listen()

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
                "You dare interrupt Omega-7?",
                "This had better be important.",
                "Insufferable. What is it?",
            ])
            _barge_wav = None
            try:
                _barge_wav = tts.synthesize(ack)
            except Exception:
                pass
        else:
            wake_word.wait_for_wake_word(on_detected=on_wake)
            _barge_wav = None

        # ── 2. Play wake ack, then record ────────────────────────────────────────
        # Wake phrase plays first (blocking) so the mic doesn't pick up the skull's
        # own speaker output. Recording starts after playback finishes.
        if _barge_wav is not None:
            try:
                audio.play_wav_bytes(_barge_wav, output_device=config.AUDIO_OUTPUT_DEVICE)
            except Exception:
                pass
        elif _wake_wavs:
            try:
                audio.play_wav_bytes(
                    random.choice(_wake_wavs),
                    output_device=config.AUDIO_OUTPUT_DEVICE,
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
        _rec_done.wait()

        if _rec_exc[0] is not None:
            print(f"[skull] Audio record error: {_rec_exc[0]}")
            eyes.off()
            candle_leds.idle()
            continue

        pcm, pcm_rate = _rec_pcm[0]
        if not pcm:
            print("[skull] No speech detected.")
            eyes.off()
            candle_leds.idle()
            continue

        eyes.off()
        candle_leds.think()

        # ── 3. Transcribe ──────────────────────────────────────────────────────
        wav = audio.pcm_to_wav_bytes(pcm, pcm_rate)
        import pathlib; pathlib.Path("/tmp/skull_debug.wav").write_bytes(wav)
        print("[skull] DEBUG: saved recording to /tmp/skull_debug.wav — open it to hear what the mic captured")
        print("[skull] Transcribing...")
        try:
            user_text = transcribe.transcribe(wav)
        except Exception as e:
            print(f"[skull] STT error: {e}")
            candle_leds.idle()
            continue

        if not user_text:
            print("[skull] No speech detected.")
            candle_leds.idle()
            continue

        print(f"[skull] Heard: {user_text}")

        # ── 3b. Detect explicit voice-switch requests ──────────────────────────
        _t = user_text.lower()
        if any(p in _t for p in ("elevenlabs", "cloud voice", "premium voice", "cloud tts")):
            config.TTS_BACKEND = "elevenlabs"
            print("[skull] TTS → elevenlabs (user request)")
            threading.Thread(target=_preload_phrases, daemon=True).start()
        elif any(p in _t for p in ("piper", "local voice", "standard voice", "local tts")):
            config.TTS_BACKEND = "piper"
            print("[skull] TTS → piper (user request)")
            threading.Thread(target=_preload_phrases, daemon=True).start()

        # ── 4. Generate response ───────────────────────────────────────────────
        print("[skull] Consulting the Machine God...")
        _cancel_cog = threading.Event()
        cog_thread = threading.Thread(target=_cogitation_loop, args=(_cancel_cog,), daemon=True)
        cog_thread.start()
        try:
            reply, spotify_cmds = brain.respond(user_text)
        except Exception as e:
            print(f"[skull] Brain error: {e}")
            candle_leds.idle()
            _cancel_cog.set()
            continue
        finally:
            _cancel_cog.set()
            cog_thread.join(timeout=2.0)

        print(f"[skull] Omega-7: {reply}")

        # ── 4b. Execute commands ───────────────────────────────────────────────
        for cmd in spotify_cmds:
            try:
                if spotify_ctrl.is_configured():
                    if cmd[0] == "play":
                        device_name = cmd[2] if len(cmd) > 2 else None
                        result = spotify_ctrl.search_and_play(cmd[1], device_name=device_name)
                        print(f"[skull] Spotify: {result}")
                        if result in ("no-device", "not-found") or result.startswith(("error", "spotify-error", "playback-error")):
                            _error_phrases = {
                                "no-device": "This unit cannot locate the Spotify cogitator. Ensure the application is active.",
                                "not-found": "The requested composition could not be found in the Spotify archives.",
                            }
                            err_text = _error_phrases.get(result, "The Spotify cogitator has reported a malfunction.")
                            try:
                                audio.play_wav_bytes(tts.synthesize(err_text), output_device=config.AUDIO_OUTPUT_DEVICE)
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
            speech_wav = tts.synthesize(tts_text)
        except Exception as e:
            if "quota_exceeded" in str(e) or "quota" in str(e).lower():
                print("[skull] ElevenLabs quota exhausted — using system TTS.")
                try:
                    tts.synthesize_fallback(tts_text)
                except Exception as fe:
                    print(f"[skull] System TTS error: {fe}")
            else:
                print(f"[skull] TTS error: {e}")
            candle_leds.idle()
            continue

        # ── 6. Play audio + barge-in listener ────────────────────────────────
        candle_leds.idle()

        _stop_play = threading.Event()
        _interrupted = threading.Event()
        _cancel_listener = threading.Event()

        def _interrupt_listener():
            detected = wake_word.wait_for_wake_word(cancel=_cancel_listener)
            if detected:
                print("[skull] Interrupted — new command incoming.")
                _stop_play.set()
                _interrupted.set()
                on_wake()

        int_thread = threading.Thread(target=_interrupt_listener, daemon=True)
        int_thread.start()

        if cast_audio.is_configured():
            cast_audio.play(speech_wav, amplitude_fn_setter=lambda fn: eyes.set_amplitude(fn()))
        else:
            amp_ref = [None]
            play_done = threading.Event()

            def receive_amp(fn):
                amp_ref[0] = fn

            def eye_loop():
                time.sleep(0.05)
                while not play_done.is_set():
                    amp = amp_ref[0]() if amp_ref[0] else 0.0
                    eyes.set_amplitude(amp)
                    time.sleep(0.025)
                if not _interrupted.is_set():
                    eyes.off()

            eye_thread = threading.Thread(target=eye_loop, daemon=True)
            eye_thread.start()

            audio.play_wav_bytes(speech_wav, amplitude_cb=receive_amp, stop_event=_stop_play, output_device=config.AUDIO_OUTPUT_DEVICE)

            play_done.set()
            eye_thread.join(timeout=1.0)

        if _interrupted.is_set():
            # Wake word already heard; go straight to recording next iteration.
            skip_wake_word = True
        else:
            _cancel_listener.set()
            int_thread.join(timeout=1.0)

        candle_leds.idle()


if __name__ == "__main__":
    main()
