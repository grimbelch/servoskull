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
#   3: + background model (UBM) and a calibrated likelihood-ratio threshold
FEATURE_VERSION = 3
FEATURE_RATE = 16000  # 25 ms = 400 samples, fits the 512-point FFT

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent

# Active GMM profiles, plus the universal background model (UBM) they are scored
# against. A raw GMM log-likelihood with one enrolled speaker accepts almost any
# sound; the ratio "this speaker vs. sound in general" is what discriminates.
_speaker_models: dict[str, GaussianMixture] = {}
_ubm: GaussianMixture | None = None
_llr_threshold = 0.0
_retrain_attempted = False  # only try the one-off feature-version migration once per process

# Decision tuning. LLRs are per-frame averages of log p(speaker) - log p(background).
_MIN_SPEECH_FRAMES = 80        # 0.8 s of voiced frames needed to judge at all
_AMBIGUITY_BAND = 0.25         # below threshold but within this band = "not sure"
_CONTINUITY_SECS = 600.0       # a confident ID carries over unsure turns for 10 minutes
# Enrollment clips are recorded close to the mic, in a quiet room, in long answers.
# Real summons are shorter, further away and noisier, so they score well below what
# calibration predicts. Calibrating without allowing for that gap overfits the
# threshold to registration conditions and rejects the owner in normal use.
_CHANNEL_MISMATCH_MARGIN = 0.40
_MIN_LLR_THRESHOLD = 0.35      # never relax so far that the model accepts anything
_last_confident: tuple[str, float] | None = None

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

    global _ubm, _llr_threshold
    version = saved.get("feature_version") if isinstance(saved, dict) else None
    if version == FEATURE_VERSION and isinstance(saved.get("models"), dict):
        _speaker_models = saved["models"]
        _ubm = saved.get("ubm")
        _llr_threshold = float(saved.get("llr_threshold", 0.0))
        print(f"[speaker_id] Loaded {len(_speaker_models)} voice profile(s): {list(_speaker_models.keys())} "
              f"(LLR threshold {_llr_threshold:.2f})")
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

def extract_mfcc(signal: np.ndarray, samplerate: int, num_cepstrals: int = 13, return_energy: bool = False):
    """Compute MFCC features from a raw 1D audio signal (and optionally per-frame dB energy)."""
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
        empty = np.zeros((0, num_cepstrals))
        return (empty, np.zeros(0)) if return_energy else empty

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

    if return_energy:
        energy_db = 10 * np.log10(np.maximum(pow_frames.sum(axis=1), np.finfo(float).eps))
        return mfcc, energy_db
    return mfcc


def _voiced(mfcc: np.ndarray, energy_db: np.ndarray) -> np.ndarray:
    """Keep frames loud enough to be speech: silence and hum say nothing about who spoke."""
    if len(energy_db) == 0:
        return mfcc
    floor = max(np.percentile(energy_db, 95) - 25.0, np.percentile(energy_db, 20) + 6.0)
    return mfcc[energy_db > floor]


def _read_signal(src) -> tuple[np.ndarray, int]:
    sr, data = wavfile.read(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else str(src))
    if len(data.shape) > 1:
        data = data[:, 0]
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    return np.asarray(data, dtype=np.float32), sr


def _voiced_features(src) -> np.ndarray:
    signal, sr = _read_signal(src)
    mfcc, energy = extract_mfcc(signal, sr, return_energy=True)
    return _voiced(mfcc, energy)


def _fit_gmm(features: np.ndarray, max_components: int = 16) -> GaussianMixture:
    n_components = min(max_components, max(2, len(features) // 50))
    gmm = GaussianMixture(n_components=n_components, covariance_type="diag", max_iter=200, random_state=42)
    gmm.fit(features)
    return gmm


def _map_adapt(ubm: GaussianMixture, features: np.ndarray, relevance: float = 16.0) -> GaussianMixture:
    """Speaker model by MAP-adapting the background model's means to the speaker's
    frames (classic GMM-UBM). With only seconds of enrollment speech this generalises
    far better than a GMM trained from scratch, and scores are directly comparable
    with the background model."""
    import copy
    resp = ubm.predict_proba(features)                    # frames x components
    n_k = resp.sum(axis=0) + 1e-10
    e_k = (resp.T @ features) / n_k[:, None]
    alpha = (n_k / (n_k + relevance))[:, None]
    adapted = copy.deepcopy(ubm)
    adapted.means_ = alpha * e_k + (1.0 - alpha) * ubm.means_
    return adapted


def _background_files() -> list[pathlib.Path]:
    """Non-owner sound for the background model: the skull's own voice (training
    corpus and cached phrases) and its sound effects. It contains no other human
    speakers, so enrolling other household members still improves discrimination."""
    import random
    rng = random.Random(42)
    corpus = sorted((REPO_DIR / "voice_training" / "wavs").glob("*.wav"))
    phrases = sorted((REPO_DIR / "models" / "phrase_cache").glob("*/*.wav"))
    effects = sorted((REPO_DIR / "sounds" / "SystemSounds").glob("*.wav")) + \
        sorted((REPO_DIR / "personalities").glob("*/sounds/*.wav"))
    return (rng.sample(corpus, min(120, len(corpus))) + rng.sample(phrases, min(60, len(phrases)))
            + effects)

def train_speaker_model() -> str:
    """Train a GMM per speaker directory in VOICES_DIR, a background model, and a
    calibrated likelihood-ratio threshold."""
    global _speaker_models, _ubm, _llr_threshold
    if not VOICES_DIR.exists():
        VOICES_DIR.mkdir(parents=True, exist_ok=True)

    per_speaker: dict[str, list[np.ndarray]] = {}
    for name in sorted(os.listdir(VOICES_DIR)):
        dir_path = VOICES_DIR / name
        if not dir_path.is_dir() or name == "debug_faces":
            continue
        feats = []
        for file in sorted(os.listdir(dir_path)):
            if file.lower().endswith(".wav"):
                try:
                    f = _voiced_features(dir_path / file)
                    if len(f) > 0:
                        feats.append(f)
                except Exception as e:
                    print(f"[speaker_id] Error reading {file}: {e}")
        if feats:
            per_speaker[name] = feats
    if not per_speaker:
        return "No speaker voice directories or WAV samples found. Training aborted."

    # Background model on half the background audio; the other half calibrates.
    bg = []
    for path in _background_files():
        try:
            f = _voiced_features(path)
            if len(f) >= 20:
                bg.append(f)
        except Exception:
            continue
    ubm, held_out = None, []
    if len(bg) >= 10:
        ubm = _fit_gmm(np.vstack(bg[0::2]), max_components=32)
        held_out = bg[1::2]

    def _speaker_model(feats: list[np.ndarray]) -> GaussianMixture:
        x = np.vstack(feats)
        return _map_adapt(ubm, x) if ubm is not None else _fit_gmm(x)

    models: dict[str, GaussianMixture] = {}
    for name, feats in per_speaker.items():
        try:
            models[name] = _speaker_model(feats)
            print(f"[speaker_id] Trained voice model for {name} on {sum(len(f) for f in feats)} voiced frames.")
        except Exception as e:
            print(f"[speaker_id] Failed to train voice model for {name}: {e}")

    threshold, calib = 0.0, {}
    if ubm is not None and models:
        # Genuine scores: each enrollment file against a model trained on the others.
        genuine = []
        for name, feats in per_speaker.items():
            for i in range(len(feats)):
                rest = [f for j, f in enumerate(feats) if j != i]
                if not rest or len(feats[i]) < 20:
                    continue
                try:
                    g = _speaker_model(rest)
                    genuine.append(g.score(feats[i]) - ubm.score(feats[i]))
                except Exception:
                    continue
        impostor = [max(m.score(f) for m in models.values()) - ubm.score(f)
                    for f in held_out if len(f) >= _MIN_SPEECH_FRAMES]
        if impostor:
            worst_impostor = float(max(impostor))
            if genuine and min(genuine) > worst_impostor:
                threshold = (min(genuine) + worst_impostor) / 2
            else:
                # Overlap (or too little enrollment audio): reject all known non-owner
                # sound; unsure owner turns fall back on conversational continuity.
                threshold = worst_impostor + 0.1
            # Allow for the enrollment-vs-live channel gap, with a floor.
            threshold = max(_MIN_LLR_THRESHOLD, threshold - _CHANNEL_MISMATCH_MARGIN)
        calib = {"genuine": [round(float(g), 3) for g in genuine],
                 "impostor_max": round(float(max(impostor)), 3) if impostor else None,
                 "impostor_count": len(impostor),
                 "mismatch_margin": _CHANNEL_MISMATCH_MARGIN}
        print(f"[speaker_id] Calibration: genuine LLRs {calib['genuine']}, worst impostor "
              f"{calib['impostor_max']} over {len(impostor)} clips, "
              f"mismatch margin {_CHANNEL_MISMATCH_MARGIN:.2f} -> threshold {threshold:.2f}")
        if genuine and min(genuine) < threshold:
            print("[speaker_id] Some enrollment clips score below the threshold — re-register with "
                  "longer answers for more reliable recognition.")
    else:
        print("[speaker_id] Not enough background audio for a background model — using raw scores.")

    try:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with MODEL_PATH.open("wb") as f:
            pickle.dump({"feature_version": FEATURE_VERSION, "models": models, "ubm": ubm,
                         "llr_threshold": threshold, "calibration": calib}, f)
        _speaker_models, _ubm, _llr_threshold = models, ubm, threshold
        return f"Successfully trained voice biometrics with profiles: {list(models.keys())}"
    except Exception as e:
        return f"Failed to save voice model: {e}"


def identify_speaker(wav_bytes: bytes) -> str | None:
    """Identify the speaker of the WAV audio bytes. Returns name or None.

    Scores voiced frames as a likelihood ratio against the background model. Clear
    matches are accepted; clearly different sound is rejected; too little speech or
    a borderline score keeps the speaker confidently identified in the last
    _CONTINUITY_SECS (so "yes" mid-conversation doesn't make the skull ask who you are)."""
    global _last_confident
    if not _speaker_models:
        if not load_model():
            return None

    def _carry_over(reason: str) -> str | None:
        if _last_confident and time.time() - _last_confident[1] < _CONTINUITY_SECS:
            print(f"[speaker_id] {reason} — keeping recent speaker '{_last_confident[0]}'")
            return _last_confident[0]
        print(f"[speaker_id] {reason} — speaker unknown")
        return None

    try:
        voiced = _voiced_features(wav_bytes)
        if len(voiced) < _MIN_SPEECH_FRAMES:
            return _carry_over(f"Only {len(voiced) / 100:.1f}s of speech")

        if _ubm is None:  # no background model: legacy absolute threshold
            name, score = max(((n, float(g.score(voiced))) for n, g in _speaker_models.items()),
                              key=lambda t: t[1])
            if score < config.SPEAKER_ID_THRESHOLD:
                return None
            _last_confident = (name, time.time())
            return name

        background = float(_ubm.score(voiced))
        name, llr = max(((n, float(g.score(voiced)) - background) for n, g in _speaker_models.items()),
                        key=lambda t: t[1])
        print(f"[speaker_id] Best match '{name}' LLR {llr:.2f} (threshold {_llr_threshold:.2f})")
        if llr >= _llr_threshold:
            _last_confident = (name, time.time())
            print(f"[speaker_id] Identified speaker: {name}")
            return name
        if llr >= _llr_threshold - _AMBIGUITY_BAND:
            return _carry_over("Borderline match")
        _last_confident = None  # clearly not an enrolled voice
        return None
    except Exception as e:
        print(f"[speaker_id] Speaker identification error: {e}")
        return None

def register_voice(name: str) -> str:
    """Record eight voice samples for the given name and train the GMM classifier."""
    from core import audio, sfx, tts

    name = config.identity_name(name)
    if not name:
        return "Invalid name for voice registration: letters, digits, spaces, hyphens and apostrophes only."

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
        
        # Eight answers of up to 12 s each. The separation between the owner and a
        # stranger is limited by how much enrollment speech there is: five 8 s answers
        # yielded only ~21 s of voiced audio, too little to score the owner reliably
        # once distance and room noise are in play. Ask for roughly triple that.
        questions = [
            f"First inquiry for the archives of Mars: State thy name and thy primary biological function or profession in this sector.",
            "Second inquiry: Which machine spirit or device in thy possession requires the most frequent application of sacred oils and prayers?",
            "Third inquiry: In the name of the Omnissiah, what is thy ultimate purpose or duty?",
            "Fourth inquiry: Describe the place where thou dwellest, and what lies beyond its windows.",
            "Fifth inquiry: Recount what thou didst this day, from the moment thou awoke.",
            "Sixth inquiry: Name the campaigns and battles that have most occupied thy cogitations of late.",
            "Seventh inquiry: Describe those who share thy dwelling, and thy duties toward them.",
            "Final inquiry: Speak freely for a time on any matter thou wishest the archives to remember."
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
                pcm, rate = audio.record(12.0, silence_threshold=config.SILENCE_THRESHOLD, silence_duration=2.0)
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
