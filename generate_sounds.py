"""
Generate the Omega-7 sound effects library using the ElevenLabs sound generation API.
Outputs WAV files to the sounds/ directory. Safe to re-run — existing files are skipped.

Prerequisites (one-time dev setup):
    pip install pydub
    brew install ffmpeg      # macOS
    # OR: sudo apt install ffmpeg   # Linux / Pi

Usage:
    python generate_sounds.py
    python generate_sounds.py --overwrite   # regenerate all files
"""

from __future__ import annotations
import argparse
import io
import os
import pathlib
import time

from dotenv import load_dotenv

load_dotenv()

SOUNDS_DIR = pathlib.Path(__file__).parent / "sounds"

# (filename, ElevenLabs prompt, duration_seconds)
SOUNDS: list[tuple[str, str, float]] = [
    # ── Attention / wake ──────────────────────────────────────────────────────
    (
        "wake_ping",
        "A sharp, clear single metallic ping. One clean crystal chime tone, very brief.",
        0.5,
    ),
    (
        "vox_crackle",
        "Radio vox static crackle, a burst of interference noise then silence. "
        "Old military radio opening sound.",
        0.8,
    ),
    (
        "eye_on",
        "Electronic power-up rising hum, cybernetic optical sensor activating. "
        "Pitch rises smoothly.",
        0.6,
    ),
    (
        "eye_off",
        "Electronic power-down descending hum, system deactivation. "
        "Pitch falls and fades out.",
        0.5,
    ),
    # ── Processing / thinking ─────────────────────────────────────────────────
    (
        "cogitating",
        "Mechanical computing machine thinking: rhythmic digital processing beeps, "
        "rapid electronic clicks, computer working sound.",
        1.5,
    ),
    (
        "data_burst",
        "Rapid data transmission: quick bursts of electronic beeps, "
        "information transfer clicking, modem-like data sounds.",
        0.8,
    ),
    (
        "memory_access",
        "Digital archive retrieval sound: sequential access beeps, "
        "memory bank loading, old hard drive seeking clicks.",
        0.9,
    ),
    # ── Feedback tones ────────────────────────────────────────────────────────
    (
        "affirmative",
        "Clean electronic double beep, positive affirmative tone. "
        "Two short high-pitched beeps in quick succession.",
        0.4,
    ),
    (
        "negative",
        "Electronic negative buzz, harsh low error tone, denial sound. "
        "Short and final.",
        0.5,
    ),
    (
        "warning",
        "Warning klaxon: two urgent alarm blasts, danger alert pulse. "
        "Harsh and attention-grabbing.",
        0.8,
    ),
    # ── Transmission ─────────────────────────────────────────────────────────
    (
        "transmission_open",
        "Vox radio channel opening: static crackle then a steady carrier tone click. "
        "Old military radio going live.",
        0.5,
    ),
    (
        "transmission_close",
        "Vox radio channel closing: brief click and squelch. Transmission over.",
        0.3,
    ),
    # ── Atmosphere / ambience ─────────────────────────────────────────────────
    (
        "power_surge",
        "Electrical power surge: crackle, hum, and discharge. "
        "Brief burst of electrical energy.",
        0.8,
    ),
    (
        "warp_static",
        "Eerie otherworldly interference: supernatural static, warped distorted noise, "
        "unsettling electronic anomaly.",
        1.2,
    ),
    (
        "servo_whir",
        "Mechanical servo motor movement: smooth whirring sound as a motor moves, "
        "robotic joint rotating.",
        0.7,
    ),
    (
        "binary_prayer",
        "Robotic mechanicus binary chanting: brief excerpt of a machine intoning "
        "rhythmic electronic prayer sounds in binary code.",
        2.0,
    ),
    # ── Boot / shutdown ───────────────────────────────────────────────────────
    (
        "skull_boot",
        "Full electronic system initialization sequence: power-up hum, "
        "cascading boot beeps, systems coming online one by one, "
        "rising pitch culminating in a ready tone.",
        2.2,
    ),
    (
        "dormancy",
        "System entering dormancy: descending power-down tones, "
        "systems going offline sequentially, final low hum fading to silence.",
        1.5,
    ),
    # ── Action states ─────────────────────────────────────────────────────────
    (
        "scan_sweep",
        "Electronic sensor scanning sweep: a single ping that sweeps "
        "from one side to the other, like a radar or sonar pulse.",
        1.0,
    ),
    (
        "threat_detected",
        "Threat detection alert: urgent pulsing alarm, rapid warning beeps, "
        "danger incoming alert sound.",
        0.8,
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true",
                        help="Regenerate files that already exist")
    args = parser.parse_args()

    try:
        from pydub import AudioSegment
    except ImportError:
        print(
            "ERROR: pydub is not installed.\n"
            "Run:  pip install pydub\n"
            "And install ffmpeg:  brew install ffmpeg  (macOS)\n"
            "                or:  sudo apt install ffmpeg  (Linux)"
        )
        return

    try:
        from skull import config
        api_key = config.ELEVENLABS_API_KEY
    except Exception:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()

    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY not found in config / environment / .env")
        return

    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=api_key)

    SOUNDS_DIR.mkdir(exist_ok=True)
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

        time.sleep(0.4)  # gentle rate-limit courtesy

    total = len(list(SOUNDS_DIR.glob("*.wav")))
    print(f"\nDone — generated {generated}, skipped {skipped}, total {total} WAV files in sounds/")


if __name__ == "__main__":
    main()
