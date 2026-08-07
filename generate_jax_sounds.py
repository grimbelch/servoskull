import argparse
import io
import os
import pathlib
import time
import sys

# Add root dir to sys.path so we can import core
sys.path.append(str(pathlib.Path(__file__).parent.parent.parent.parent.parent / "Desktop" / "Servoskull"))

from dotenv import load_dotenv

env_path = pathlib.Path(__file__).parent.parent.parent.parent.parent / "Desktop" / "Servoskull" / ".env"
load_dotenv(dotenv_path=env_path)

SOUNDS_DIR = pathlib.Path("/Users/sean/Desktop/Servoskull/personalities/jax/sounds")

SOUNDS: list[tuple[str, str, float]] = [
    # ── Attention / wake ──────────────────────────────────────────────────────
    (
        "wake_ping",
        "A short, sharp, happy bark from a golden retriever puppy. One clean woof.",
        0.5,
    ),
    (
        "vox_crackle",
        "A soft dog panting followed by a quick sniff. Getting ready for action.",
        0.8,
    ),
    (
        "eye_on",
        "A happy dog whimpering and getting excited, tail wagging sounds.",
        0.6,
    ),
    (
        "eye_off",
        "A soft, contented dog sigh, lying down to rest.",
        0.5,
    ),
    # ── Processing / thinking ─────────────────────────────────────────────────
    (
        "cogitating",
        "A dog happily panting and sniffing around, investigating something.",
        1.5,
    ),
    (
        "data_burst",
        "Rapid excited yips and tail thumps on a wooden floor.",
        0.8,
    ),
    (
        "memory_access",
        "A dog digging in the dirt playfully, scratching at the ground.",
        0.9,
    ),
    # ── Feedback tones ────────────────────────────────────────────────────────
    (
        "affirmative",
        "Two quick, bright, happy yaps. Very positive.",
        0.5,
    ),
    (
        "negative",
        "A low, soft whine or whimper, expressing mild disappointment.",
        0.5,
    ),
    (
        "warning",
        "A deep, alert bark. A warning 'woof!'",
        0.8,
    ),
    # ── Transmission ─────────────────────────────────────────────────────────
    (
        "transmission_open",
        "A dog's collar jingling cheerfully.",
        0.5,
    ),
    (
        "transmission_close",
        "A soft dog sneeze or snort.",
        0.5,
    ),
    # ── Atmosphere / ambience ─────────────────────────────────────────────────
    (
        "power_surge",
        "Excited dog zoomies: claws scrabbling on the floor, playful growling.",
        0.8,
    ),
    (
        "warp_static",
        "A dog vigorously shaking its body and flapping its ears.",
        1.2,
    ),
    (
        "servo_whir",
        "The sound of a dog eagerly lapping up water from a bowl.",
        0.7,
    ),
    (
        "binary_prayer",
        "A dog singing or howling softly along to a tune.",
        2.0,
    ),
    # ── Boot / shutdown ───────────────────────────────────────────────────────
    (
        "skull_boot",
        "A dog waking up: a big yawn, a stretch, followed by an energetic, happy bark.",
        2.2,
    ),
    (
        "dormancy",
        "A dog curling up to sleep: circling a few times, letting out a long, heavy sigh.",
        1.5,
    ),
    # ── Action states ─────────────────────────────────────────────────────────
    (
        "scan_sweep",
        "A dog loudly sniffing in a long, continuous intake of breath, searching for a scent.",
        1.0,
    ),
    (
        "threat_detected",
        "A low, rumbling growl escalating into a sharp bark.",
        0.8,
    ),
]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true", help="Regenerate files")
    args = parser.parse_args()

    try:
        from pydub import AudioSegment
    except ImportError:
        print("ERROR: pydub is not installed.")
        return

    try:
        from core import config
        api_key = config.ELEVENLABS_API_KEY
    except Exception:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()

    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY not found")
        return

    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=api_key)

    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0
    skipped = 0

    for name, description, duration in SOUNDS:
        output_path = SOUNDS_DIR / f"{name}.wav"
        if output_path.exists() and not args.overwrite:
            print(f"  [skip]  {name}.wav")
            skipped += 1
            continue

        print(f"  [gen]   {name}.wav  ({duration}s) …")
        try:
            mp3_iter = client.text_to_sound_effects.convert(
                text=description,
                duration_seconds=duration,
                prompt_influence=0.3,
            )
            mp3_bytes = b"".join(mp3_iter)
            audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
            audio = audio.set_frame_rate(44100).set_channels(1)
            audio.export(str(output_path), format="wav")
            print(f"  [ok]    {output_path.name}  ({len(mp3_bytes) // 1024} KB)")
            generated += 1
        except Exception as exc:
            print(f"  [ERR]   {name}: {exc}")

        time.sleep(0.4)

    total = len(list(SOUNDS_DIR.glob("*.wav")))
    print(f"\nDone — generated {generated}, skipped {skipped}, total {total} WAV files in {SOUNDS_DIR}")

if __name__ == "__main__":
    main()
