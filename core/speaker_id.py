"""
Lightweight speaker identification module using MFCC feature extraction and GMM classifiers.
"""

from __future__ import annotations
import os
import io
import pickle
import pathlib
import time
import numpy as np
from scipy.fftpack import dct
import scipy.io.wavfile as wavfile
from sklearn.mixture import GaussianMixture
from core import config

# Directory setup
VOICES_DIR = pathlib.Path(config.data_path("voices"))
MODEL_PATH = VOICES_DIR / "speaker_model.pkl"

# Bump whenever extract_mfcc's output changes: a model trained on other features is
# meaningless, so load_model() retrains from the stored recordings instead.
#   1 (unversioned): native-rate framing, frames cropped to 512 samples at 48 kHz
#   2: resampled to 16 kHz, stride-trick framing, continuous mel filters
FEATURE_VERSION = 2
FEATURE_RATE = 16000  # 25 ms = 400 samples, fits the 512-point FFT

# Active GMM profiles
_speaker_models: dict[str, GaussianMixture] = {}
_retrain_attempted = False  # only try the one-off feature-version migration once per process

def load_model() -> bool:
    """Load the trained GMM models from disk. Returns True on success.

    A model saved with an older (or no) FEATURE_VERSION is retrained from the WAV
    recordings in VOICES_DIR, so feature changes never force a re-enrollment.
    """
    global _speaker_models, _retrain_attempted
    if not MODEL_PATH.exists():
        _speaker_models = {}
        return False
    try:
        with MODEL_PATH.open("rb") as f:
            saved = pickle.load(f)
    except Exception as e:
        print(f"[speaker_id] Failed to load speaker model: {e}")
        _speaker_models = {}
        return False

    version = saved.get("feature_version") if isinstance(saved, dict) else None
    if version == FEATURE_VERSION and isinstance(saved.get("models"), dict):
        _speaker_models = saved["models"]
        print(f"[speaker_id] Loaded {len(_speaker_models)} voice profile(s): {list(_speaker_models.keys())}")
        return True

    # Stale features (pre-versioning models are a bare {name: GMM} dict).
    _speaker_models = {}
    if _retrain_attempted:
        return False
    _retrain_attempted = True
    print(f"[speaker_id] Speaker model uses feature version {version or 1}, need {FEATURE_VERSION} — retraining from stored recordings")
    print(f"[speaker_id] {train_speaker_model()}")
    return bool(_speaker_models)

def _mel_filterbank(nfilt: int, nfft: int, samplerate: int) -> np.ndarray:
    """Triangular mel filters evaluated at each FFT bin's centre frequency.

    Using the continuous mel edges (rather than flooring them to FFT bins) keeps
    every filter non-empty: even the narrowest low filter spans ~2 bins at 16 kHz.
    """
    max_freq = min(samplerate / 2.0, 8000.0)
    mel_points = np.linspace(0.0, 2595 * np.log10(1 + max_freq / 700.0), nfilt + 2)
    hz_points = 700 * (10 ** (mel_points / 2595.0) - 1)
    bin_hz = np.fft.rfftfreq(nfft, 1.0 / samplerate)
    lower, centre, upper = hz_points[:-2, None], hz_points[1:-1, None], hz_points[2:, None]
    rising = (bin_hz - lower) / (centre - lower)
    falling = (upper - bin_hz) / (upper - centre)
    return np.maximum(0.0, np.minimum(rising, falling))

_fbank_cache: dict[tuple, np.ndarray] = {}

def extract_mfcc(signal: np.ndarray, samplerate: int, num_cepstrals: int = 13) -> np.ndarray:
    """Compute MFCC features from a raw 1D audio signal."""
    # Resample to 16 kHz so a 25 ms frame (400 samples) fits the 512-point FFT
    # whatever the mic's native rate (at 48 kHz frames were cropped to 512 of 1200).
    if samplerate != FEATURE_RATE:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(FEATURE_RATE, int(samplerate))
        signal = resample_poly(signal, FEATURE_RATE // g, int(samplerate) // g)
        samplerate = FEATURE_RATE
    signal = np.asarray(signal, dtype=np.float32)
    if signal.size == 0:
        return np.zeros((0, num_cepstrals))

    # Pre-emphasis
    pre_emphasis = 0.97
    emphasized_signal = np.append(signal[0], signal[1:] - pre_emphasis * signal[:-1])
    
    # Framing
    frame_size = 0.025 # 25ms
    frame_stride = 0.01 # 10ms overlap
    frame_length, frame_step = frame_size * samplerate, frame_stride * samplerate
    signal_length = len(emphasized_signal)
    frame_length = int(round(frame_length))
    frame_step = int(round(frame_step))
    
    # Ensure signal is long enough
    if signal_length <= frame_length:
        num_frames = 1
    else:
        num_frames = int(np.ceil(float(np.abs(signal_length - frame_length)) / frame_step))
    
    # Padding
    pad_signal_length = num_frames * frame_step + frame_length
    z = np.zeros((pad_signal_length - signal_length), dtype=np.float32)
    pad_signal = np.append(emphasized_signal, z)
    
    # Overlapping frames as a strided view (no index matrix); windowing makes the one copy
    frames = np.lib.stride_tricks.sliding_window_view(pad_signal, frame_length)[::frame_step][:num_frames]
    
    # Windowing (Hamming)
    frames = frames * np.hamming(frame_length).astype(np.float32)
    
    # FFT and Power Spectrum
    NFFT = 512
    mag_frames = np.absolute(np.fft.rfft(frames, NFFT))
    pow_frames = ((1.0 / NFFT) * ((mag_frames) ** 2))
    
    # Mel Filterbanks (limit to 8000Hz for speech range)
    nfilt = 40
    key = (nfilt, NFFT, samplerate)
    fbank = _fbank_cache.get(key)
    if fbank is None:
        fbank = _fbank_cache[key] = _mel_filterbank(nfilt, NFFT, samplerate)
            
    filter_banks = np.dot(pow_frames, fbank.T)
    filter_banks = np.where(filter_banks == 0, np.finfo(float).eps, filter_banks)
    filter_banks = 20 * np.log10(filter_banks) # dB
    
    # DCT to get MFCC
    mfcc = dct(filter_banks, type=2, axis=1, norm='ortho')[:, 1 : (num_cepstrals + 1)]
    
    # Mean normalization
    mfcc -= (np.mean(mfcc, axis=0) + 1e-8)
    
    return mfcc

def train_speaker_model() -> str:
    """Train GMM models for each speaker directory in VOICES_DIR."""
    global _speaker_models
    if not VOICES_DIR.exists():
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        
    models: dict[str, GaussianMixture] = {}
    
    for name in sorted(os.listdir(VOICES_DIR)):
        dir_path = VOICES_DIR / name
        if not dir_path.is_dir() or name == "debug_faces":
            continue
            
        features_list = []
        for file in os.listdir(dir_path):
            if file.lower().endswith(".wav"):
                try:
                    sr, data = wavfile.read(str(dir_path / file))
                    # Handle stereo
                    if len(data.shape) > 1:
                        data = data[:, 0]
                    # Normalize
                    signal = data.astype(np.float32) / 32768.0
                    mfccs = extract_mfcc(signal, sr)
                    if len(mfccs) > 0:
                        features_list.append(mfccs)
                except Exception as e:
                    print(f"[speaker_id] Error reading {file}: {e}")
                    
        if features_list:
            all_features = np.vstack(features_list)
            # Train GMM. Adjust components based on feature count
            n_components = min(16, max(2, len(all_features) // 50))
            gmm = GaussianMixture(n_components=n_components, covariance_type='diag', max_iter=200, random_state=42)
            try:
                gmm.fit(all_features)
                models[name] = gmm
                print(f"[speaker_id] Trained GMM for {name} with {n_components} components on {len(all_features)} frames.")
            except Exception as e:
                print(f"[speaker_id] Failed to train GMM for {name}: {e}")
                
    if not models:
        return "No speaker voice directories or WAV samples found. Training aborted."
        
    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MODEL_PATH.open("wb") as f:
            pickle.dump({"feature_version": FEATURE_VERSION, "models": models}, f)
        _speaker_models = models
        return f"Successfully trained voice biometrics with profiles: {list(models.keys())}"
    except Exception as e:
        return f"Failed to save voice model: {e}"

def identify_speaker(wav_bytes: bytes) -> str | None:
    """Identify the speaker of the WAV audio bytes. Returns name or None."""
    global _speaker_models
    if not _speaker_models:
        if not load_model():
            return None
            
    try:
        sr, data = wavfile.read(io.BytesIO(wav_bytes))
        if len(data.shape) > 1:
            data = data[:, 0]
        signal = data.astype(np.float32) / 32768.0
        mfccs = extract_mfcc(signal, sr)
        if len(mfccs) == 0:
            return None
            
        best_name = None
        best_score = -np.inf
        
        for name, gmm in _speaker_models.items():
            score = float(gmm.score(mfccs))
            print(f"[speaker_id] Speaker score for '{name}': {score:.3f}")
            if score > best_score:
                best_score = score
                best_name = name
                
        # Threshold to reject background noise / untrained voices
        threshold = config.SPEAKER_ID_THRESHOLD
        if best_score < threshold:
            print(f"[speaker_id] Best match '{best_name}' score {best_score:.3f} below threshold {threshold}")
            return None
            
        print(f"[speaker_id] Identified speaker: {best_name} (score {best_score:.3f})")
        return best_name
    except Exception as e:
        print(f"[speaker_id] Speaker identification error: {e}")
        return None

def register_voice(name: str) -> str:
    """Record 3 voice samples for the given name and train the GMM classifier."""
    from core import audio, sfx, tts
    
    # Suspend background thinking phrases so they don't play during recording
    config.COGITATION_SUSPENDED = True
    try:
        # Create target directory
        target_dir = VOICES_DIR / name
        if target_dir.exists():
            import shutil
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[speaker_id] Starting voice registration for {name}")
        
        questions = [
            f"First inquiry for the archives of Mars: State thy name and thy primary biological function or profession in this sector.",
            "Second inquiry: Which machine spirit or device in thy possession requires the most frequent application of sacred oils and prayers?",
            "Third inquiry: In the name of the Omnissiah, what is thy ultimate purpose or duty?"
        ]
        
        for i, q in enumerate(questions):
            try:
                prompt_wav = tts.synthesize(q)
                audio.play_wav_bytes(prompt_wav, output_device=config.VOICE_OUTPUT_DEVICE)
            except Exception as e:
                print(f"[speaker_id] TTS prompt error: {e}")
                
            time.sleep(0.5)
            sfx.play("wake_ping", config.VOICE_OUTPUT_DEVICE)
            time.sleep(0.2)
            
            # Record up to 6.0 seconds, stopping early on silence
            try:
                pcm, rate = audio.record(6.0, silence_threshold=250, silence_duration=1.5)
                wav_bytes = audio.pcm_to_wav_bytes(pcm, rate)
                # Save WAV
                wav_path = target_dir / f"sample_{i}_{int(time.time())}.wav"
                wav_path.write_bytes(wav_bytes)
                print(f"[speaker_id] Saved sample {i+1}")
            except Exception as e:
                return f"Voice registration failed during recording of sample {i+1}: {e}"
                
            # Short break
            time.sleep(1.0)
            
        # Play completion sound
        sfx.play("positive", config.VOICE_OUTPUT_DEVICE)
        
        # Trigger GMM training
        train_result = train_speaker_model()
        return f"Voice registration complete for {name}. {train_result}"
    finally:
        config.COGITATION_SUSPENDED = False

# Load model on import
load_model()
