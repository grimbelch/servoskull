import time
import signal
import sys
import threading
import random

from skull import config
from skull import audio, wake_word, transcribe, brain, tts, eyes, candle_leds
from skull import spotify_ctrl, cast_audio


def shutdown(sig=None, frame=None):
    print("\n[skull] Powering down. The Emperor protects.")
    candle_leds.cleanup()
    eyes.cleanup()
    audio.cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


_COGITATION_PHRASES = [
    "Cogitating.",
    "Consulting the archives.",
    "Accessing the data-vaults.",
    "The machine spirits deliberate.",
    "Searching the cogitator.",
    "Processing.",
]
_cogitation_wavs: list = []


def _preload_cogitation() -> None:
    for phrase in _COGITATION_PHRASES:
        try:
            _cogitation_wavs.append(tts.synthesize(phrase))
        except Exception as e:
            print(f"[skull] Cogitation preload warning: {e}")


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
            audio.play_wav_bytes(wav, stop_event=cancel)
        except Exception:
            pass
        i += 1
        cancel.wait(timeout=5.0)


def main():
    eyes.setup(config.LED_PIN_LEFT, config.LED_PIN_RIGHT)
    print("[skull] Omega-7 online. Awaiting the Emperor's commands.")

    # Startup: brief eye flash then settle into candlelight idle
    eyes.on()
    time.sleep(0.5)
    eyes.off()
    candle_leds.idle()

    # Pre-synthesize cogitation phrases in background so they're ready instantly
    threading.Thread(target=_preload_cogitation, daemon=True).start()

    skip_wake_word = False

    while True:
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
            try:
                audio.play_wav_bytes(tts.synthesize(ack))
            except Exception:
                pass
        else:
            wake_word.wait_for_wake_word(on_detected=on_wake)

        # ── 2. Record the question ─────────────────────────────────────────────
        print("[skull] Recording...")
        pcm = audio.record(
            seconds=config.RECORD_SECONDS,
            device_index=config.MIC_DEVICE_INDEX,
            silence_threshold=config.SILENCE_THRESHOLD,
            silence_duration=config.SILENCE_DURATION,
        )
        eyes.off()
        candle_leds.think()

        # ── 3. Transcribe ──────────────────────────────────────────────────────
        wav = audio.pcm_to_wav_bytes(pcm)
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
                if cmd[0] == "tts_backend":
                    config.TTS_BACKEND = cmd[1]
                    print(f"[skull] TTS backend switched to: {cmd[1]}")
                elif spotify_ctrl.is_configured():
                    if cmd[0] == "play":
                        result = spotify_ctrl.search_and_play(cmd[1])
                        print(f"[skull] Spotify: {result}")
                    elif cmd[0] == "pause":
                        spotify_ctrl.pause()
                    elif cmd[0] == "resume":
                        spotify_ctrl.resume()
                    elif cmd[0] == "skip":
                        spotify_ctrl.skip()
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

            audio.play_wav_bytes(speech_wav, amplitude_cb=receive_amp, stop_event=_stop_play)

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
