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

_latest_audio_bytes: bytes | None = None
_latest_audio_id: int = 0
_audio_lock = threading.Lock()


def publish_web_audio(wav_bytes: bytes) -> None:
    global _latest_audio_bytes, _latest_audio_id
    if not wav_bytes:
        return
    with _audio_lock:
        _latest_audio_bytes = wav_bytes
        _latest_audio_id = int(time.time() * 1000)


def get_latest_web_audio() -> tuple[bytes | None, int]:
    with _audio_lock:
        return _latest_audio_bytes, _latest_audio_id


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
        history = list(brain.get_history() or [])
        import re
        for item in history:
            if not isinstance(item, dict):
                continue
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
        try:
            self.original_stdout.write(s)
        except Exception:
            pass
        if s and s.strip():
            try:
                import re
                clean_s = re.sub(r'\x1b\[[0-9;]*[mK]', '', s.strip())
                now_str = time.strftime("%H:%M:%S")

                m_heard = re.match(r'^\[skull\]\s+Heard(?:\s*\(([^)]+)\))?:\s*(.+)$', clean_s)
                m_skull = re.match(r'^\[skull\]\s+([^:]+):\s*(.+)$', clean_s)

                if m_heard:
                    spk = m_heard.group(1) or "User"
                    txt = m_heard.group(2)
                    log_vox(spk, txt, timestamp=now_str)
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
            except Exception:
                pass
        return len(s) if s else 0

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


_psutil_lock = threading.Lock()


def get_ram_usage() -> str:
    try:
        with _psutil_lock:
            import psutil
            mem = psutil.virtual_memory()
            return f"{mem.percent:.1f}%"
    except Exception:
        return "42.5%"


def get_ram_total() -> str:
    try:
        with _psutil_lock:
            import psutil
            mem = psutil.virtual_memory()
            total_gb = mem.total / (1024**3)
            val = f"{total_gb:.1f}"
            if val.endswith('.0'):
                val = val[:-2]
            return f"{val} GB"
    except Exception:
        return "2 GB"


def get_storage_usage() -> str:
    try:
        with _psutil_lock:
            import psutil
            disk = psutil.disk_usage('/')
            return f"{disk.percent:.1f}%"
    except Exception:
        try:
            import os
            st = os.statvfs('/')
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            percent = (used / total) * 100
            return f"{percent:.1f}%"
        except Exception:
            return "61.2%"


def get_storage_total() -> str:
    try:
        with _psutil_lock:
            import psutil
            disk = psutil.disk_usage('/')
            total_gb = disk.total / (1024**3)
            val = f"{total_gb:.1f}"
            if val.endswith('.0'):
                val = val[:-2]
            return f"{val} GB"
    except Exception:
        try:
            import os
            st = os.statvfs('/')
            total = st.f_blocks * st.f_frsize
            val = f"{total / (1024**3):.1f}"
            if val.endswith('.0'):
                val = val[:-2]
            return f"{val} GB"
        except Exception:
            return "64 GB"


def get_cpu_usage() -> str:
    try:
        with _psutil_lock:
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
        if state in ("RUNNING", "PREPARE") or percent > 0:
            return {"text": f"{percent:.0f}%", "percent": percent}
        return {"text": state, "percent": percent}
    except Exception:
        return {"text": "UNAVAILABLE", "percent": 0.0}

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

_web_client_connected = False


def has_web_client_connected() -> bool:
    """Return True if any web client has connected to the Web Remote server."""
    return _web_client_connected


def test_api_key(provider: str, key: str) -> tuple[bool, str]:
    """Test an API key live with its respective provider."""
    if not key or not key.strip():
        return False, "API key cannot be empty."
    key = key.strip()
    provider = provider.lower().strip()

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return True, f"Anthropic API key valid! Response: '{msg.content[0].text.strip()}'"
        elif provider == "elevenlabs":
            import requests
            r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=8)
            if r.status_code == 200:
                voices = len(r.json().get("voices", []))
                return True, f"ElevenLabs API key valid! Access to {voices} voice profiles."
            else:
                return False, f"ElevenLabs API key invalid (HTTP {r.status_code})."
        elif provider == "openai":
            import requests
            r = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=8)
            if r.status_code == 200:
                return True, "OpenAI API key valid!"
            else:
                return False, f"OpenAI API key invalid (HTTP {r.status_code})."
        else:
            return False, f"Unknown API provider: '{provider}'."
    except Exception as e:
        return False, f"Verification failed: {e}"


class WebRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress automatic logging to console to keep main logs readable
        pass

    def _send_json(self, data: dict, status_code: int = 200) -> None:
        try:
            body = json.dumps(data, default=str).encode("utf-8")
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

    def _handle_root(self) -> None:
        body = HTML_CLIENT.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _handle_app_js(self) -> None:
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), "app.js"), "rb") as f:
                js_body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(js_body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(js_body)
        except Exception as e:
            print(f"Failed to serve app.js: {e}")
            self.send_response(404)
            self.end_headers()

    def _handle_api_state(self) -> None:
        from skull import display, temperature, brain
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

        from skull import quiet, mood, proximity
        master_name = str(config._OWNER_PROFILE.get("name") or "Unknown").upper()
        active_game = brain.get_current_game() if hasattr(brain, "get_current_game") else "None"
        if not active_game:
            active_game = "None"

        state_data = {
            "skull_name": config.SKULL_NAME,
            "display": disp_state if isinstance(disp_state, dict) else {},
            "temperature": temp or "Unavailable",
            "cpu": get_cpu_usage(),
            "ram": get_ram_usage(),
            "ram_total": get_ram_total(),
            "storage": get_storage_usage(),
            "storage_total": get_storage_total(),
            "master": master_name,
            "silent_mode": "ACTIVE" if quiet.is_silent() else "INACTIVE",
            "mood": mood.label() if hasattr(mood, "label") else "DUTIFUL",
            "fabricator": get_fabricator_status(),
            "active_game": str(active_game),
            "screensavers": display.get_screensaver_names() if hasattr(display, "get_screensaver_names") else [],
            "logs": get_logs(),
            "vox_logs": get_vox_logs(),
            "camera_active": (lambda: getattr(sys.modules.get("skull.camera"), "is_camera_active", lambda: False)())() if "skull.camera" in sys.modules else False,
            "audio_id": get_latest_web_audio()[1],
            "proximity": {
                "enabled": config.PROXIMITY_ENABLED,
                "available": proximity.available(),
                "distance_cm": round(proximity.get_latest_distance_cm(), 1) if proximity.get_latest_distance_cm() is not None else None,
                "summary": proximity.get_distance_summary_short(),
            },
            "wifi": (lambda: getattr(sys.modules.get("skull.wifi_provisioner"), "get_status", lambda: {})())() if "skull.wifi_provisioner" in sys.modules else {},
            "is_configured": config.is_configured(),
        }
        self._send_json(state_data)

    def _handle_wifi_status(self) -> None:
        from skull import wifi_provisioner
        self._send_json(wifi_provisioner.get_status())

    def _handle_wifi_scan(self) -> None:
        from skull import wifi_provisioner
        networks = wifi_provisioner.scan_networks()
        self._send_json({"networks": networks})

    def _handle_custom_image(self) -> None:
        from skull import display
        img_bytes = display.get_ocular_frame_bytes()
        if img_bytes:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_bytes)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(img_bytes)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_ocular_stream(self) -> None:
        from skull import display
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
                time.sleep(0.033)
        except Exception:
            pass

    def _handle_camera_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            from skull import camera
            import time
            while True:
                img_bytes = camera.get_camera_frame_bytes()
                if img_bytes:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(img_bytes)}\r\n\r\n".encode())
                    self.wfile.write(img_bytes)
                    self.wfile.write(b"\r\n")
                time.sleep(0.04)
        except Exception:
            pass

    def _handle_game_status(self) -> None:
        """GET /api/game/status — returns current Bard's Tale agent state."""
        try:
            from games.bardstale import agent as _bt_agent
            self._send_json(_bt_agent.get_status())
        except Exception as e:
            self._send_json({"running": False, "turn": 0, "last_action": "", "error": str(e)})

    def _handle_game_start(self) -> None:
        """POST /api/game/start — launch the autonomous Bard's Tale agent."""
        try:
            import pathlib
            content_length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(content_length).decode("utf-8")) if content_length else {}
            disk_dir = pathlib.Path(__file__).resolve().parent.parent / "games" / "bardstale" / "disks"
            # Allow caller to override disk path; otherwise pick first found disk
            disk_path = data.get("disk", "")
            if not disk_path:
                disks = sorted(
                    list(disk_dir.glob("*.dsk")) + list(disk_dir.glob("*.woz"))
                    + list(disk_dir.glob("*.nib"))
                ) if disk_dir.exists() else []
                disk_path = str(disks[0]) if disks else ""
            if not disk_path:
                self._send_json({"ok": False, "error": "No disk image found in games/bardstale/disks/"}, 400)
                return
            from games.bardstale import agent as _bt_agent
            if _bt_agent.is_running():
                self._send_json({"ok": False, "error": "Game already running"})
                return
            from skull import display as _disp
            import skull.main as _main
            _disp.start_game_display()
            _bt_agent.start(disk_path, _main._game_narrate)
            self._send_json({"ok": True, "disk": disk_path})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_game_stop(self) -> None:
        """POST /api/game/stop — stop the Bard's Tale agent."""
        try:
            from games.bardstale import agent as _bt_agent
            from skull import display as _disp
            _bt_agent.stop()
            _disp.stop_game_display()
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_GET(self) -> None:
        global _web_client_connected
        _web_client_connected = True

        path_clean = self.path.split("?")[0].rstrip("/")
        if not path_clean:
            path_clean = "/"

        get_routes = {
            "/": self._handle_root,
            "/api/app.js": self._handle_app_js,
            "/api/state": self._handle_api_state,
            "/api/wifi/status": self._handle_wifi_status,
            "/api/wifi/scan": self._handle_wifi_scan,
            "/api/custom_image.jpg": self._handle_custom_image,
            "/api/ocular_frame.jpg": self._handle_custom_image,
            "/api/ocular_stream.mjpeg": self._handle_ocular_stream,
            "/api/camera_stream.mjpeg": self._handle_camera_stream,
            "/api/game/status": self._handle_game_status,
        }

        handler = get_routes.get(path_clean)
        if handler:
            handler()
            return

        if self.path.startswith("/api/last_speech.wav"):
            wav_bytes, _ = get_latest_web_audio()
            if wav_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(wav_bytes)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if self.path.startswith("/api/camera_frame.jpg"):
            try:
                from skull import camera
                img_bytes = camera.get_camera_frame_bytes()
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
            except Exception:
                self.send_response(404)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def _handle_setup_test_key(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            provider = data.get("provider", "")
            key = data.get("key", "")
            success, msg = test_api_key(provider, key)
            self._send_json({"status": "ok" if success else "error", "message": msg})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_setup_save(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)

            settings_data = {}
            if "skull_name" in data:
                settings_data["SKULL_NAME"] = data["skull_name"]
            if "keys" in data:
                keys = data["keys"]
                if "anthropic" in keys and keys["anthropic"]:
                    settings_data["ANTHROPIC_API_KEY"] = keys["anthropic"]
                if "elevenlabs" in keys and keys["elevenlabs"]:
                    settings_data["ELEVENLABS_API_KEY"] = keys["elevenlabs"]
                if "elevenlabs_voice_id" in keys and keys["elevenlabs_voice_id"]:
                    settings_data["ELEVENLABS_VOICE_ID"] = keys["elevenlabs_voice_id"]
                if "openai" in keys and keys["openai"]:
                    settings_data["OPENAI_API_KEY"] = keys["openai"]

            config.save_settings(settings_data)

            if "skull.main" in sys.modules and hasattr(sys.modules["skull.main"], "stop_setup_repeater"):
                try:
                    sys.modules["skull.main"].stop_setup_repeater()
                except Exception:
                    pass

            if "owner" in data:
                config.save_owner_profile(data["owner"])

            if "wifi" in data and data["wifi"].get("ssid"):
                from skull import wifi_provisioner
                wifi_provisioner.connect_network(data["wifi"]["ssid"], data["wifi"].get("password"))
                wifi_provisioner.stop_hotspot()

            try:
                from skull import tts
                owner_name = data.get("owner", {}).get("name", "Master")
                announcement = f"Initialization complete, Master {owner_name}. Machine spirit online."
                wav = tts.synthesize_piper(announcement)
            except Exception as e:
                print(f"[web] Post-setup speech error: {e}")

            self._send_json({"status": "ok", "message": "Appliance initialized successfully!"})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_wifi_connect(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            ssid = data.get("ssid", "")
            password = data.get("password", "")
            from skull import wifi_provisioner
            success, msg = wifi_provisioner.connect_network(ssid, password)
            self._send_json({"status": "ok" if success else "error", "message": msg})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_wifi_hotspot(self) -> None:
        try:
            from skull import wifi_provisioner
            success, msg = wifi_provisioner.start_hotspot()
            self._send_json({"status": "ok" if success else "error", "message": msg})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_wake(self) -> None:
        request_wake()
        self._send_json({"status": "ok", "message": "Wake request triggered."})

    def _handle_screensaver(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            anim = data.get("animation", "").strip()
            if anim:
                from skull import display
                display.trigger_idle_animation(300.0, anim)
                log_vox("Omega-7", f"Executing cogitator visual emulation ({anim}).")
                self._send_json({"status": "ok", "message": f"Triggered screensaver: {anim}"})
            else:
                self._send_json({"status": "error", "message": "Animation parameter is empty."}, 400)
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_command(self) -> None:
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

    def _handle_upload_audio(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            wav_bytes = self.rfile.read(content_length)
            
            if len(wav_bytes) < 100:
                self._send_json({"status": "error", "message": "Audio file too short."}, 400)
                return
            
            def _process_web_audio(audio_data):
                try:
                    from skull import speaker_id, transcribe
                    speaker_name = speaker_id.identify_speaker(audio_data)
                    print(f"[web] Identified speaker from audio upload: {speaker_name}")
                    
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

    def do_POST(self) -> None:
        path_clean = self.path.split("?")[0].rstrip("/")

        post_routes = {
            "/api/setup/test_key": self._handle_setup_test_key,
            "/api/setup/save": self._handle_setup_save,
            "/api/wifi/connect": self._handle_wifi_connect,
            "/api/wifi/hotspot": self._handle_wifi_hotspot,
            "/api/wake": self._handle_wake,
            "/api/screensaver": self._handle_screensaver,
            "/api/command": self._handle_command,
            "/api/upload_audio": self._handle_upload_audio,
            "/api/game/start": self._handle_game_start,
            "/api/game/stop": self._handle_game_stop,
        }

        handler = post_routes.get(path_clean)
        if handler:
            handler()
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
                print("[web] Generating self-signed SSL certificate with SAN for secure audio capture context...")
                try:
                    san_ext = "subjectAltName=DNS:omega7,DNS:omega7.local,DNS:omega7.panther-firefighter.ts.net,IP:127.0.0.1"
                    subprocess.run([
                        "openssl", "req", "-new", "-newkey", "rsa:2048", "-days", "3650",
                        "-nodes", "-x509", "-keyout", key_file, "-out", cert_file,
                        "-subj", "/C=US/ST=Mars/L=Mechanicus/O=Adeptus/CN=omega7.panther-firefighter.ts.net",
                        "-addext", san_ext
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
            box-sizing: border-box;
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

        .header-title-row {
            width: 100%;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
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

        .master-header-tag {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            letter-spacing: 2px;
            color: var(--bright-green);
            text-shadow: 0 0 8px var(--glow-color);
        }

        .master-header-tag .master-label {
            color: var(--dim-green);
            font-size: 12px;
            letter-spacing: 1.5px;
        }

        .master-header-tag .master-value {
            color: var(--bright-green);
            font-weight: bold;
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
            flex-direction: column;
            gap: 12px;
            width: 100%;
            margin-top: 10px;
        }

        .pie-gauge-row {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            width: 100%;
            border: 2px double var(--border-color);
            background: rgba(17, 120, 35, 0.03);
            padding: 12px;
            box-sizing: border-box;
            border-radius: 4px;
        }

        .pie-gauge-item {
            border: 1px solid var(--border-color);
            background: rgba(17, 120, 35, 0.05);
            padding: 10px 4px;
            border-radius: 2px;
            box-shadow: inset 0 0 8px rgba(0,0,0,0.8);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 6px;
            width: 100%;
            box-sizing: border-box;
        }

        .gauge-label {
            color: rgba(56, 255, 88, 0.85);
            font-size: 10px;
            letter-spacing: 1.5px;
            font-weight: bold;
            text-align: center;
            text-shadow: 0 0 3px rgba(56, 255, 88, 0.4);
            white-space: nowrap;
        }

        .pie-chart-container {
            position: relative;
            width: 58px;
            height: 58px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .pie-chart {
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }

        .pie-bg {
            fill: rgba(0, 0, 0, 0.6);
            stroke: rgba(17, 120, 35, 0.3);
            stroke-width: 3.5;
        }

        .pie-fill {
            fill: none;
            stroke: var(--bright-green);
            stroke-width: 3.8;
            stroke-linecap: round;
            filter: drop-shadow(0 0 3px var(--bright-green));
            transition: stroke-dasharray 0.4s ease;
        }

        .gauge-val {
            position: absolute;
            font-size: 11px;
            font-weight: bold;
            color: var(--bright-green);
            text-shadow: 0 0 4px var(--glow-color);
            text-align: center;
        }

        .status-row {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            width: 100%;
        }

        .telemetry-item {
            border: 1px solid var(--border-color);
            background: rgba(17, 120, 35, 0.05);
            padding: 10px 14px;
            border-radius: 2px;
            box-shadow: inset 0 0 5px rgba(0,0,0,0.8);
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
            box-sizing: border-box;
        }

        .telemetry-item.text-only {
            justify-content: center;
            align-items: center;
            text-align: center;
            width: 100%;
            box-sizing: border-box;
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
            padding: 18px 20px 14px 20px;
            text-align: center;
            border-radius: 2px;
            position: relative;
            margin-bottom: 5px;
        }

        .alert-banner::before {
            content: "◆ COGITATOR MONITORING ACTIVE ◆";
            position: absolute;
            top: -10px;
            left: 50%;
            transform: translateX(-50%);
            background-color: var(--card-color);
            padding: 0 8px;
            font-size: 11px;
            color: var(--bright-green);
            letter-spacing: 2px;
            white-space: nowrap;
            z-index: 5;
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

        /* Right Column: Camera Optic Feed (Placeholder) */
        .camera-pane {
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

        .camera-screen {
            width: 270px;
            height: 270px;
            border: 4px double var(--border-color);
            position: relative;
            background-color: #000200;
            box-shadow: 0 0 20px rgba(56, 255, 88, 0.05), inset 0 0 25px rgba(0,0,0,0.95);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }

        .camera-placeholder-text {
            color: var(--dim-green);
            font-size: 11px;
            letter-spacing: 2px;
            text-align: center;
            line-height: 1.6;
            opacity: 0.7;
        }

        .camera-canvas {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        /* Ocular & Camera Bezel Tech Details */
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

        /* Full Width Section: Vox Control Panel (Under feeds) */
        .control-pane {
            grid-column: 1 / -1;
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 12px;
            border: 1px solid var(--border-color);
            padding: 15px;
            background: rgba(0,0,0,0.4);
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
            width: 16px;
            height: 16px;
            fill: var(--bright-green);
            transition: fill 0.2s ease;
        }

        button:hover .btn-svg {
            fill: #000;
        }

        button.mic-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 10px 14px;
            background-color: rgba(56, 255, 88, 0.08);
            border-color: var(--bright-green);
            flex-shrink: 0;
        }

        button.mic-btn.recording {
            background-color: #ff3838;
            border-color: #ff3838;
            color: #ffffff;
            text-shadow: none;
            animation: pulse-red 1.5s infinite;
        }

        button.mic-btn.recording .btn-svg {
            fill: #ffffff;
        }

        @keyframes pulse-red {
            0% { box-shadow: 0 0 0 0 rgba(255, 56, 56, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(255, 56, 56, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 56, 56, 0); }
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

        .aux-panel {
            grid-column: 1 / -1;
            width: 100%;
            border: 1px solid var(--border-color);
            background: rgba(17, 120, 35, 0.04);
            padding: 12px 16px;
            box-sizing: border-box;
            border-radius: 2px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 4px;
        }

        .aux-title {
            color: rgba(56, 255, 88, 0.85);
            font-size: 11px;
            letter-spacing: 2px;
            font-weight: bold;
            text-transform: uppercase;
        }

        .aux-controls {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            align-items: center;
        }

        .aux-item {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .aux-label {
            font-size: 11px;
            letter-spacing: 1.5px;
            color: var(--dim-green);
            white-space: nowrap;
        }

        .aux-panel select {
            background-color: rgba(0,0,0,0.7);
            border: 1px solid var(--border-color);
            color: var(--bright-green);
            padding: 6px 10px;
            font-family: inherit;
            font-size: 12px;
        }

        .aux-panel select:focus {
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

        /* Mobile Responsive Overrides (Must stay at bottom of style block) */
        @media (max-width: 768px) {
            html, body {
                overflow-x: hidden !important;
                overflow-y: auto !important;
                touch-action: pan-y !important;
                -webkit-overflow-scrolling: touch !important;
            }
            .screen {
                padding: 4px 2px !important;
                overflow: visible !important;
                touch-action: pan-y !important;
            }
            .container {
                grid-template-columns: 1fr !important;
                padding: 8px 4px !important;
                gap: 10px !important;
                width: 100% !important;
                max-width: 100% !important;
                overflow: visible !important;
                touch-action: pan-y !important;
            }
            .header {
                padding-bottom: 8px !important;
                margin-bottom: 6px !important;
                gap: 6px !important;
            }
            .header h1 {
                font-size: 13px !important;
                letter-spacing: 0px !important;
                flex-wrap: wrap !important;
                line-height: 1.2 !important;
                word-break: break-word !important;
            }
            .cog-logo {
                width: 16px !important;
                height: 16px !important;
                flex-shrink: 0 !important;
            }
            .telemetry {
                display: flex !important;
                flex-direction: column !important;
                gap: 8px !important;
                width: 100% !important;
                padding: 4px !important;
            }
            .pie-gauge-row {
                grid-template-columns: repeat(5, 1fr) !important;
                gap: 4px !important;
                padding: 6px 2px !important;
            }
            .pie-chart-container {
                width: 44px !important;
                height: 44px !important;
            }
            .gauge-label {
                font-size: 8px !important;
                letter-spacing: 0px !important;
            }
            .gauge-val {
                font-size: 9px !important;
            }
            .status-row {
                grid-template-columns: 1fr !important;
                gap: 6px !important;
            }
            .telemetry-item, .telemetry-item.text-only {
                width: 100% !important;
                min-width: 0 !important;
                max-width: 100% !important;
                box-sizing: border-box !important;
                padding: 10px 12px !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 6px !important;
            }
            .sensor-header {
                display: flex !important;
                flex-direction: row !important;
                justify-content: space-between !important;
                align-items: center !important;
                gap: 4px !important;
            }
            .telemetry-label {
                font-size: 11px !important;
                letter-spacing: 1px !important;
            }
            .telemetry-value {
                font-size: 12px !important;
                letter-spacing: 0px !important;
                word-break: break-word !important;
            }
            .alert-banner {
                padding: 12px 4px 8px 4px !important;
                width: 100% !important;
                box-sizing: border-box !important;
            }
            .alert-banner::before {
                font-size: 8px !important;
                letter-spacing: 0.5px !important;
                top: -9px !important;
                content: "◆ MONITORING ACTIVE ◆" !important;
            }
            .alert-title {
                font-size: 9px !important;
                letter-spacing: 0.5px !important;
            }
            .alert-value {
                font-size: 13px !important;
                letter-spacing: 0px !important;
                word-break: break-word !important;
                white-space: normal !important;
            }
            .ocular-pane, .camera-pane, .control-pane, .console-container {
                padding: 8px 6px !important;
            }
            .ocular-ring, .camera-screen {
                width: 220px !important;
                height: 220px !important;
                max-width: 100% !important;
            }
            .aux-panel {
                padding: 6px 6px !important;
            }
            .aux-controls {
                flex-direction: column !important;
                align-items: stretch !important;
            }
            .input-bar {
                flex-wrap: wrap !important;
                gap: 6px !important;
            }
            .input-bar input {
                width: 100% !important;
                flex: 1 1 100% !important;
                box-sizing: border-box !important;
            }
            .send-btn, .mic-btn {
                flex: 1 1 calc(50% - 4px) !important;
                text-align: center !important;
                justify-content: center !important;
                padding: 10px 6px !important;
            }
            .pane-title, .aux-title {
                font-size: 10px !important;
                letter-spacing: 0px !important;
                word-break: break-word !important;
            }
        }
    </style>
</head>
<body>
    <div class="screen">
        <div class="container">
            <div class="frame-bracket"></div>

            <!-- Header -->
            <div class="header">
                <div class="header-title-row">
                    <h1>
                        <!-- Wireframe SVG Cog Logo -->
                        <svg class="cog-logo" viewBox="0 0 100 100">
                            <path d="M50 20c-16.5 0-30 13.5-30 30s13.5 30 30 30 30-13.5 30-30-13.5-30-30-30zm0 10c11 0 20 9 20 20s-9 20-20 20-20-9-20-20 9-20 20-20z"/>
                            <path d="M50 0l6 14h-12zM50 100l6-14h-12zM0 50l14-6v12zM100 50l-14-6v12zM15 15l10 10-8 8zM85 85l-10-10 8-8zM15 85l10-10-8-8zM85 15l-10 10 8 8z"/>
                        </svg>
                        OMEGA-7 COGITATOR TERMINAL
                    </h1>
                    <div class="master-header-tag">
                        <span class="master-label">MASTER:</span>
                        <span id="master-val" class="master-value">UNKNOWN</span>
                    </div>
                </div>

                <div class="telemetry">
                    <div class="pie-gauge-row">
                        <div class="pie-gauge-item">
                            <span class="gauge-label">CPU</span>
                            <div class="pie-chart-container">
                                <svg class="pie-chart" viewBox="0 0 36 36">
                                    <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    <path id="cpu-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                </svg>
                                <span id="cpu-val" class="gauge-val">0%</span>
                            </div>
                        </div>
                        <div class="pie-gauge-item">
                            <span class="gauge-label">CORE TEMP</span>
                            <div class="pie-chart-container">
                                <svg class="pie-chart" viewBox="0 0 36 36">
                                    <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    <path id="temp-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                </svg>
                                <span id="temp-val" class="gauge-val">0°C</span>
                            </div>
                        </div>
                        <div class="pie-gauge-item">
                            <span class="gauge-label" id="ram-label">RAM</span>
                            <div class="pie-chart-container">
                                <svg class="pie-chart" viewBox="0 0 36 36">
                                    <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    <path id="ram-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                </svg>
                                <span id="ram-val" class="gauge-val">0%</span>
                            </div>
                        </div>
                        <div class="pie-gauge-item">
                            <span class="gauge-label" id="storage-label">STORAGE</span>
                            <div class="pie-chart-container">
                                <svg class="pie-chart" viewBox="0 0 36 36">
                                    <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    <path id="storage-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                </svg>
                                <span id="storage-val" class="gauge-val">0%</span>
                            </div>
                        </div>
                        <div class="pie-gauge-item">
                            <span class="gauge-label">FABRICATOR</span>
                            <div class="pie-chart-container">
                                <svg class="pie-chart" viewBox="0 0 36 36">
                                    <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    <path id="fabricator-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                </svg>
                                <span id="fabricator-val" class="gauge-val">0%</span>
                            </div>
                        </div>
                    </div>

                    <div class="status-row">
                        <div class="telemetry-item text-only">
                            <span class="telemetry-label">SILENT MODE</span>
                            <span id="silent-val" class="telemetry-value">INACTIVE</span>
                        </div>
                        <div class="telemetry-item text-only">
                            <span class="telemetry-label">DISPOSITION / MOOD</span>
                            <span id="mood-val" class="telemetry-value">DUTIFUL</span>
                        </div>
                        <div class="telemetry-item text-only">
                            <span class="telemetry-label">ACTIVE GAME</span>
                            <span id="game-val" class="telemetry-value">NONE</span>
                        </div>
                    </div>

                    <div class="telemetry-item" style="margin-top: 6px;">
                        <div class="sensor-header">
                            <span class="telemetry-label">LASER RANGEFINDER (MAX 8.0 METERS)</span>
                            <span id="range-val" class="telemetry-value">-- cm (-- m)</span>
                        </div>
                        <div class="sensor-bar-container" style="height: 10px; margin-top: 4px;">
                            <div id="range-bar" class="sensor-bar" style="width: 0%;"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 9px; color: var(--dim-green); margin-top: 2px; font-weight: bold;">
                            <span>0m</span>
                            <span>2m</span>
                            <span>4m</span>
                            <span>6m</span>
                            <span>8m</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Thematic Warning/Status Banner (Secret Level Style) -->
            <div class="alert-banner" id="alert-banner">
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

            <!-- Right column: Camera Optic Feed -->
            <div class="camera-pane">
                <div class="pane-title" style="width: 100%;">[ CAMERA OPTIC FEED ]</div>
                <div class="camera-screen" id="camera-screen">
                    <!-- Overlay Bezel Telemetry -->
                    <div class="ocular-bezel-text bezel-tl">CAM: 01</div>
                    <div class="ocular-bezel-text bezel-tr" id="cam-bezel-tr">FPS: --</div>
                    <div class="ocular-bezel-text bezel-bl" id="cam-bezel-bl">MODE: STANDBY</div>
                    <div class="ocular-bezel-text bezel-br">RESOL: 640x480</div>

                    <img class="camera-canvas" id="camera-stream" alt="Camera Feed" style="display: none;">
                    <div class="camera-placeholder-text" id="camera-standby">[ NO CAMERA STREAM ]<br>STANDBY</div>
                </div>
            </div>

            <!-- Right column: Control Room -->
            <div class="control-pane">
                <div class="pane-title">[ VOX CHANNEL LOGS ]</div>
                <div class="chat-container" id="chat-container">
                    <div class="chat-bubble chat-skull">System initialized. Awaiting commands, master.</div>
                </div>
                
                <div class="input-bar">
                    <input type="text" id="command-input" placeholder="Enter high-level command..." onkeydown="if(event.key === 'Enter') sendCommand()">
                    <button class="send-btn" onclick="sendCommand()">SEND</button>

                    <button class="mic-btn" id="mic-btn" onclick="toggleMicRecording()" title="Click to Record Web Mic Audio">
                        <svg class="btn-svg" viewBox="0 0 24 24" style="vertical-align: middle;">
                            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                        </svg>
                        <span id="mic-btn-label">REC</span>
                    </button>
                </div>
            </div>

            <!-- Auxiliary Controls Section (Above Telemetry Console Feed) -->
            <div class="aux-panel">
                <div class="aux-title">[ AUXILIARY COGITATOR CONTROLS ]</div>
                <div class="aux-controls">
                    <div class="aux-item">
                        <span class="aux-label">VISUAL EMULATION:</span>
                        <select id="screensaver-select">
                            <option value="">-- Select Screensaver --</option>
                        </select>
                        <button onclick="playScreensaver()">RUN</button>
                    </div>
                    <div class="aux-item">
                        <span class="aux-label">VOX AUDIO OUTPUT:</span>
                        <button id="web-audio-btn" onclick="toggleWebAudio()">🔊 WEB AUDIO: ENABLED</button>
                    </div>
                    <div class="aux-item">
                        <span class="aux-label">WI-FI PROVISIONING:</span>
                        <span id="wifi-status-text" style="font-size: 11px; margin-right: 8px;">[ DISCONNECTED ]</span>
                        <button onclick="scanWifiNetworks()">📶 SCAN</button>
                        <button onclick="toggleHotspot()">📡 AP HOTSPOT</button>
                    </div>
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

    <!-- Onboarding Setup Wizard Overlay Modal -->
    <div id="wizard-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.92); z-index: 20000; padding: 20px; box-sizing: border-box; overflow-y: auto;">
        <div style="max-width: 650px; margin: 40px auto; border: 2px solid var(--bright-green); background-color: var(--card-color); padding: 24px; box-shadow: 0 0 25px var(--glow-color);">
            <div style="border-bottom: 1px solid var(--border-color); padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
                <div style="font-weight: bold; font-size: 16px; color: var(--bright-green); letter-spacing: 1.5px;">◆ APPLIANCE INITIALIZATION WIZARD ◆</div>
                <div id="wizard-step-label" style="font-size: 11px; color: rgba(56,255,88,0.8); font-weight: bold;">STEP 1 OF 4</div>
            </div>

            <!-- Step 1: Wi-Fi Setup -->
            <div class="wizard-step" id="w-step-1">
                <p style="margin-bottom: 16px; font-size: 13px; color: rgba(56,255,88,0.9);">Welcome! Connect your Servo Skull to your home Wi-Fi network to enable remote access and machine spirit updates.</p>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">WI-FI NETWORK (SSID):</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="text" id="w-wifi-ssid" placeholder="Home Wi-Fi Name" style="flex-grow: 1; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                        <button onclick="scanWizardWifi()">📶 SCAN</button>
                    </div>
                </div>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">WI-FI PASSWORD:</label>
                    <input type="password" id="w-wifi-pass" placeholder="Network Password" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                </div>
                <div id="w-wifi-result" style="font-size: 11px; margin-bottom: 14px; min-height: 16px;"></div>
                <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                    <button style="background: rgba(56,255,88,0.2);" onclick="nextWizardStep(2)">NEXT: IDENTITY ➔</button>
                </div>
            </div>

            <!-- Step 2: Skull Identity & Archetype -->
            <div class="wizard-step" id="w-step-2" style="display: none;">
                <p style="margin-bottom: 16px; font-size: 13px; color: rgba(56,255,88,0.9);">Designate the unit's name and primary vocal personality archetype.</p>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">SKULL NAME / DESIGNATION:</label>
                    <input type="text" id="w-skull-name" value="Omega-7" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                </div>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">PERSONALITY ARCHETYPE:</label>
                    <select id="w-personality" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                        <option value="Imperial Servo Skull">Imperial Servo Skull (Adeptus Mechanicus / Warhammer 40k)</option>
                        <option value="Golden Retriever">Golden Retriever (Upbeat, Loyal & Enthusiastic)</option>
                        <option value="Custom Archetype">Custom Archetype</option>
                    </select>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 20px;">
                    <button onclick="nextWizardStep(1)">⬅ BACK</button>
                    <button style="background: rgba(56,255,88,0.2);" onclick="nextWizardStep(3)">NEXT: MASTER PROFILE ➔</button>
                </div>
            </div>

            <!-- Step 3: Master Personalization Profile -->
            <div class="wizard-step" id="w-step-3" style="display: none;">
                <p style="margin-bottom: 16px; font-size: 13px; color: rgba(56,255,88,0.9);">Tell the skull who it serves so it can address you by name and provide localized information.</p>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">YOUR NAME (MASTER):</label>
                    <input type="text" id="w-master-name" placeholder="e.g. Sean, Sarah" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                </div>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">CITY / LOCATION (FOR WEATHER):</label>
                    <input type="text" id="w-master-city" placeholder="e.g. Seattle, WA" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                </div>
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">PRIMARY INTERESTS / HOBBIES:</label>
                    <input type="text" id="w-master-interests" placeholder="e.g. 3D Printing, Warhammer 40k" style="width: 100%; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 20px;">
                    <button onclick="nextWizardStep(2)">⬅ BACK</button>
                    <button style="background: rgba(56,255,88,0.2);" onclick="nextWizardStep(4)">NEXT: API CREDENTIALS ➔</button>
                </div>
            </div>

            <!-- Step 4: API Credentials (BYO-Keys) -->
            <div class="wizard-step" id="w-step-4" style="display: none;">
                <p style="margin-bottom: 16px; font-size: 13px; color: rgba(56,255,88,0.9);">Enter your cloud API keys. Test each key to verify before finishing initialization.</p>
                
                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">ANTHROPIC API KEY (REQUIRED FOR CLAUDE BRAIN):</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="w-key-anthropic" placeholder="sk-ant-api03-..." style="flex-grow: 1; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                        <button onclick="testWizardKey('anthropic')">TEST KEY</button>
                    </div>
                    <div id="w-res-anthropic" style="font-size: 11px; margin-top: 4px; min-height: 14px;"></div>
                </div>

                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">ELEVENLABS API KEY (OPTIONAL CLOUD VOICE):</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="w-key-elevenlabs" placeholder="Optional ElevenLabs API Key" style="flex-grow: 1; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                        <button onclick="testWizardKey('elevenlabs')">TEST KEY</button>
                    </div>
                    <div id="w-res-elevenlabs" style="font-size: 11px; margin-top: 4px; min-height: 14px;"></div>
                </div>

                <div style="margin-bottom: 14px;">
                    <label style="display: block; font-size: 11px; font-weight: bold; margin-bottom: 4px;">OPENAI API KEY (OPTIONAL):</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="password" id="w-key-openai" placeholder="Optional OpenAI API Key" style="flex-grow: 1; background: rgba(0,0,0,0.7); border: 1px solid var(--border-color); padding: 8px; color: var(--bright-green);">
                        <button onclick="testWizardKey('openai')">TEST KEY</button>
                    </div>
                    <div id="w-res-openai" style="font-size: 11px; margin-top: 4px; min-height: 14px;"></div>
                </div>

                <div style="display: flex; justify-content: space-between; margin-top: 20px;">
                    <button onclick="nextWizardStep(3)">⬅ BACK</button>
                    <button style="background: var(--bright-green); color: #000; font-size: 13px;" onclick="finishWizard()">⚙️ INITIALIZE MACHINE SPIRIT</button>
                </div>
            </div>
        </div>
    </div>


    <script src="/api/app.js"></script></script>


</body>
</html>
"""

