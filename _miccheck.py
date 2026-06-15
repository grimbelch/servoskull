"""Live mic level meter on the real PyAudio path.

Usage:
    python _miccheck.py          # monitor the DEFAULT input device
    python _miccheck.py 35       # monitor a specific PyAudio device index

Talk while it runs. Bars that jump when you speak = that device hears you.
Use that index as MIC_DEVICE_INDEX in your .env (PyAudio index, NOT sounddevice).
"""
import sys
import numpy as np
import pyaudio

pa = pyaudio.PyAudio()
host_apis = {i: pa.get_host_api_info_by_index(i)["name"] for i in range(pa.get_host_api_count())}

print("=== PyAudio input devices ===")
try:
    print(f"DEFAULT -> [{pa.get_default_input_device_info()['index']}]")
except Exception:
    pass
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d["maxInputChannels"] > 0:
        print(f"  [{i:2}] {d['name']}  ({host_apis.get(d['hostApi'],'?')})")

idx = int(sys.argv[1]) if len(sys.argv) > 1 else -1
RATE, CHUNK, SECONDS = 16000, 512, 10
kwargs = {"input_device_index": idx} if idx >= 0 else {}
label = f"index {idx}" if idx >= 0 else "DEFAULT device"

print(f"\n=== Live level meter: {label} @ 16 kHz — TALK NOW ({SECONDS}s) ===")
try:
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                     input=True, frames_per_buffer=CHUNK, **kwargs)
    peak = 0.0
    for n in range(int(RATE / CHUNK * SECONDS)):
        data = stream.read(CHUNK, exception_on_overflow=False)
        rms = float(np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)))
        peak = max(peak, rms)
        if n % 8 == 0:  # ~4 updates/sec
            bar = "#" * min(50, int(rms / 20))
            print(f"RMS {rms:6.0f} |{bar}")
    stream.stop_stream(); stream.close()
    print(f"\npeak RMS: {peak:.0f}  (need > 200 to clear SILENCE_THRESHOLD)")
    print("GOOD - this device hears you." if peak > 200 else "TOO QUIET - try another index above.")
except Exception as e:
    print(f"open/record FAILED for {label}: {e!r}")
finally:
    pa.terminate()
