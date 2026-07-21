#!/usr/bin/env python3
import os
import shutil
import sys
import numpy as np
import scipy.io.wavfile as wavfile
import pathlib

# Ensure skull packages can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from skull import speaker_id, config

def generate_synthetic_voice(filename, fundamental_freq, duration=2.0, sr=16000):
    """Generate a synthetic harmonic voice wave and save as WAV."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Fundamental frequency + some harmonics to simulate vocal cords
    wave = np.sin(2 * np.pi * fundamental_freq * t)
    wave += 0.5 * np.sin(2 * np.pi * (fundamental_freq * 2) * t)
    wave += 0.25 * np.sin(2 * np.pi * (fundamental_freq * 3) * t)
    # Add a bit of noise
    wave += 0.05 * np.random.normal(size=len(t))
    # Normalize to 16-bit PCM range
    wave = wave / np.max(np.abs(wave))
    audio_data = (wave * 32767).astype(np.int16)
    wavfile.write(filename, sr, audio_data)

def main():
    print("Setting up synthetic voice directories...")
    speaker_a = "Speaker_A"
    speaker_b = "Speaker_B"
    
    dir_a = speaker_id.VOICES_DIR / speaker_a
    dir_b = speaker_id.VOICES_DIR / speaker_b
    
    # Cleanup any old test dirs
    for d in [dir_a, dir_b]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
        
    try:
        # 1. Generate training audio (3 samples each)
        # Speaker A: low pitch (100 Hz fundamental)
        # Speaker B: high pitch (300 Hz fundamental)
        print("Generating training WAVs...")
        for i in range(3):
            generate_synthetic_voice(str(dir_a / f"sample_{i}.wav"), 100.0)
            generate_synthetic_voice(str(dir_b / f"sample_{i}.wav"), 300.0)
            
        # 2. Train model
        print("Training speaker GMM classifier...")
        result = speaker_id.train_speaker_model()
        print(f"Train result: {result}")
        
        if not speaker_id.MODEL_PATH.exists():
            print("ERROR: speaker_model.pkl was not saved!")
            sys.exit(1)
            
        # 3. Load model
        print("Loading speaker model...")
        loaded = speaker_id.load_model()
        print(f"Loaded successfully: {loaded}")
        
        # 4. Generate test audio and identify
        print("Testing speaker identification...")
        test_file_a = "/tmp/test_speaker_a.wav"
        test_file_b = "/tmp/test_speaker_b.wav"
        
        generate_synthetic_voice(test_file_a, 100.0)
        generate_synthetic_voice(test_file_b, 300.0)
        
        # Test Speaker A
        wav_bytes_a = pathlib.Path(test_file_a).read_bytes()
        match_a = speaker_id.identify_speaker(wav_bytes_a)
        print(f"Test A (expected Speaker_A): {match_a}")
        
        # Test Speaker B
        wav_bytes_b = pathlib.Path(test_file_b).read_bytes()
        match_b = speaker_id.identify_speaker(wav_bytes_b)
        print(f"Test B (expected Speaker_B): {match_b}")
        
        # Clean up test files
        for f in [test_file_a, test_file_b]:
            if os.path.exists(f):
                os.remove(f)
                
        # Assertions
        if match_a == speaker_a and match_b == speaker_b:
            print("ALL SPEAKER IDENTIFICATION TESTS PASSED SUCCESSFULLY!")
        else:
            print(f"TEST FAILED! match_a={match_a}, match_b={match_b}")
            sys.exit(1)
            
    finally:
        # Final cleanup
        print("Cleaning up synthetic test data...")
        for d in [dir_a, dir_b]:
            if d.exists():
                shutil.rmtree(d)
        if speaker_id.MODEL_PATH.exists():
            speaker_id.MODEL_PATH.unlink()

if __name__ == "__main__":
    main()
