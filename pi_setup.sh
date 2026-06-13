#!/usr/bin/env bash
# Omega-7 Servo Skull — Raspberry Pi 5 setup script
# Run once after a fresh Raspberry Pi OS (64-bit) install.
# Usage: bash pi_setup.sh

set -e

echo "=== Omega-7 Pi 5 Setup ==="

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/6] Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    espeak \
    git \
    libatlas-base-dev \
    ffmpeg

# ── 2. ReSpeaker 2-Mic HAT drivers (HinTak fork, Pi 5 compatible) ──────────
echo "[2/6] Installing ReSpeaker HAT drivers (HinTak fork)..."

# Detect kernel version to check out the right branch
KERNEL_VER=$(uname -r | cut -d. -f1,2)
echo "    Kernel: $(uname -r)"

DRIVER_DIR="$HOME/seeed-voicecard"
if [ -d "$DRIVER_DIR" ]; then
    echo "    seeed-voicecard directory exists — pulling latest..."
    git -C "$DRIVER_DIR" pull
else
    git clone https://github.com/HinTak/seeed-voicecard "$DRIVER_DIR"
fi

cd "$DRIVER_DIR"

# HinTak branches are named after kernel versions (e.g. v6.6, v6.1).
# Try exact match first, then fall back to default branch.
BRANCH="v${KERNEL_VER}"
if git ls-remote --exit-code --heads origin "$BRANCH" > /dev/null 2>&1; then
    git checkout "$BRANCH"
    echo "    Checked out branch $BRANCH"
else
    echo "    Branch $BRANCH not found — using default branch"
fi

sudo ./install.sh
cd -

echo ""
echo "    *** ReSpeaker driver installed. A reboot is required before continuing. ***"
echo "    After rebooting, run this script again with --skip-drivers to complete setup."
echo ""

# Check if --skip-drivers was passed; if not, stop here for reboot.
if [[ "$1" != "--skip-drivers" ]]; then
    echo "Reboot now with: sudo reboot"
    echo "Then run:        bash pi_setup.sh --skip-drivers"
    exit 0
fi

# ── 3. Python virtual environment ──────────────────────────────────────────
echo "[3/6] Creating Python virtual environment..."
cd "$HOME/skull"
python3 -m venv .venv
source .venv/bin/activate

# ── 4. Python dependencies ──────────────────────────────────────────────────
echo "[4/6] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 5. Piper voice model ───────────────────────────────────────────────────
echo "[5/6] Checking Piper voice model..."
MODEL_DIR="$HOME/skull/models"
MODEL_FILE="$MODEL_DIR/en_GB-alan-medium.onnx"
MODEL_JSON="$MODEL_DIR/en_GB-alan-medium.onnx.json"

mkdir -p "$MODEL_DIR"

if [ ! -f "$MODEL_FILE" ]; then
    echo "    Downloading en_GB-alan-medium voice model (~60MB)..."
    BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium"
    curl -L -o "$MODEL_FILE" "${BASE_URL}/en_GB-alan-medium.onnx"
    curl -L -o "$MODEL_JSON" "${BASE_URL}/en_GB-alan-medium.onnx.json"
    echo "    Download complete."
else
    echo "    Voice model already present, skipping."
fi

# ── 6. Verify audio device ─────────────────────────────────────────────────
echo "[6/6] Checking audio devices..."
python3 -c "
import pyaudio
pa = pyaudio.PyAudio()
print('    Input devices (microphones):')
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d['maxInputChannels'] > 0:
        print(f'      [{i}] {d[\"name\"]}')
print('    Output devices (speakers):')
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d['maxOutputChannels'] > 0:
        print(f'      [{i}] {d[\"name\"]}')
pa.terminate()
"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your .env file into ~/skull/ (never commit it to git)"
echo "  2. Set MIC_DEVICE_INDEX to the USB microphone index shown above"
echo "  3. Set AUDIO_OUTPUT_DEVICE to the ReSpeaker output index shown above"
echo "  4. Run the skull:  cd ~/skull && source .venv/bin/activate && python -m skull.main"
