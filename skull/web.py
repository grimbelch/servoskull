from __future__ import annotations
import http.server
import socketserver
import threading
import json
import queue
import time
import io
import sys
import collections
from pathlib import Path
from skull import config

# Thread-safe commands queue and wake states
_command_queue = queue.Queue()
_wake_requested = False
_cancel_event = None
_cancel_lock = threading.Lock()

# Thread-safe log buffer
_log_buffer = collections.deque(maxlen=100)
_log_lock = threading.Lock()

class WebLogRedirect:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        
    def write(self, s):
        self.original_stdout.write(s)
        if s.strip():
            # Strip ANSI escape codes if any (for cleaner display)
            clean_s = s.strip()
            # Basic escape sequences stripper
            import re
            clean_s = re.sub(r'\x1b\[[0-9;]*[mK]', '', clean_s)
            with _log_lock:
                _log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {clean_s}")
                
    def flush(self):
        self.original_stdout.flush()

# Redirect stdout to capture logs
sys.stdout = WebLogRedirect(sys.stdout)

def get_logs() -> list[str]:
    with _log_lock:
        return list(_log_buffer)

def register_cancel_event(evt) -> None:
    global _cancel_event
    with _cancel_lock:
        _cancel_event = evt

def trigger_cancel() -> None:
    global _cancel_event
    with _cancel_lock:
        if _cancel_event is not None:
            _cancel_event.set()

def queue_command(text: str, speaker_name: str | None = None) -> None:
    _command_queue.put((text, speaker_name))
    trigger_cancel()

def get_queued_command() -> tuple[str, str | None] | None:
    try:
        return _command_queue.get_nowait()
    except queue.Empty:
        return None

def request_wake() -> None:
    global _wake_requested
    _wake_requested = True
    trigger_cancel()

def pop_wake_request() -> bool:
    global _wake_requested
    if _wake_requested:
        _wake_requested = False
        return True
    return False

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

class WebRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress automatic logging to console to keep main logs readable
        pass

    def _send_json(self, data: dict, status_code: int = 200) -> None:
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"[web] send_json error: {e}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        from skull import display, temperature, brain
        
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_CLIENT.encode("utf-8"))
            return
            
        elif self.path == "/api/state":
            try:
                disp_state = display.get_state()
            except Exception:
                disp_state = {}
                
            try:
                temp = temperature.get_warning() or f"{temperature.get_warning() if hasattr(temperature, 'get_warning') else 45.0}°C"
                # fallback mock temperature if needed
                if not temp:
                    temp = "42.0°C"
            except Exception:
                temp = "Unavailable"
                
            state_data = {
                "skull_name": config.SKULL_NAME,
                "display": disp_state,
                "temperature": temp,
                "active_game": brain.get_current_game() if hasattr(brain, "get_current_game") else "None",
                "screensavers": display.get_screensaver_names() if hasattr(display, "get_screensaver_names") else [],
                "logs": get_logs(),
            }
            self._send_json(state_data)
            return
            
        elif self.path == "/api/custom_image.jpg":
            img_bytes = display.get_custom_image_bytes()
            if img_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(img_bytes)))
                self.end_headers()
                self.wfile.write(img_bytes)
            else:
                self.send_response(404)
                self.end_headers()
            return
            
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/wake":
            request_wake()
            self._send_json({"status": "ok", "message": "Wake request triggered."})
            return
            
        elif self.path == "/api/command":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(post_data)
                cmd = data.get("command", "").strip()
                if cmd:
                    queue_command(cmd)
                    self._send_json({"status": "ok", "message": f"Queued command: {cmd}"})
                else:
                    self._send_json({"status": "error", "message": "Command parameter is empty."}, 400)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)
            return
            
        elif self.path == "/api/upload_audio":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                wav_bytes = self.rfile.read(content_length)
                
                if len(wav_bytes) < 100:
                    self._send_json({"status": "error", "message": "Audio file too short."}, 400)
                    return
                
                # Process audio in a separate thread so web response is fast
                def _process_web_audio(audio_data):
                    try:
                        from skull import speaker_id, transcribe
                        # 1. Identify speaker
                        speaker_name = speaker_id.identify_speaker(audio_data)
                        print(f"[web] Identified speaker from audio upload: {speaker_name}")
                        
                        # 2. Transcribe speech
                        user_text = transcribe.transcribe(audio_data)
                        print(f"[web] Transcribed audio upload: {user_text}")
                        
                        if user_text.strip():
                            queue_command(user_text, speaker_name=speaker_name)
                    except Exception as err:
                        print(f"[web] Error processing uploaded audio: {err}")
                        
                threading.Thread(target=_process_web_audio, args=(wav_bytes,), daemon=True).start()
                self._send_json({"status": "ok", "message": "Audio received and processing initiated."})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        self.send_response(404)
        self.end_headers()

def _run_server(port: int) -> None:
    try:
        # Bind to 0.0.0.0 so it is accessible via Tailscale IP or local network IP
        server = ThreadingHTTPServer(("0.0.0.0", port), WebRequestHandler)
        print(f"[web] Servoskull Web Remote Server running on port {port} (accessible via local/Tailscale IP)")
        server.serve_forever()
    except Exception as e:
        print(f"[web] Server failed to start: {e}")

def start() -> None:
    """Start the HTTP server on a background thread."""
    if not getattr(config, "WEB_SERVER_ENABLED", True):
        return
    port = getattr(config, "WEB_SERVER_PORT", 8080)
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

# Embedded Single-File HTML / CSS / JS Client
HTML_CLIENT = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Omega-7 Web Remote & Emulator</title>
    <style>
        :root {
            --bg-color: #0b0b0c;
            --card-color: #141416;
            --border-color: #27272a;
            --red-glow: #ff2a2a;
            --red-dim: #7f1212;
            --brass: #d4af37;
            --brass-dim: #8b6e15;
            --text-color: #e4e4e7;
            --text-muted: #a1a1aa;
            --green-glow: #10b981;
            --cyan-glow: #06b6d4;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: 'Share Tech Mono', 'JetBrains Mono', Courier, monospace;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 900px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            background-color: var(--card-color);
            border: 2px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7), 0 0 20px rgba(212, 175, 55, 0.05);
        }

        @media (max-width: 768px) {
            .container {
                grid-template-columns: 1fr;
            }
            body {
                padding: 10px;
            }
        }

        .header {
            grid-column: 1 / -1;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 12px;
            margin-bottom: 10px;
        }

        .header h1 {
            color: var(--red-glow);
            font-size: 24px;
            letter-spacing: 2px;
            text-shadow: 0 0 10px rgba(255, 42, 42, 0.5);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .header h1 span {
            color: var(--brass);
            font-size: 14px;
        }

        .telemetry {
            display: flex;
            gap: 15px;
            font-size: 14px;
        }

        .telemetry-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 4px 8px;
        }

        .telemetry-label {
            color: var(--text-muted);
        }

        .telemetry-value {
            color: var(--brass);
            font-weight: bold;
        }

        /* Ocular Display Left Pane */
        .emulator-pane {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 20px;
            padding: 10px;
            border-right: 1px solid var(--border-color);
        }

        @media (max-width: 768px) {
            .emulator-pane {
                border-right: none;
                border-bottom: 1px solid var(--border-color);
                padding-bottom: 24px;
            }
        }

        /* Circular Eye */
        .ocular-ring {
            width: 260px;
            height: 260px;
            border-radius: 50%;
            border: 6px solid var(--brass);
            position: relative;
            background-color: #000;
            box-shadow: 0 0 25px var(--red-dim), inset 0 0 20px rgba(0, 0, 0, 0.9);
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
            transition: box-shadow 0.1s ease;
        }

        .ocular-canvas {
            width: 240px;
            height: 240px;
            border-radius: 50%;
            display: block;
            image-rendering: pixelated;
        }

        .custom-image-display {
            position: absolute;
            width: 240px;
            height: 240px;
            border-radius: 50%;
            object-fit: cover;
            display: none;
        }

        .led-glow {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: var(--red-glow);
            box-shadow: 0 0 10px var(--red-glow);
            position: absolute;
            top: 15px;
            right: 15px;
            transition: all 0.1s ease;
        }

        .status-badge {
            background-color: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 16px;
            text-align: center;
            width: 80%;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        /* Control Panel Right Pane */
        .control-pane {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        /* Chat log / responses */
        .chat-container {
            flex-grow: 1;
            height: 180px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background: rgba(0, 0, 0, 0.2);
            padding: 12px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-size: 14px;
        }

        .chat-bubble {
            max-width: 90%;
            padding: 6px 10px;
            border-radius: 4px;
            line-height: 1.4;
        }

        .chat-user {
            align-self: flex-end;
            background-color: rgba(212, 175, 55, 0.1);
            border: 1px solid var(--brass-dim);
            color: var(--brass);
        }

        .chat-skull {
            align-self: flex-start;
            background-color: rgba(255, 42, 42, 0.05);
            border: 1px solid var(--red-dim);
            color: var(--red-glow);
        }

        .input-bar {
            display: flex;
            gap: 8px;
        }

        .input-bar input {
            flex-grow: 1;
            background-color: rgba(0,0,0,0.5);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            padding: 10px;
            color: var(--text-color);
            font-family: inherit;
            font-size: 15px;
        }

        .input-bar input:focus {
            outline: none;
            border-color: var(--brass);
        }

        button {
            background-color: var(--brass-dim);
            border: 1px solid var(--brass);
            color: var(--text-color);
            padding: 10px 16px;
            border-radius: 4px;
            font-family: inherit;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s ease;
        }

        button:hover {
            background-color: var(--brass);
            color: #000;
            box-shadow: 0 0 10px rgba(212, 175, 55, 0.4);
        }

        .action-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }

        button.wake-btn {
            background-color: var(--red-dim);
            border-color: var(--red-glow);
        }

        button.wake-btn:hover {
            background-color: var(--red-glow);
            color: #000;
            box-shadow: 0 0 10px rgba(255, 42, 42, 0.4);
        }

        button.mic-btn {
            background-color: #27272a;
            border-color: #3f3f46;
        }
        
        button.mic-btn.recording {
            background-color: var(--red-glow);
            color: #000;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 42, 42, 0.7); }
            70% { box-shadow: 0 0 0 8px rgba(255, 42, 42, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 42, 42, 0); }
        }

        /* Logs Console Panel */
        .console-container {
            grid-column: 1 / -1;
            border-top: 2px solid var(--border-color);
            margin-top: 10px;
            padding-top: 15px;
        }

        .console-title {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 1px;
            display: flex;
            justify-content: space-between;
        }

        .console-box {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            height: 120px;
            padding: 8px 12px;
            overflow-y: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 11px;
            color: var(--text-muted);
            line-height: 1.5;
        }

        .console-line {
            white-space: pre-wrap;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            padding: 2px 0;
        }

        /* Dropdowns for Quick Settings */
        .controls-row {
            display: flex;
            gap: 10px;
            font-size: 14px;
        }

        .controls-row select {
            flex-grow: 1;
            background-color: rgba(0,0,0,0.5);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 8px;
            border-radius: 4px;
            font-family: inherit;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>OMEGA-7 <span>SERVO SKULL REMOTE</span></h1>
            <div class="telemetry">
                <div class="telemetry-item">
                    <span class="telemetry-label">TEMP:</span>
                    <span id="temp-val" class="telemetry-value">--.-°C</span>
                </div>
                <div class="telemetry-item">
                    <span class="telemetry-label">GAME:</span>
                    <span id="game-val" class="telemetry-value">NONE</span>
                </div>
            </div>
        </div>

        <!-- Left Pane: Ocular Panel -->
        <div class="emulator-pane">
            <div class="ocular-ring" id="eye-ring">
                <canvas class="ocular-canvas" id="eye-canvas" width="240" height="240"></canvas>
                <img class="custom-image-display" id="custom-image" src="" alt="Custom Image View">
                <div class="led-glow" id="eye-led"></div>
            </div>
            <div class="status-badge" id="status-badge">● IDLE</div>
        </div>

        <!-- Right Pane: Control Room -->
        <div class="control-pane">
            <div class="chat-container" id="chat-container">
                <div class="chat-bubble chat-skull">System initialized. Awaiting commands, master.</div>
            </div>
            
            <div class="controls-row">
                <select id="screensaver-select">
                    <option value="">-- Trigger Screensaver --</option>
                </select>
                <button onclick="playScreensaver()">PLAY</button>
            </div>

            <div class="action-buttons">
                <button class="wake-btn" onclick="triggerWake()">VERBAL WAKE</button>
                <button class="mic-btn" id="mic-btn" onmousedown="startMicRecording()" onmouseup="stopMicRecording()" ontouchstart="startMicRecording()" ontouchend="stopMicRecording()">HOLD TO SPEAK</button>
            </div>

            <div class="input-bar">
                <input type="text" id="command-input" placeholder="Transmit command text (e.g. 'roll standard d20')..." onkeydown="if(event.key === 'Enter') sendCommand()">
                <button onclick="sendCommand()">SEND</button>
            </div>
        </div>

        <!-- Console Logging Buffer -->
        <div class="console-container">
            <div class="console-title">
                <span>Machine Spirit Output Logs</span>
                <span style="color: var(--brass)">Active Console Connection</span>
            </div>
            <div class="console-box" id="console-box">
                <div class="console-line">[SYSTEM] Remote terminal connection established.</div>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('eye-canvas');
        const ctx = canvas.getContext('2d');
        const img = document.getElementById('custom-image');
        const statusBadge = document.getElementById('status-badge');
        const tempVal = document.getElementById('temp-val');
        const gameVal = document.getElementById('game-val');
        const eyeRing = document.getElementById('eye-ring');
        const eyeLed = document.getElementById('eye-led');
        const chatContainer = document.getElementById('chat-container');
        const consoleBox = document.getElementById('console-box');
        const screensaverSelect = document.getElementById('screensaver-select');
        const micBtn = document.getElementById('mic-btn');

        let currentState = {
            showing_custom_image: false,
            active_idle_anim: null,
            speaking: false,
            thinking: false,
            amplitude: 0,
            scanning_auspex: false,
            scanning_noosphere: false,
            targeting: false,
            visualizing_music: false,
            rolling_die: false,
            die_result: ""
        };

        let lastRepliedText = "";
        let audioContext = null;
        let mediaRecorder = null;
        let audioChunks = [];
        let canvasAnimationId = null;
        let animationFrameCount = 0;

        // Fetch State loop
        async function fetchState() {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                
                // Update basic telemetry
                tempVal.innerText = data.temperature;
                gameVal.innerText = data.active_game.toUpperCase();
                
                // Update screensaver options if not already filled
                if (screensaverSelect.options.length <= 1 && data.screensavers) {
                    data.screensavers.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s;
                        opt.innerText = s.replace('_', ' ').toUpperCase();
                        screensaverSelect.appendChild(opt);
                    });
                }

                // Update Logs Console
                if (data.logs) {
                    consoleBox.innerHTML = '';
                    data.logs.forEach(line => {
                        const div = document.createElement('div');
                        div.className = 'console-line';
                        div.innerText = line;
                        consoleBox.appendChild(div);
                    });
                    consoleBox.scrollTop = consoleBox.scrollHeight;
                }

                // Check state transitions
                const prevState = { ...currentState };
                currentState = data.display;

                // Update Status Badge
                let statusText = "● IDLE";
                let statusColor = "var(--text-muted)";
                if (currentState.thinking) {
                    statusText = "● THINKING";
                    statusColor = "var(--cyan-glow)";
                } else if (currentState.speaking) {
                    statusText = "● SPEAKING";
                    statusColor = "var(--red-glow)";
                } else if (currentState.scanning_auspex || currentState.scanning_noosphere) {
                    statusText = "● SCANNING";
                    statusColor = "var(--green-glow)";
                } else if (currentState.active_idle_anim) {
                    statusText = `● SCREENSAVER (${currentState.active_idle_anim})`;
                    statusColor = "var(--brass)";
                }
                statusBadge.innerText = statusText;
                statusBadge.style.color = statusColor;
                statusBadge.style.borderColor = statusColor;

                // Adjust glows/LEDs based on amplitude
                const amp = currentState.amplitude || 0;
                let brightness = 15;
                if (currentState.speaking) {
                    brightness = 30 + amp * 70;
                } else if (currentState.thinking) {
                    brightness = 40 + Math.sin(Date.now() / 150) * 20;
                }
                
                eyeLed.style.opacity = brightness / 100;
                eyeLed.style.transform = `scale(${0.8 + (brightness/100)*0.4})`;
                eyeRing.style.boxShadow = `0 0 ${15 + (brightness/100)*25}px var(--red-dim)`;

                // Update custom image display
                if (currentState.showing_custom_image) {
                    img.style.display = 'block';
                    canvas.style.display = 'none';
                    // Reload src if just transitioned
                    if (!prevState.showing_custom_image) {
                        img.src = '/api/custom_image.jpg?t=' + Date.now();
                    }
                } else {
                    img.style.display = 'none';
                    canvas.style.display = 'block';
                }

            } catch (err) {
                console.error("Error fetching state:", err);
            }
        }

        setInterval(fetchState, 300);

        // Canvas animation simulation
        function drawCanvas() {
            animationFrameCount++;
            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, 240, 240);

            const now = Date.now();

            if (currentState.thinking) {
                // Spinning Cog Animation
                ctx.save();
                ctx.translate(120, 120);
                ctx.rotate((animationFrameCount * 2 * Math.PI) / 180);
                
                ctx.strokeStyle = 'var(--cyan-glow)';
                ctx.lineWidth = 4;
                ctx.beginPath();
                ctx.arc(0, 0, 50, 0, 2 * Math.PI);
                ctx.stroke();

                // Draw teeth
                for (let i = 0; i < 8; i++) {
                    ctx.rotate(Math.PI / 4);
                    ctx.fillRect(-8, -62, 16, 12);
                }
                ctx.restore();
                
                // Pulsing central iris
                ctx.beginPath();
                ctx.arc(120, 120, 30 + Math.sin(now / 100)*4, 0, 2*Math.PI);
                ctx.fillStyle = 'var(--red-glow)';
                ctx.fill();
            }
            else if (currentState.speaking) {
                // Speaking iris pulses
                const amp = currentState.amplitude || 0;
                const irisRadius = 40 + amp * 35;
                
                // Glow boundary
                ctx.beginPath();
                ctx.arc(120, 120, irisRadius + 8, 0, 2 * Math.PI);
                ctx.fillStyle = 'rgba(255, 42, 42, 0.2)';
                ctx.fill();

                // Solid center
                ctx.beginPath();
                ctx.arc(120, 120, irisRadius, 0, 2 * Math.PI);
                ctx.fillStyle = 'var(--red-glow)';
                ctx.fill();

                // Pupil
                ctx.beginPath();
                ctx.arc(120, 120, 15, 0, 2 * Math.PI);
                ctx.fillStyle = '#000000';
                ctx.fill();
            }
            else if (currentState.scanning_auspex || currentState.scanning_noosphere) {
                // Radar sweep
                ctx.save();
                ctx.translate(120, 120);
                const angle = (animationFrameCount * 3) % 360;
                ctx.rotate((angle * Math.PI) / 180);
                
                // Sweep line
                const scanColor = currentState.scanning_auspex ? 'rgba(16, 185, 129, 0.8)' : 'rgba(255, 42, 42, 0.8)';
                ctx.strokeStyle = scanColor;
                ctx.lineWidth = 3;
                ctx.beginPath();
                ctx.moveTo(0, 0);
                ctx.lineTo(0, -110);
                ctx.stroke();
                
                // Fade gradient
                ctx.fillStyle = currentState.scanning_auspex ? 'rgba(16, 185, 129, 0.05)' : 'rgba(255, 42, 42, 0.05)';
                ctx.beginPath();
                ctx.moveTo(0, 0);
                ctx.arc(0, 0, 110, -Math.PI/2, -Math.PI/2 - 0.5, true);
                ctx.closePath();
                ctx.fill();

                ctx.restore();

                // Draw circles
                ctx.strokeStyle = currentState.scanning_auspex ? 'rgba(16, 185, 129, 0.3)' : 'rgba(255, 42, 42, 0.3)';
                ctx.lineWidth = 1;
                for (let r = 30; r <= 110; r += 30) {
                    ctx.beginPath();
                    ctx.arc(120, 120, r, 0, 2 * Math.PI);
                    ctx.stroke();
                }
            }
            else if (currentState.rolling_die) {
                // Draw rotating numbers or dice outline
                ctx.strokeStyle = 'var(--brass)';
                ctx.lineWidth = 2;
                ctx.strokeRect(60, 60, 120, 120);
                
                ctx.fillStyle = 'var(--text-color)';
                ctx.font = '36px Courier New';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const tempRoll = Math.floor(Math.random() * 20) + 1;
                ctx.fillText(currentState.die_result || tempRoll.toString(), 120, 120);
            }
            else if (currentState.active_idle_anim === 'canticle_rain') {
                // Binary Matrix rain simulation
                ctx.fillStyle = 'rgba(0, 0, 0, 0.15)';
                ctx.fillRect(0, 0, 240, 240);
                ctx.fillStyle = '#10b981';
                ctx.font = '12px Courier New';
                for (let i = 10; i < 240; i += 20) {
                    const char = Math.random() > 0.5 ? "1" : "0";
                    const y = (animationFrameCount * 4 + i * 3) % 240;
                    ctx.fillText(char, i, y);
                }
            }
            else {
                // Default breathing iris
                const radius = 50 + Math.sin(now / 800) * 5;
                ctx.beginPath();
                ctx.arc(120, 120, radius, 0, 2 * Math.PI);
                ctx.fillStyle = 'var(--red-glow)';
                ctx.fill();

                ctx.beginPath();
                ctx.arc(120, 120, 12, 0, 2 * Math.PI);
                ctx.fillStyle = '#000000';
                ctx.fill();
            }

            canvasAnimationId = requestAnimationFrame(drawCanvas);
        }

        drawCanvas();

        // Control API Calls
        async function triggerWake() {
            addChatBubble("Triggering verbal wake word...", 'chat-user');
            await fetch('/api/wake', { method: 'POST' });
        }

        async function sendCommand() {
            const input = document.getElementById('command-input');
            const cmd = input.value.trim();
            if (!cmd) return;

            addChatBubble(cmd, 'chat-user');
            input.value = "";

            try {
                const res = await fetch('/api/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: cmd })
                });
                const data = await res.json();
                if (data.status !== 'ok') {
                    addChatBubble(`Error: ${data.message}`, 'chat-skull');
                }
            } catch (err) {
                addChatBubble(`Failed to send command: ${err}`, 'chat-skull');
            }
        }

        async function playScreensaver() {
            const select = document.getElementById('screensaver-select');
            const anim = select.value;
            if (!anim) return;
            
            const cmd = `play ${anim} screensaver`;
            addChatBubble(cmd, 'chat-user');
            
            await fetch('/api/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            });
        }

        function addChatBubble(text, className) {
            const bubble = document.createElement('div');
            bubble.className = `chat-bubble ${className}`;
            bubble.innerText = text;
            chatContainer.appendChild(bubble);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        // Web Audio Recording (Microphone) -> WAV mono 16kHz
        let mediaStream = null;

        async function startMicRecording() {
            micBtn.classList.add('recording');
            micBtn.innerText = "RECORDING...";
            audioChunks = [];

            try {
                if (!audioContext) {
                    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                }
                
                mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const source = audioContext.createMediaStreamSource(mediaStream);
                
                // Use a processor to downsample and collect PCM samples
                const bufferSize = 4096;
                const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
                
                processor.onaudioprocess = function(e) {
                    const inputData = e.inputBuffer.getChannelData(0);
                    // Copy float32 samples
                    audioChunks.push(new Float32Array(inputData));
                };
                
                source.connect(processor);
                processor.connect(audioContext.destination);
                
                // Store references to shut down later
                micBtn.audioProcessor = processor;
                micBtn.audioSource = source;
            } catch (err) {
                console.error("Mic access failed:", err);
                addChatBubble("Failed to access browser microphone.", 'chat-skull');
                stopMicRecording();
            }
        }

        async function stopMicRecording() {
            if (!micBtn.classList.contains('recording')) return;
            
            micBtn.classList.remove('recording');
            micBtn.innerText = "HOLD TO SPEAK";

            if (micBtn.audioProcessor) {
                micBtn.audioProcessor.disconnect();
                micBtn.audioSource.disconnect();
            }
            if (mediaStream) {
                mediaStream.getTracks().forEach(track => track.stop());
            }

            // Convert Float32Array chunks to 16-bit PCM WAV
            if (audioChunks.length === 0) return;
            
            addChatBubble("[Voice input transmitted]", 'chat-user');
            
            const wavBlob = encodeWAV(audioChunks, 16000);
            
            try {
                const res = await fetch('/api/upload_audio', {
                    method: 'POST',
                    headers: { 'Content-Type': 'audio/wav' },
                    body: wavBlob
                });
                const data = await res.json();
                if (data.status !== 'ok') {
                    addChatBubble(`Speech processing failed: ${data.message}`, 'chat-skull');
                }
            } catch (err) {
                addChatBubble(`Speech transmission failed: ${err}`, 'chat-skull');
            }
        }

        // JS WAV Encoder Helper
        function encodeWAV(chunks, sampleRate) {
            // Flatten chunks
            let totalLength = 0;
            for (let i = 0; i < chunks.length; i++) {
                totalLength += chunks[i].length;
            }
            const samples = new Float32Array(totalLength);
            let offset = 0;
            for (let i = 0; i < chunks.length; i++) {
                samples.set(chunks[i], offset);
                offset += chunks[i].length;
            }

            const buffer = new ArrayBuffer(44 + samples.length * 2);
            const view = new DataView(buffer);

            /* RIFF identifier */
            writeString(view, 0, 'RIFF');
            /* file length */
            view.setUint32(4, 36 + samples.length * 2, true);
            /* RIFF type */
            writeString(view, 8, 'WAVE');
            /* format chunk identifier */
            writeString(view, 12, 'fmt ');
            /* format chunk length */
            view.setUint32(16, 16, true);
            /* sample format (raw pcm) */
            view.setUint16(20, 1, true);
            /* channel count (mono) */
            view.setUint16(22, 1, true);
            /* sample rate */
            view.setUint32(24, sampleRate, true);
            /* byte rate (sample rate * block align) */
            view.setUint32(28, sampleRate * 2, true);
            /* block align (channel count * bytes per sample) */
            view.setUint16(32, 2, true);
            /* bits per sample */
            view.setUint16(34, 16, true);
            /* data chunk identifier */
            writeString(view, 36, 'data');
            /* chunk length */
            view.setUint32(40, samples.length * 2, true);

            // Write PCM audio samples (Float32 to Int16)
            let index = 44;
            for (let i = 0; i < samples.length; i++) {
                const s = Math.max(-1, Math.min(1, samples[i]));
                view.setInt16(index, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
                index += 2;
            }

            return new Blob([view], { type: 'audio/wav' });
        }

        function writeString(view, offset, string) {
            for (let i = 0; i < string.length; i++) {
                view.setUint8(offset + i, string.charCodeAt(i));
            }
        }
    </script>
</body>
</html>
"""
