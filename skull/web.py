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

# Thread-safe log buffers (Telemetry vs Vox Channel)
_log_buffer = collections.deque(maxlen=100)
_log_lock = threading.RLock()

_vox_buffer = collections.deque(maxlen=100)
_vox_lock = threading.RLock()


def log_vox(speaker: str, text: str, timestamp: str | None = None) -> None:
    if not text or not text.strip():
        return
    if not timestamp:
        timestamp = time.strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "speaker": speaker.strip() if speaker else "User",
        "text": text.strip()
    }
    with _vox_lock:
        if _vox_buffer and _vox_buffer[-1]["text"] == entry["text"] and _vox_buffer[-1]["speaker"] == entry["speaker"]:
            return
        _vox_buffer.append(entry)


_vox_history_loaded = False


def clear_vox_logs() -> None:
    global _vox_history_loaded
    with _vox_lock:
        _vox_buffer.clear()
        _vox_history_loaded = True


def load_vox_history_from_brain() -> None:
    global _vox_history_loaded
    if _vox_history_loaded:
        return
    _vox_history_loaded = True
    try:
        from skull import brain
        history = brain.get_history()
        import re
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if not content:
                continue
            if role == "user":
                m = re.match(r'^\[([^\]]+)\]:\s*(.+)$', content)
                if m:
                    spk = m.group(1)
                    txt = m.group(2)
                else:
                    spk = "User"
                    txt = content
                log_vox(spk, txt, timestamp="History")
            elif role == "assistant":
                log_vox(config.SKULL_NAME, content, timestamp="History")
    except Exception as e:
        print(f"[web] History load error: {e}")


def get_vox_logs() -> list[dict]:
    with _vox_lock:
        if not _vox_history_loaded:
            load_vox_history_from_brain()
        return list(_vox_buffer)


class WebLogRedirect:
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout

    def write(self, s):
        self.original_stdout.write(s)
        if s.strip():
            import re
            clean_s = re.sub(r'\x1b\[[0-9;]*[mK]', '', s.strip())
            now_str = time.strftime("%H:%M:%S")

            m_heard = re.match(r'^\[skull\]\s+Heard(?:\s*\(([^)]+)\))?:\s*(.+)$', clean_s)
            m_skull = re.match(r'^\[skull\]\s+([^:]+):\s*(.+)$', clean_s)

            if m_heard:
                spk = m_heard.group(1) or "User"
                txt = m_heard.group(2)
                log_vox(spk, txt, timestamp=now_str)
            elif clean_s.startswith("[skull] Web command received:"):
                txt = clean_s[len("[skull] Web command received:"):].strip()
                log_vox("Web Master", txt, timestamp=now_str)
            elif clean_s.startswith("[skull] Idle:"):
                txt = clean_s[len("[skull] Idle:"):].strip()
                log_vox(config.SKULL_NAME, txt, timestamp=now_str)
            elif clean_s.startswith("[skull] Daily Briefing:"):
                txt = clean_s[len("[skull] Daily Briefing:"):].strip()
                log_vox(config.SKULL_NAME, txt, timestamp=now_str)
            elif m_skull and m_skull.group(1).strip() in (config.SKULL_NAME, "Omega-7", "Servo-Skull"):
                spk = m_skull.group(1).strip()
                txt = m_skull.group(2)
                log_vox(spk, txt, timestamp=now_str)
            else:
                with _log_lock:
                    _log_buffer.append(f"[{now_str}] {clean_s}")

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
    spk = speaker_name if speaker_name else config._OWNER_PROFILE.get("name", "User")
    log_vox(spk, text)
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


def get_ram_usage() -> str:
    try:
        import psutil
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024**3)
        total_gb = mem.total / (1024**3)
        return f"{mem.percent:.1f}% ({used_gb:.1f}G/{total_gb:.1f}G)"
    except Exception:
        return "42.5% (1.7G/4.0G) [Virtual]"


def get_storage_usage() -> str:
    try:
        import psutil
        disk = psutil.disk_usage('/')
        used_gb = disk.used / (1024**3)
        total_gb = disk.total / (1024**3)
        return f"{disk.percent:.1f}% ({used_gb:.1f}G/{total_gb:.1f}G)"
    except Exception:
        try:
            import os
            st = os.statvfs('/')
            free = st.f_bavail * st.f_frsize
            total = st.f_blocks * st.f_frsize
            used = total - free
            pct = (used / total) * 100
            return f"{pct:.1f}% ({used / (1024**3):.1f}G/{total / (1024**3):.1f}G)"
        except Exception:
            return "18.2% (11.6G/64.0G) [Virtual]"


def get_cpu_usage() -> str:
    try:
        import psutil
        pct = psutil.cpu_percent(interval=None)
        return f"{pct:.1f}%"
    except Exception:
        return "12.4% [Virtual]"


def get_fabricator_status() -> dict:
    try:
        from skull import bambu_ctrl
        status = bambu_ctrl.get_status_report()
        if status is None:
            monitor = bambu_ctrl.get_monitor()
            if monitor and monitor.is_configured():
                return {"text": "OFFLINE", "percent": 0.0}
            return {"text": "UNCONFIGURED", "percent": 0.0}
        
        state = status.get("gcode_state", "UNKNOWN").upper()
        percent = float(status.get("percent", 0))
        if state in ("RUNNING", "PREPARE"):
            return {"text": f"{state} ({percent:.0f}%)", "percent": percent}
        return {"text": state, "percent": 0.0}
    except Exception:
        return {"text": "UNAVAILABLE", "percent": 0.0}

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
                t_val = temperature.read_temp_c()
                if t_val is not None:
                    temp = f"{t_val:.1f}°C"
                else:
                    temp = "42.0°C (Virtual)"
            except Exception:
                temp = "Unavailable"
                
            from skull import quiet
            master_name = config._OWNER_PROFILE.get("name", "Unknown").upper()
            state_data = {
                "skull_name": config.SKULL_NAME,
                "display": disp_state,
                "temperature": temp,
                "cpu": get_cpu_usage(),
                "ram": get_ram_usage(),
                "storage": get_storage_usage(),
                "master": master_name,
                "silent_mode": "ACTIVE" if quiet.is_silent() else "INACTIVE",
                "fabricator": get_fabricator_status(),
                "active_game": brain.get_current_game() if hasattr(brain, "get_current_game") else "None",
                "screensavers": display.get_screensaver_names() if hasattr(display, "get_screensaver_names") else [],
                "logs": get_logs(),
                "vox_logs": get_vox_logs(),
            }
            self._send_json(state_data)
            return
            
        elif self.path == "/api/custom_image.jpg":
            img_bytes = display.get_ocular_frame_bytes()
            if img_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(img_bytes)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(img_bytes)
            else:
                self.send_response(404)
                self.end_headers()
            return
            
        elif self.path == "/api/ocular_stream.mjpeg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            try:
                import time
                while True:
                    img_bytes = display.get_ocular_frame_bytes()
                    if img_bytes:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(img_bytes)}\r\n\r\n".encode())
                        self.wfile.write(img_bytes)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.066)  # ~15 FPS matching display thread
            except Exception:
                pass
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
        import os
        import ssl
        import subprocess

        use_https = getattr(config, "WEB_SERVER_HTTPS", True)
        # Save certificates in the skull code directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cert_file = os.path.join(base_dir, "cert.pem")
        key_file = os.path.join(base_dir, "key.pem")

        if use_https:
            if not os.path.exists(cert_file) or not os.path.exists(key_file):
                print("[web] Generating self-signed SSL certificate for secure audio capture context...")
                try:
                    subprocess.run([
                        "openssl", "req", "-new", "-newkey", "rsa:2048", "-days", "365",
                        "-nodes", "-x509", "-keyout", key_file, "-out", cert_file,
                        "-subj", "/C=US/ST=Mars/L=Mechanicus/O=Adeptus/CN=omega7"
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    print(f"[web] Failed to generate self-signed certificate: {e}")
                    use_https = False

        server = ThreadingHTTPServer(("0.0.0.0", port), WebRequestHandler)

        if use_https and os.path.exists(cert_file) and os.path.exists(key_file):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=cert_file, keyfile=key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            print(f"[web] Servoskull Web Remote Server running SECURELY on HTTPS port {port}")
        else:
            print(f"[web] Servoskull Web Remote Server running on HTTP port {port} (insecure context - microphone disabled by browser)")

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
    <title>Omega-7 Cogitator Terminal</title>
    <style>
        :root {
            --bg-color: #020803;
            --card-color: #030f05;
            --border-color: #14531d;
            --bright-green: #38ff58;
            --dim-green: #117823;
            --glow-color: rgba(56, 255, 88, 0.45);
            --crt-glow: rgba(56, 255, 88, 0.1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: var(--bright-green);
            font-family: 'Share Tech Mono', 'Courier New', Courier, monospace;
            overflow-x: hidden;
            position: relative;
            min-height: 100vh;
        }

        /* CRT Screen Filter & Glass Effects */
        .screen {
            position: relative;
            width: 100%;
            min-height: 100vh;
            padding: 20px;
            box-sizing: border-box;
        }

        .screen::after {
            content: " ";
            display: block;
            position: fixed;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), 
                        linear-gradient(90deg, rgba(56, 255, 88, 0.04), rgba(0, 255, 0, 0.01), rgba(0, 0, 255, 0.03));
            background-size: 100% 4px, 6px 100%;
            z-index: 9999;
            pointer-events: none;
            animation: crt-flicker 0.25s infinite;
        }

        .screen::before {
            content: " ";
            display: block;
            position: fixed;
            top: 0; left: 0; bottom: 0; right: 0;
            background: radial-gradient(circle, rgba(56, 255, 88, 0.03) 0%, rgba(0, 0, 0, 0.75) 120%);
            z-index: 10000;
            pointer-events: none;
        }

        @keyframes crt-flicker {
            0% { opacity: 0.985; }
            50% { opacity: 1; }
            100% { opacity: 0.978; }
        }

        /* Page Layout Container */
        .container {
            width: 100%;
            max-width: 1000px;
            margin: 0 auto;
            border: 2px solid var(--border-color);
            background-color: var(--card-color);
            padding: 24px;
            position: relative;
            box-shadow: 0 0 30px rgba(17, 120, 35, 0.15);
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        /* Diagonal corner cuts for AdMech framing */
        .container::before, .container::after, .frame-bracket::before, .frame-bracket::after {
            content: "";
            position: absolute;
            width: 16px;
            height: 16px;
            border-color: var(--bright-green);
            border-style: solid;
            pointer-events: none;
        }

        .container::before { top: -2px; left: -2px; border-width: 4px 0 0 4px; }
        .container::after { top: -2px; right: -2px; border-width: 4px 4px 0 0; }
        
        .frame-bracket {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            pointer-events: none;
        }
        .frame-bracket::before { bottom: -2px; left: -2px; border-width: 0 0 4px 4px; }
        .frame-bracket::after { bottom: -2px; right: -2px; border-width: 0 4px 4px 0; }

        @media (max-width: 768px) {
            .container {
                grid-template-columns: 1fr;
                padding: 16px;
            }
        }

        /* Heading & Telemetry Section */
        .header {
            grid-column: 1 / -1;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 16px;
            margin-bottom: 10px;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 10px;
            width: 100%;
        }

        .header h1 {
            color: var(--bright-green);
            font-size: 26px;
            letter-spacing: 3px;
            text-shadow: 0 0 10px var(--glow-color);
            display: flex;
            align-items: center;
            gap: 12px;
        }

        /* SVG AdMech Logo */
        .cog-logo {
            width: 28px;
            height: 28px;
            fill: var(--bright-green);
            filter: drop-shadow(0 0 4px var(--glow-color));
            animation: slow-spin 20s linear infinite;
        }

        @keyframes slow-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .telemetry {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            width: 100%;
            border: 2px double var(--border-color);
            background: rgba(17, 120, 35, 0.03);
            padding: 12px 16px;
            box-sizing: border-box;
            border-radius: 4px;
            margin-top: 10px;
        }

        .telemetry-item {
            border: 1px solid var(--border-color);
            background: rgba(17, 120, 35, 0.05);
            padding: 8px 14px;
            border-radius: 2px;
            box-shadow: inset 0 0 5px rgba(0,0,0,0.8);
            display: flex;
            flex-direction: column;
            gap: 8px;
            flex: 1 1 200px;
            min-width: 180px;
        }

        .telemetry-item.text-only {
            justify-content: center;
            flex: 1 1 150px;
            min-width: 130px;
        }

        .telemetry-label {
            color: rgba(56, 255, 88, 0.75);
            font-size: 11px;
            letter-spacing: 1.5px;
            font-weight: bold;
            text-shadow: 0 0 2px rgba(56, 255, 88, 0.3);
        }

        .telemetry-value {
            color: var(--bright-green);
            font-weight: bold;
            text-shadow: 0 0 4px var(--glow-color);
            font-size: 13px;
        }

        .sensor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .sensor-bar-container {
            width: 100%;
            height: 6px;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--border-color);
            border-radius: 1px;
            overflow: hidden;
            box-shadow: inset 0 0 4px rgba(0,0,0,0.9);
        }

        .sensor-bar {
            height: 100%;
            background: var(--bright-green);
            box-shadow: 0 0 8px var(--glow-color);
            width: 0%;
            transition: width 0.4s cubic-bezier(0.1, 0.8, 0.3, 1);
        }

        /* Immersive Top Alert Banner */
        .alert-banner {
            grid-column: 1 / -1;
            border: 2px solid var(--bright-green);
            background-color: rgba(56, 255, 88, 0.07);
            box-shadow: 0 0 15px rgba(56, 255, 88, 0.15), inset 0 0 10px rgba(56, 255, 88, 0.08);
            padding: 14px 20px;
            text-align: center;
            border-radius: 2px;
            position: relative;
            margin-bottom: 5px;
        }

        .alert-banner::before {
            content: "◆ COGITATOR MONITORING ACTIVE ◆";
            position: absolute;
            top: -9px;
            left: 50%;
            transform: translateX(-50%);
            background-color: var(--card-color);
            padding: 0 8px;
            font-size: 11px;
            color: var(--bright-green);
            letter-spacing: 2px;
        }

        .alert-title {
            font-size: 12px;
            color: var(--bright-green);
            letter-spacing: 4px;
            opacity: 0.8;
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        .alert-value {
            font-size: 24px;
            font-weight: 900;
            letter-spacing: 6px;
            color: var(--bright-green);
            text-shadow: 0 0 10px var(--glow-color);
            text-transform: uppercase;
        }

        /* Left Column: Tactical Ocular Display Feed */
        .ocular-pane {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 20px;
            padding: 15px;
            border: 1px solid var(--border-color);
            background: rgba(0,0,0,0.4);
            position: relative;
        }

        .ocular-ring {
            width: 270px;
            height: 270px;
            border: 4px double var(--bright-green);
            position: relative;
            background-color: #000200;
            box-shadow: 0 0 20px rgba(56, 255, 88, 0.1), inset 0 0 25px rgba(0,0,0,0.95);
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        /* Ocular Bezel Tech Details */
        .ocular-bezel-text {
            position: absolute;
            font-size: 9px;
            color: var(--dim-green);
            z-index: 10;
        }
        .bezel-tl { top: 6px; left: 6px; }
        .bezel-tr { top: 6px; right: 6px; }
        .bezel-bl { bottom: 6px; left: 6px; }
        .bezel-br { bottom: 6px; right: 6px; }

        .ocular-canvas {
            width: 240px;
            height: 240px;
            border-radius: 50%;
            display: block;
        }

        /* Monochromatic Green night vision filter for custom image uploads */
        .custom-image-display {
            position: absolute;
            width: 240px;
            height: 240px;
            border-radius: 50%;
            object-fit: cover;
            display: none;
            filter: sepia(1) hue-rotate(85deg) saturate(2.5) contrast(1.2) brightness(0.95);
            opacity: 0.95;
        }

        /* Right Column: Mechanical Vox Control Panel */
        .control-pane {
            display: flex;
            flex-direction: column;
            gap: 12px;
            border: 1px solid var(--border-color);
            padding: 15px;
            background: rgba(0,0,0,0.4);
            min-height: 380px;
        }

        .pane-title {
            font-size: 13px;
            letter-spacing: 2px;
            color: var(--bright-green);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 6px;
            margin-bottom: 4px;
            text-transform: uppercase;
        }

        /* Chat feed / console interface */
        .chat-container {
            flex-grow: 1;
            height: 320px;
            min-height: 300px;
            border: 1px solid var(--border-color);
            background: rgba(0, 0, 0, 0.6);
            padding: 12px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
            font-size: 13px;
            box-shadow: inset 0 0 10px rgba(0,0,0,0.9);
        }

        .chat-bubble {
            max-width: 90%;
            padding: 8px 12px;
            border-radius: 2px;
            line-height: 1.4;
            border-left: 3px solid;
            white-space: pre-wrap;
        }

        .chat-user {
            align-self: flex-end;
            background-color: rgba(56, 255, 88, 0.05);
            border-color: var(--dim-green);
            color: var(--bright-green);
        }

        .chat-skull {
            align-self: flex-start;
            background-color: rgba(56, 255, 88, 0.1);
            border-color: var(--bright-green);
            color: var(--bright-green);
            text-shadow: 0 0 4px var(--glow-color);
        }

        .input-bar {
            display: flex;
            gap: 8px;
        }

        .input-bar input {
            flex-grow: 1;
            background-color: rgba(0,0,0,0.7);
            border: 1px solid var(--border-color);
            padding: 10px;
            color: var(--bright-green);
            font-family: inherit;
            font-size: 14px;
        }

        .input-bar input:focus {
            outline: none;
            border-color: var(--bright-green);
            box-shadow: 0 0 5px var(--glow-color);
        }

        /* High-tech chamfered button style */
        button {
            background-color: rgba(17, 120, 35, 0.15);
            border: 1px solid var(--bright-green);
            color: var(--bright-green);
            padding: 10px 18px;
            font-family: inherit;
            cursor: pointer;
            font-weight: bold;
            letter-spacing: 1px;
            text-shadow: 0 0 4px var(--glow-color);
            transition: all 0.2s ease;
            clip-path: polygon(8px 0%, 100% 0%, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0% 100%, 0% 8px);
        }

        button:hover {
            background-color: var(--bright-green);
            color: #000;
            text-shadow: none;
            box-shadow: 0 0 10px var(--glow-color);
        }

        /* Small Icon Buttons for Mic Controls */
        .icon-btn {
            width: 38px;
            height: 38px;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }

        .btn-svg {
            width: 18px;
            height: 18px;
            fill: var(--bright-green);
            transition: fill 0.2s ease;
        }

        button:hover .btn-svg {
            fill: #000;
        }

        button.wake-btn {
            background-color: rgba(56, 255, 88, 0.08);
        }

        button.mic-btn {
            background-color: rgba(0,0,0,0.6);
            border-color: var(--border-color);
        }
        
        button.mic-btn.recording {
            background-color: var(--bright-green);
            color: #000;
            text-shadow: none;
            animation: pulse 1.5s infinite;
        }

        button.mic-btn.recording .btn-svg {
            fill: #000;
        }

        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(56, 255, 88, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(56, 255, 88, 0); }
            100% { box-shadow: 0 0 0 0 rgba(56, 255, 88, 0); }
        }

        /* Console Output Logs Pane */
        .console-container {
            grid-column: 1 / -1;
            border: 1px solid var(--border-color);
            background: rgba(0,0,0,0.5);
            padding: 16px;
        }

        .console-box {
            background: rgba(0, 0, 0, 0.8);
            border: 1px solid var(--border-color);
            height: 130px;
            padding: 8px 12px;
            overflow-y: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 11px;
            color: var(--bright-green);
            line-height: 1.5;
            box-shadow: inset 0 0 10px rgba(0,0,0,0.95);
        }

        .console-line {
            white-space: pre-wrap;
            border-bottom: 1px dashed rgba(56, 255, 88, 0.08);
            padding: 2px 0;
            opacity: 1.0;
            text-shadow: 0 0 3px var(--glow-color);
        }

        .controls-row {
            display: flex;
            gap: 10px;
        }

        .controls-row select {
            flex-grow: 1;
            background-color: rgba(0,0,0,0.7);
            border: 1px solid var(--border-color);
            color: var(--bright-green);
            padding: 8px;
            font-family: inherit;
        }
        
        .controls-row select:focus {
            outline: none;
            border-color: var(--bright-green);
        }

        /* Custom Scrollbars */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(0,0,0,0.5);
        }
        ::-webkit-scrollbar-thumb {
            background: var(--dim-green);
            border-radius: 1px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--bright-green);
        }
    </style>
</head>
<body>
    <div class="screen">
        <div class="container">
            <div class="frame-bracket"></div>

            <!-- Header -->
            <div class="header">
                <h1>
                    <!-- Wireframe SVG Cog Logo -->
                    <svg class="cog-logo" viewBox="0 0 100 100">
                        <path d="M50 20c-16.5 0-30 13.5-30 30s13.5 30 30 30 30-13.5 30-30-13.5-30-30-30zm0 10c11 0 20 9 20 20s-9 20-20 20-20-9-20-20 9-20 20-20z"/>
                        <path d="M50 0l6 14h-12zM50 100l6-14h-12zM0 50l14-6v12zM100 50l-14-6v12zM15 15l10 10-8 8zM85 85l-10-10 8-8zM15 85l10-10-8-8zM85 15l-10 10 8 8z"/>
                    </svg>
                    OMEGA-7 COGITATOR TERMINAL
                </h1>
                <div class="telemetry">
                    <div class="telemetry-item">
                        <div class="sensor-header">
                            <span class="telemetry-label">CORE TEMP:</span>
                            <span id="temp-val" class="telemetry-value">--.-°C</span>
                        </div>
                        <div class="sensor-bar-container">
                            <div id="temp-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                    </div>
                    <div class="telemetry-item">
                        <div class="sensor-header">
                            <span class="telemetry-label">CPU:</span>
                            <span id="cpu-val" class="telemetry-value">--.-%</span>
                        </div>
                        <div class="sensor-bar-container">
                            <div id="cpu-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                    </div>
                    <div class="telemetry-item">
                        <div class="sensor-header">
                            <span class="telemetry-label">RAM:</span>
                            <span id="ram-val" class="telemetry-value">--.-%</span>
                        </div>
                        <div class="sensor-bar-container">
                            <div id="ram-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                    </div>
                    <div class="telemetry-item">
                        <div class="sensor-header">
                            <span class="telemetry-label">STORAGE:</span>
                            <span id="storage-val" class="telemetry-value">--.-%</span>
                        </div>
                        <div class="sensor-bar-container">
                            <div id="storage-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                    </div>
                    <div class="telemetry-item">
                        <div class="sensor-header">
                            <span class="telemetry-label">FABRICATOR:</span>
                            <span id="fabricator-val" class="telemetry-value">UNCONFIGURED</span>
                        </div>
                        <div class="sensor-bar-container">
                            <div id="fabricator-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                    </div>
                    <div class="telemetry-item text-only">
                        <span class="telemetry-label">MASTER</span>
                        <span id="master-val" class="telemetry-value">UNKNOWN</span>
                    </div>
                    <div class="telemetry-item text-only">
                        <span class="telemetry-label">SILENT MODE</span>
                        <span id="silent-val" class="telemetry-value">INACTIVE</span>
                    </div>
                    <div class="telemetry-item text-only">
                        <span class="telemetry-label">ACTIVE GAME</span>
                        <span id="game-val" class="telemetry-value">NONE</span>
                    </div>
                </div>
            </div>

            <!-- Thematic Warning/Status Banner (Secret Level Style) -->
            <div class="alert-banner">
                <div class="alert-title" id="alert-title">SYSTEM STATUS</div>
                <div class="alert-value" id="alert-value">SYSTEM OPTIMAL</div>
            </div>

            <!-- Left column: Ocular Feed -->
            <div class="ocular-pane">
                <div class="pane-title" style="width: 100%;">[ OCULAR SENSOR FEED ]</div>
                <div class="ocular-ring" id="eye-ring">
                    <!-- Overlay Bezel Telemetry -->
                    <div class="ocular-bezel-text bezel-tl">TGT: LOCK</div>
                    <div class="ocular-bezel-text bezel-tr">Z: 4.0X</div>
                    <div class="ocular-bezel-text bezel-bl">SENS: IR/NV</div>
                    <div class="ocular-bezel-text bezel-br">RA: 18h36m</div>

                    <img class="ocular-canvas" id="eye-stream" src="/api/ocular_stream.mjpeg" alt="Ocular View">
                </div>
            </div>

            <!-- Right column: Control Room -->
            <div class="control-pane">
                <div class="pane-title">[ VOX CHANNEL LOGS ]</div>
                <div class="chat-container" id="chat-container">
                    <div class="chat-bubble chat-skull">System initialized. Awaiting commands, master.</div>
                </div>
                
                <div class="controls-row">
                    <select id="screensaver-select">
                        <option value="">-- Select Screensaver --</option>
                    </select>
                    <button onclick="playScreensaver()">RUN</button>

                    <button class="wake-btn icon-btn" onclick="triggerWake()" title="Trigger Voice Listener (Wake)">
                        <svg class="btn-svg" viewBox="0 0 24 24">
                            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                        </svg>
                    </button>

                    <button class="mic-btn icon-btn" id="mic-btn" 
                            onmousedown="startMicRecording()" onmouseup="stopMicRecording()" 
                            ontouchstart="startMicRecording()" ontouchend="stopMicRecording()" 
                            title="Hold to Speak (Web Mic)">
                        <svg class="btn-svg" viewBox="0 0 24 24">
                            <circle cx="12" cy="12" r="5"/>
                            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"/>
                        </svg>
                    </button>
                </div>

                <div class="input-bar">
                    <input type="text" id="command-input" placeholder="Enter high-level command..." onkeydown="if(event.key === 'Enter') sendCommand()">
                    <button onclick="sendCommand()">SEND</button>
                </div>
            </div>

            <!-- Console Log Panel -->
            <div class="console-container">
                <div class="pane-title">[ TELEMETRY CONSOLE FEED ]</div>
                <div class="console-box" id="console-box">
                    <div class="console-line">[SYSTEM] Remote connection established via Tailscale link.</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const alertTitle = document.getElementById('alert-title');
        const alertValue = document.getElementById('alert-value');
        const alertBanner = document.getElementById('alert-banner');
        const tempVal = document.getElementById('temp-val');
        const cpuVal = document.getElementById('cpu-val');
        const ramVal = document.getElementById('ram-val');
        const storageVal = document.getElementById('storage-val');
        const fabricatorVal = document.getElementById('fabricator-val');
        const masterVal = document.getElementById('master-val');
        const silentVal = document.getElementById('silent-val');
        const gameVal = document.getElementById('game-val');
        const eyeRing = document.getElementById('eye-ring');
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

        let lastStatus = "";
        let audioContext = null;
        let mediaRecorder = null;
        let audioChunks = [];

        // Fetch State loop
        async function fetchState() {
            try {
                const res = await fetch('/api/state');
                const data = await res.json();
                
                // Update basic telemetry
                tempVal.innerText = data.temperature;
                cpuVal.innerText = data.cpu;
                ramVal.innerText = data.ram;
                storageVal.innerText = data.storage;
                fabricatorVal.innerText = data.fabricator.text;
                masterVal.innerText = data.master;
                silentVal.innerText = data.silent_mode;
                gameVal.innerText = data.active_game.toUpperCase();

                // Update progress bars
                const tempFloat = parseFloat(data.temperature);
                if (!isNaN(tempFloat)) {
                    document.getElementById('temp-bar').style.width = Math.min(100, Math.max(0, tempFloat)) + '%';
                }
                const cpuFloat = parseFloat(data.cpu);
                if (!isNaN(cpuFloat)) {
                    document.getElementById('cpu-bar').style.width = Math.min(100, Math.max(0, cpuFloat)) + '%';
                }
                const ramFloat = parseFloat(data.ram);
                if (!isNaN(ramFloat)) {
                    document.getElementById('ram-bar').style.width = Math.min(100, Math.max(0, ramFloat)) + '%';
                }
                const storageFloat = parseFloat(data.storage);
                if (!isNaN(storageFloat)) {
                    document.getElementById('storage-bar').style.width = Math.min(100, Math.max(0, storageFloat)) + '%';
                }
                if (data.fabricator && typeof data.fabricator.percent === 'number') {
                    document.getElementById('fabricator-bar').style.width = Math.min(100, Math.max(0, data.fabricator.percent)) + '%';
                }
                
                // Update screensaver options if not already filled
                if (screensaverSelect.options.length <= 1 && data.screensavers) {
                    data.screensavers.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s;
                        opt.innerText = s.replace('_', ' ').toUpperCase();
                        screensaverSelect.appendChild(opt);
                    });
                }

                // Update Logs Console (Telemetry Console Feed)
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

                // Update Vox Channel Logs
                if (data.vox_logs && data.vox_logs.length > 0) {
                    const voxHash = JSON.stringify(data.vox_logs);
                    if (window._lastVoxHash !== voxHash) {
                        window._lastVoxHash = voxHash;
                        chatContainer.innerHTML = '';
                        data.vox_logs.forEach(msg => {
                            const bubble = document.createElement('div');
                            const isSkull = (msg.speaker === data.skull_name || msg.speaker === 'Omega-7' || msg.speaker === 'Servo-Skull');
                            bubble.className = `chat-bubble ${isSkull ? 'chat-skull' : 'chat-user'}`;
                            const timeTag = msg.time ? `[${msg.time}] ` : '';
                            bubble.innerText = `${timeTag}${msg.speaker}: ${msg.text}`;
                            chatContainer.appendChild(bubble);
                        });
                        chatContainer.scrollTop = chatContainer.scrollHeight;
                    }
                }

                // Check state transitions
                currentState = data.display;

                // Update Warning/Status Banner (Secret Level Style)
                let headerTitle = "SYSTEM STATUS";
                let headerValue = "SYSTEM OPTIMAL";
                let bannerBg = "rgba(56, 255, 88, 0.07)";
                let bannerBorder = "2px solid var(--bright-green)";

                if (currentState.thinking) {
                    headerTitle = "COGITATION PROTOCOL";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.15)";
                } else if (currentState.speaking) {
                    headerTitle = "VOCAL TRANSMISSION";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.25)";
                    bannerBorder = "3px double var(--bright-green)";
                } else if (currentState.scanning_auspex || currentState.scanning_noosphere) {
                    headerTitle = "AUSPEX SCANNING MODE";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.15)";
                } else if (currentState.active_idle_anim) {
                    headerTitle = "VISUAL EMULATION";
                    headerValue = currentState.active_idle_anim.toUpperCase().replace('_', ' ');
                }
                
                alertTitle.innerText = headerTitle;
                alertValue.innerText = headerValue;
                alertBanner.style.background = bannerBg;
                alertBanner.style.border = bannerBorder;

                // Adjust glows/shadows based on speech amplitude
                const amp = currentState.amplitude || 0;
                let brightness = 15;
                if (currentState.speaking) {
                    brightness = 30 + amp * 70;
                } else if (currentState.thinking) {
                    brightness = 40 + Math.sin(Date.now() / 150) * 20;
                }
                
                // Pulsate eye ring glow matching the speaker amplitude
                eyeRing.style.boxShadow = `0 0 ${15 + (brightness/100)*25}px var(--glow-color)`;

            } catch (err) {
                console.error("Error fetching state:", err);
            }
        }

        setInterval(fetchState, 300);

        // Control API Calls
        async function triggerWake() {
            addChatBubble("Triggering verbal wake sequence...", 'chat-user');
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

        // Web Audio Recording
        let mediaStream = null;

        async function startMicRecording() {
            micBtn.classList.add('recording');
            micBtn.title = "Recording audio...";
            audioChunks = [];

            try {
                if (!audioContext) {
                    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                }
                
                mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const source = audioContext.createMediaStreamSource(mediaStream);
                const bufferSize = 4096;
                const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
                
                processor.onaudioprocess = function(e) {
                    const inputData = e.inputBuffer.getChannelData(0);
                    audioChunks.push(new Float32Array(inputData));
                };
                
                source.connect(processor);
                processor.connect(audioContext.destination);
                
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
            micBtn.title = "Hold to Speak (Web Mic)";

            if (micBtn.audioProcessor) {
                micBtn.audioProcessor.disconnect();
                micBtn.audioSource.disconnect();
            }
            if (mediaStream) {
                mediaStream.getTracks().forEach(track => track.stop());
            }

            if (audioChunks.length === 0) return;
            
            addChatBubble("[Vox input transmitted]", 'chat-user');
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

        function encodeWAV(chunks, sampleRate) {
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

            writeString(view, 0, 'RIFF');
            view.setUint32(4, 36 + samples.length * 2, true);
            writeString(view, 8, 'WAVE');
            writeString(view, 12, 'fmt ');
            view.setUint32(16, 16, true);
            view.setUint16(20, 1, true);
            view.setUint16(22, 1, true);
            view.setUint32(24, sampleRate, true);
            view.setUint32(28, sampleRate * 2, true);
            view.setUint16(32, 2, true);
            view.setUint16(34, 16, true);
            writeString(view, 36, 'data');
            view.setUint32(40, samples.length * 2, true);

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

