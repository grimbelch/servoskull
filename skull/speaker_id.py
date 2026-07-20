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
from skull import config

# Directory setup
VOICES_DIR = pathlib.Path(config.data_path("voices"))
MODEL_PATH = VOICES_DIR / "speaker_model.pkl"

# Active GMM profiles
_speaker_models: dict[str, GaussianMixture] = {}

def load_model() -> bool:
    """Load the trained GMM models from disk. Returns True on success."""
    global _speaker_models
    if not MODEL_PATH.exists():
        _speaker_models = {}
        return False
    try:
        with MODEL_PATH.open("rb") as f:
            _speaker_models = pickle.load(f)
        print(f"[speaker_id] Loaded {len(_speaker_models)} voice profile(s): {list(_speaker_models.keys())}")
        return True
    except Exception as e:
        print(f"[speaker_id] Failed to load speaker model: {e}")
        _speaker_models = {}
        return False

def extract_mfcc(signal: np.ndarray, samplerate: int, num_cepstrals: int = 13) -> np.ndarray:
    """Compute MFCC features from a raw 1D audio signal."""
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
    z = np.zeros((pad_signal_length - signal_length))
    pad_signal = np.append(emphasized_signal, z)
    
    # Frame indices
    indices = np.tile(np.arange(0, frame_length), (num_frames, 1)) + \
              np.tile(np.arange(0, num_frames * frame_step, frame_step), (frame_length, 1)).T
    frames = pad_signal[indices.astype(np.int32, copy=False)]
    
    # Windowing (Hamming)
    frames *= np.hamming(frame_length)
    
    # FFT and Power Spectrum
    NFFT = 512
    mag_frames = np.absolute(np.fft.rfft(frames, NFFT))
    pow_frames = ((1.0 / NFFT) * ((mag_frames) ** 2))
    
    # Mel Filterbanks (limit to 8000Hz for speech range)
    nfilt = 40
    low_freq_mel = 0
    max_freq = min(samplerate / 2.0, 8000.0)
    high_freq_mel = (2595 * np.log10(1 + max_freq / 700.0))
    mel_points = np.linspace(low_freq_mel, high_freq_mel, nfilt + 2)
    hz_points = (700 * (10**(mel_points / 2595.0) - 1))
    bin = np.floor((NFFT + 1) * hz_points / samplerate)
    
    fbank = np.zeros((nfilt, int(np.floor(NFFT / 2 + 1))))
    for m in range(1, nfilt + 1):
        f_m_minus = int(bin[m - 1])
        f_m = int(bin[m])
        f_m_plus = int(bin[m + 1])
        
        # Guard against indices out of bounds
        for k in range(f_m_minus, f_m):
            if k < fbank.shape[1]:
                fbank[m - 1, k] = (k - bin[m - 1]) / (bin[m] - bin[m - 1])
        for k in range(f_m, f_m_plus):
            if k < fbank.shape[1]:
                fbank[m - 1, k] = (bin[m + 1] - k) / (bin[m + 1] - bin[m])
            
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
            pickle.dump(models, f)
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
        threshold = -45.0
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
    from skull import audio, sfx, tts
    
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
        
        # We will record 3 samples
        num_samples = 3
        for i in range(num_samples):
            # Announce sample registration
            prompt = f"Speak sample {i+1} of {num_samples} after the chime."
            try:
                prompt_wav = tts.synthesize(prompt)
                audio.play_wav_bytes(prompt_wav, output_device=config.VOICE_OUTPUT_DEVICE)
            except Exception as e:
                print(f"[speaker_id] TTS prompt error: {e}")
                
            time.sleep(0.5)
            sfx.play("wake_ping", config.VOICE_OUTPUT_DEVICE)
            time.sleep(0.2)
            
            # Record 4 seconds of speech
            try:
                pcm, rate = audio.record(4.0, silence_threshold=250, silence_duration=1.5)
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
