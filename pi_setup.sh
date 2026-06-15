#!/usr/bin/env bash
# Omega-7 Servo Skull — Raspberry Pi 5 setup script
# Run once after a fresh Raspberry Pi OS (64-bit) install.
# Usage: bash pi_setup.sh

set -e

echo "=== Omega-7 Pi 5 Setup ==="

# Load credentials from .env if present
ENV_FILE="$HOME/skull/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    echo "    Loaded credentials from .env"
else
    echo "    WARNING: .env not found at $ENV_FILE — Raspotify credentials will not be configured."
fi

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/5] Installing system dependencies..."
sudo apt-get update -q
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    portaudio19-dev \
    espeak \
    git \
    libatlas-base-dev \
    ffmpeg \
    python3-opencv

# ── 2. Python virtual environment ──────────────────────────────────────────
echo "[2/5] Creating Python virtual environment..."
cd "$HOME/skull"
python3 -m venv .venv
source .venv/bin/activate

# ── 3. Python dependencies ──────────────────────────────────────────────────
echo "[3/5] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 4. Piper voice model ───────────────────────────────────────────────────
echo "[4/5] Checking Piper voice model..."
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

# ── 5. Install systemd service ────────────────────────────────────────────
echo "[5/6] Installing systemd service..."
SERVICE_DST="/etc/systemd/system/omega7.service"
USER_ID=$(id -u)

sudo cp "$HOME/skull/omega7.service" "$SERVICE_DST"
sudo sed -i \
    -e "s|__USER__|$USER|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__UID__|$USER_ID|g" \
    "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable omega7.service
echo "    Omega-7 service enabled — starts automatically on every boot."
echo "    Start now: sudo systemctl start omega7"
echo "    View logs: journalctl -u omega7 -f"

# ── 6. Raspotify (local Spotify Connect daemon) ───────────────────────────
echo "[6/7] Installing Raspotify (local Spotify playback)..."
if command -v raspotify &>/dev/null || systemctl list-unit-files raspotify.service &>/dev/null 2>&1; then
    echo "    Raspotify already installed, skipping."
else
    curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
fi

RASPOTIFY_CONF="/etc/raspotify/conf"
if [ -f "$RASPOTIFY_CONF" ]; then
    # Set device name — replaces any existing (commented or not) DEVICE_NAME line
    sudo sed -i 's/^#\?DEVICE_NAME=.*/DEVICE_NAME="Omega-7"/' "$RASPOTIFY_CONF"
    # Enable high-quality bitrate
    sudo sed -i 's/^#\?BITRATE=.*/BITRATE="320"/' "$RASPOTIFY_CONF"
    echo "    Raspotify configured: device name = Omega-7, bitrate = 320kbps"

    if [ -n "$SPOTIFY_USERNAME" ] && [ -n "$SPOTIFY_PASSWORD" ]; then
        sudo sed -i "s/^#\?USERNAME=.*/USERNAME=\"$SPOTIFY_USERNAME\"/" "$RASPOTIFY_CONF"
        sudo sed -i "s/^#\?PASSWORD=.*/PASSWORD=\"$SPOTIFY_PASSWORD\"/" "$RASPOTIFY_CONF"
        echo "    Raspotify credentials set from .env"
    else
        echo "    WARNING: SPOTIFY_USERNAME / SPOTIFY_PASSWORD not found in .env"
        echo "             Add them and re-run, or set manually in $RASPOTIFY_CONF"
    fi
else
    echo "    WARNING: $RASPOTIFY_CONF not found — configure it manually."
fi

sudo systemctl enable --now raspotify
echo "    Raspotify service enabled and started."
echo "    This Pi will appear as 'Omega-7' in Spotify Connect."

# ── 7. Verify audio devices ────────────────────────────────────────────────
echo "[7/7] Checking audio devices..."
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
echo "  2. Plug in the UGREEN USB sound card and note its index above"
echo "  3. Set MIC_DEVICE_INDEX to the UGREEN input index"
echo "  4. Set AUDIO_OUTPUT_DEVICE to the UGREEN output index"
echo "  5. Add your Spotify credentials to .env:"
echo "       SPOTIFY_CLIENT_ID=..."
echo "       SPOTIFY_CLIENT_SECRET=..."
echo "     Raspotify is already named 'Omega-7' — Omega-7 will play Spotify locally."
echo "  6. Start the service: sudo systemctl start omega7"
echo "     Or run manually:   cd ~/skull && source .venv/bin/activate && python -m skull.main"
