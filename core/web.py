from __future__ import annotations
from core import web_campaign
import http.server
import os
import socketserver
import threading
import json
import queue
import time
import io
import sys
import collections
from pathlib import Path
from core import config

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


# ── Web remote access control ─────────────────────────────────────────────────────
# Every page, API route and stream requires a login, except while the unit is still
# unconfigured (the first-run setup wizard).
#
# Logging in takes a 4-digit code that only exists while someone near the skull has
# asked for it ("show the web access code"): it is shown large on the eye, never
# spoken or logged, is fresh each time, expires after ACCESS_CODE_TTL seconds and is
# destroyed after ACCESS_CODE_MAX_TRIES wrong guesses. A successful login gives the
# browser its own random session key (HttpOnly cookie, valid a year), so the short
# code is only ever used to sign in. Scripts can send "Authorization: Bearer <key>".
_AUTH_COOKIE = "omega7_session"
# Branding assets served without a session, so a phone can install the
# terminal to its home screen from the login screen itself. None of them
# reveal anything about the unit beyond its name.
_PUBLIC_ASSETS = frozenset({
    "/manifest.webmanifest",
    "/favicon.svg",
    "/static/icon-180.png",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/static/icon-maskable-512.png",
})
ACCESS_CODE_TTL = 600.0
ACCESS_CODE_MAX_TRIES = 5
_SESSION_MAX_AGE = 365 * 24 * 3600
_MAX_SESSIONS = 50
_auth_lock = threading.Lock()
_access_code: str | None = None
_access_code_expires = 0.0
_access_code_failures = 0
_sessions: dict[str, float] | None = None   # sha256(session key) -> created (epoch s)
_login_failures: collections.deque = collections.deque()
_LOGIN_FAILURE_WINDOW = 300.0
_LOGIN_FAILURE_LIMIT = 10
_https_enabled = False


def issue_access_code() -> str:
    """Create a fresh 4-digit sign-in code (replacing any previous one) and return it."""
    global _access_code, _access_code_expires, _access_code_failures
    import secrets
    with _auth_lock:
        _access_code = f"{secrets.randbelow(10000):04d}"
        _access_code_expires = time.time() + ACCESS_CODE_TTL
        _access_code_failures = 0
    print("[web] Issued a web remote sign-in code (shown on the eye).")
    return _access_code


def _check_access_code(candidate: str) -> bool:
    """True if `candidate` is the live code. Wrong guesses count toward destroying it."""
    global _access_code, _access_code_failures
    import hmac
    digits = "".join(ch for ch in (candidate or "") if ch.isdigit())
    with _auth_lock:
        if _access_code is None or time.time() > _access_code_expires:
            _access_code = None
            return False
        if hmac.compare_digest(digits, _access_code):
            _access_code = None  # single use
            return True
        _access_code_failures += 1
        if _access_code_failures >= ACCESS_CODE_MAX_TRIES:
            _access_code = None
            print("[web] Too many wrong sign-in codes — code destroyed; ask the skull for a new one.")
        return False


def _session_hash(key: str) -> str:
    import hashlib
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _load_sessions() -> dict[str, float]:
    global _sessions
    if _sessions is None:
        try:
            data = json.loads(config.data_path("web_sessions.json").read_text(encoding="utf-8"))
            _sessions = {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _sessions = {}
    return _sessions


def _new_session() -> str:
    """Create and persist a session; only its hash is stored on disk."""
    import secrets
    key = secrets.token_urlsafe(32)
    with _auth_lock:
        sessions = _load_sessions()
        now = time.time()
        for h in [h for h, t in sessions.items() if now - t > _SESSION_MAX_AGE]:
            del sessions[h]
        sessions[_session_hash(key)] = now
        for h, _ in sorted(sessions.items(), key=lambda kv: kv[1])[:-_MAX_SESSIONS]:
            del sessions[h]
        config.atomic_write(config.data_path("web_sessions.json"), json.dumps(sessions), mode=0o600)
    return key


def _session_valid(key: str) -> bool:
    if not key:
        return False
    with _auth_lock:
        created = _load_sessions().get(_session_hash(key))
    return created is not None and time.time() - created <= _SESSION_MAX_AGE


def _login_locked_out() -> bool:
    now = time.time()
    with _auth_lock:
        while _login_failures and now - _login_failures[0] > _LOGIN_FAILURE_WINDOW:
            _login_failures.popleft()
        return len(_login_failures) >= _LOGIN_FAILURE_LIMIT


def _record_login_failure() -> None:
    with _auth_lock:
        _login_failures.append(time.time())


_LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#04120a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Omega-7">
<title>Omega-7 Access</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/static/icon-180.png">
<style>
:root{--acc:#46ff78;--ink:#dcffe6;--ink-3:#65b47e;--line:rgba(70,255,120,.22)}
*{box-sizing:border-box;margin:0}
body{min-height:100svh;display:grid;place-items:center;padding:24px;
background:radial-gradient(900px 560px at 50% -10%,rgba(70,255,120,.07),transparent 70%),#020a05;
color:var(--ink);font-family:'Share Tech Mono',ui-monospace,'Courier New',monospace}
.crt{position:fixed;inset:0;pointer-events:none;z-index:2;
background:repeating-linear-gradient(180deg,rgba(0,0,0,0) 0 2px,rgba(0,0,0,.22) 2px 4px)}
form{position:relative;z-index:3;width:min(380px,100%);display:flex;flex-direction:column;gap:14px;
padding:28px;border:1px solid var(--line);border-radius:12px;
background:linear-gradient(180deg,#0a1d10,#061308);box-shadow:0 30px 70px -40px #000}
.sigil{width:46px;height:46px;fill:var(--acc);filter:drop-shadow(0 0 10px rgba(70,255,120,.45));
animation:spin 24s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.sigil{animation:none}}
h1{font-size:15px;letter-spacing:.18em;text-transform:uppercase}
.sub{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--ink-3)}
input{width:100%;background:rgba(0,0,0,.6);color:var(--ink);border:1px solid var(--line);
border-radius:6px;padding:14px;font:600 24px/1 'Share Tech Mono',monospace;letter-spacing:.5em;
text-align:center;text-indent:.5em}
input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px rgba(70,255,120,.16)}
button{background:var(--acc);color:#021007;border:0;border-radius:6px;padding:13px 16px;
font:700 12px/1 'Share Tech Mono',monospace;letter-spacing:.16em;text-transform:uppercase;cursor:pointer}
button:hover{background:#6bffa0}
button:focus-visible{outline:2px solid var(--acc);outline-offset:3px}
.err{color:#ff5f4a;font-size:12px;line-height:1.5}
.hint{color:var(--ink-3);font-size:11.5px;line-height:1.6}
</style></head><body>
<div class="crt" aria-hidden="true"></div>
<form method="post" action="/login">
<div style="display:flex;align-items:center;gap:14px">
<svg class="sigil" viewBox="0 0 100 100" aria-hidden="true">
<path d="M50 20c-16.5 0-30 13.5-30 30s13.5 30 30 30 30-13.5 30-30-13.5-30-30-30zm0 10c11 0 20 9 20 20s-9 20-20 20-20-9-20-20 9-20 20-20z"/>
<path d="M50 0l6 14h-12zM50 100l6-14h-12zM0 50l14-6v12zM100 50l-14-6v12zM15 15l10 10-8 8zM85 85l-10-10 8-8zM15 85l10-10-8-8zM85 15l-10 10 8 8z"/>
</svg>
<div><h1>Omega-7</h1><div class="sub">Access rite</div></div>
</div>
__MESSAGE__
<label for="code" class="sub">Four-digit access code</label>
<input id="code" name="code" placeholder="0000" inputmode="numeric" pattern="[0-9]*" maxlength="4"
 autocomplete="one-time-code" autofocus aria-describedby="code-hint">
<input type="hidden" name="next" value="__NEXT__">
<button type="submit">Authenticate</button>
<p class="hint" id="code-hint">Ask the skull: &ldquo;show the web access code&rdquo;. The code lasts 10 minutes.</p>
</form></body></html>"""


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
    try:
        from core import db
        db.kv_set("telemetry_vox", list(_vox_buffer))
    except Exception:
        pass


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
        from core import brain
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
        if not _vox_buffer:
            try:
                from core import db
                items = db.kv_get("telemetry_vox", [])
                if isinstance(items, list) and items:
                    return items
            except Exception:
                pass
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
        res = list(_log_buffer)
        if not res:
            try:
                from core import db
                items = db.kv_get("telemetry_logs", [])
                if isinstance(items, list) and items:
                    return items
            except Exception:
                pass
        return res


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
            if pct > 0.0:
                return f"{pct:.1f}%"
    except Exception:
        pass

    try:
        import os
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        pct = min(100.0, max(0.0, (load / cores) * 100.0))
        return f"{pct:.1f}%"
    except Exception:
        return "5.0%"


def get_fabricator_status() -> dict:
    try:
        from core import bambu_ctrl
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

_TLS_HANDSHAKE_TIMEOUT = 15.0   # seconds a client gets to finish the TLS handshake
_CONNECTION_IDLE_TIMEOUT = 60.0  # seconds a connection may sit idle mid-request


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded server that does the TLS handshake on each connection's own worker
    thread. Wrapping the listening socket instead would run every handshake inside
    accept() on the single serving thread, so one client that connects and says
    nothing would freeze the whole remote."""
    daemon_threads = True
    ssl_context = None

    def finish_request(self, request, client_address):
        if self.ssl_context is None:
            request.settimeout(_CONNECTION_IDLE_TIMEOUT)
            return super().finish_request(request, client_address)
        import ssl
        request.settimeout(_TLS_HANDSHAKE_TIMEOUT)
        try:
            tls = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # failed or stalled handshake: drop just this connection
        try:
            tls.settimeout(_CONNECTION_IDLE_TIMEOUT)
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

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
    _MAX_BODY_BYTES = 1_048_576

    def _read_body(self, max_bytes: int | None = None) -> str | None:
        limit = max_bytes or self._MAX_BODY_BYTES
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > limit:
            self.send_response(413)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "body too large"}')
            return None
        if content_length <= 0:
            return "{}"
        return self.rfile.read(content_length).decode("utf-8")

    def log_message(self, format, *args):
        pass

    # ── access control ────────────────────────────────────────────────────────
    def _is_authenticated(self) -> bool:
        if not config.is_configured():
            return True  # first-run setup wizard must work before anyone has the code
        from http.cookies import SimpleCookie
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if _AUTH_COOKIE in cookie and _session_valid(cookie[_AUTH_COOKIE].value):
                return True
        except Exception:
            pass
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and _session_valid(auth[7:].strip())

    # Request bodies are capped before any handler reads them (handlers read
    # Content-Length bytes into memory): 10 MB for recorded audio, 1 MB otherwise.
    _BODY_LIMITS = {"/api/upload_audio": 10 * 1024 * 1024}
    _DEFAULT_BODY_LIMIT = 1024 * 1024

    def _body_size_ok(self, path: str) -> bool:
        raw = self.headers.get("Content-Length")
        if raw is None:
            return True  # no body; handlers treat a missing length as empty
        try:
            length = int(raw)
        except ValueError:
            length = -1
        limit = self._BODY_LIMITS.get(path, self._DEFAULT_BODY_LIMIT)
        if length < 0 or length > limit:
            self.close_connection = True
            self._send_json({"error": f"request body must be 0-{limit} bytes"}, 413 if length > limit else 400)
            return False
        return True

    def _is_cross_site(self) -> bool:
        """True for requests another website caused the browser to send."""
        if self.headers.get("Sec-Fetch-Site", "") == "cross-site":
            return True
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            from urllib.parse import urlparse
            return urlparse(origin).netloc.lower() != (self.headers.get("Host") or "").lower()
        return False

    def _set_auth_cookie_and_redirect(self, location: str) -> None:
        cookie = f"{_AUTH_COOKIE}={_new_session()}; Path=/; Max-Age={_SESSION_MAX_AGE}; HttpOnly; SameSite=Lax"
        if _https_enabled:
            cookie += "; Secure"
        self.send_response(303)
        self.send_header("Set-Cookie", cookie)
        self.send_header("Location", location if location.startswith("/") and not location.startswith("//") else "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_login_page(self, status: int = 200, message: str = "", next_path: str = "/") -> None:
        import html
        body = (_LOGIN_PAGE.replace("__MESSAGE__", f'<p class="err">{html.escape(message)}</p>' if message else "")
                .replace("__NEXT__", html.escape(next_path, quote=True))).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _attempt_login(self, code: str, next_path: str) -> None:
        if _login_locked_out():
            self._send_login_page(429, "Too many attempts. Wait a few minutes.", next_path)
            return
        if code and _check_access_code(code):
            print("[web] Web remote login succeeded.")
            self._set_auth_cookie_and_redirect(next_path)
        else:
            _record_login_failure()
            print("[web] Web remote login failed.")
            self._send_login_page(401, "Access denied.", next_path)

    def _guard(self, method: str) -> bool:
        """Run access control. Returns True if the request was fully handled here."""
        from urllib.parse import urlsplit, parse_qs
        parts = urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"
        query = parse_qs(parts.query)

        if method != "GET" and self._is_cross_site():
            self._send_json({"error": "cross-site request refused"}, 403)
            return True
        if method != "GET" and not self._body_size_ok(path):
            return True
        if path == "/logout":
            self.send_response(303)
            self.send_header("Set-Cookie", f"{_AUTH_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if path == "/login":
            if method == "POST":
                from urllib.parse import parse_qs as _pq
                length = max(0, min(int(self.headers.get("Content-Length", 0) or 0), 4096))
                form = _pq(self.rfile.read(length).decode("utf-8", "replace"))
                self._attempt_login(form.get("code", [""])[0], form.get("next", ["/"])[0])
            elif "code" in query:
                self._attempt_login(query["code"][0], query.get("next", ["/"])[0])
            else:
                self._send_login_page(next_path=query.get("next", ["/"])[0])
            return True
        if "code" in query and method == "GET":
            # Login link, e.g. https://omega7:8080/?code=XXXX-XXXX-XXXX-XXXX
            self._attempt_login(query["code"][0], path)
            return True
        if method == "GET" and path in _PUBLIC_ASSETS:
            return False
        if self._is_authenticated():
            return False
        if method == "GET" and not (path.startswith("/api/") or path.startswith("/static/")
                                    or path.startswith("/asset/") or "." in path.rsplit("/", 1)[-1]):
            from urllib.parse import quote
            self.send_response(303)
            self.send_header("Location", f"/login?next={quote(path)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send_json({"error": "login required"}, 401)
        return True

    def _send_json(self, data: dict, status_code: int = 200) -> None:
        try:
            body = json.dumps(data, default=str).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print(f"[web] send_json error: {e}")

    def do_OPTIONS(self):
        # The remote is same-origin only: no CORS grants to other websites.
        self.send_response(204)
        self.send_header("Content-Length", "0")
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

    def _handle_module_viewer(self) -> None:
        self._send_page("module_viewer.html")

    def _handle_campaign_page(self) -> None:
        self._send_page("static/campaign.html")

    def _send_page(self, relative_path: str) -> None:
        """Serve one of the book-styled pages from core/."""
        import os
        try:
            target = os.path.join(os.path.dirname(__file__), *relative_path.split("/"))
            with open(target, "r", encoding="utf-8") as f:
                html_body = f.read()
            body = html_body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error loading page: {e}".encode("utf-8"))

    def _handle_static(self) -> None:
        """Serve a front-end asset from core/static.

        The 40K terminal client is embedded in this module as a string, but the
        book-styled campaign and module pages are large enough that keeping
        their CSS and JS as real files is worth a route of their own.
        """
        import os
        try:
            rel = self.path.split("?")[0][len("/static/"):]
            base = os.path.join(os.path.dirname(__file__), "static")
            target = os.path.abspath(os.path.join(base, rel))
            if not target.startswith(os.path.abspath(base) + os.sep) or not os.path.isfile(target):
                self.send_response(404)
                self.end_headers()
                return
            mime = {
                "css": "text/css; charset=utf-8",
                "js": "application/javascript; charset=utf-8",
                "svg": "image/svg+xml",
                "png": "image/png",
                "woff2": "font/woff2",
            }.get(target.rsplit(".", 1)[-1].lower(), "application/octet-stream")
            with open(target, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(500)
            self.end_headers()

    def _handle_rules_image(self) -> None:
        import os
        try:
            rel_path = self.path.split("?")[0].replace("/rules_images/", "")
            rules_base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "games", "wfrp", "rules"))
            img_path = os.path.abspath(os.path.join(rules_base, rel_path))
            if not img_path.startswith(rules_base + os.sep) and img_path != rules_base:
                self.send_response(403)
                self.end_headers()
                return
            if os.path.exists(img_path) and os.path.isfile(img_path):
                with open(img_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                ext = os.path.splitext(img_path)[1].lower()
                mime = "image/png"
                if ext in [".jpg", ".jpeg"]: mime = "image/jpeg"
                elif ext == ".webp": mime = "image/webp"
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception:
            self.send_response(500)
            self.end_headers()

    def _handle_module_image(self) -> None:
        """Serve a module asset addressed by its repository-relative path.

        Asset paths are stored in the database relative to the repository root
        ("games/wfrp/rules/modules/<slug>/images/x.png") so that the database
        can be built on a workstation and served from the Pi. The canonical URL
        is therefore /asset/<that path>.

        The older /images/modules/<...> form is kept working for anything still
        linking to it; it was resolving against games/ and so pointed at
        games/images/modules/<...>, which has never existed.
        """
        import os
        try:
            rel_path = self.path.split("?")[0]
            repo_base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            games_base = os.path.join(repo_base, "games")

            if rel_path.startswith("/asset/"):
                base = repo_base
                rel_path = rel_path[len("/asset/"):]
            else:
                base = games_base
                rel_path = rel_path.lstrip("/")

            img_path = os.path.abspath(os.path.join(base, rel_path))
            # Only ever serve artwork out of the games tree, whichever form the
            # request took.
            if not img_path.startswith(games_base + os.sep):
                self.send_response(403)
                self.end_headers()
                return
            ext = img_path.rsplit(".", 1)[-1].lower()
            mime = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
            }.get(ext)
            # Images only: never the campaign database, source code or other files.
            if mime is None:
                self.send_response(404)
                self.end_headers()
                return
            if os.path.exists(img_path) and os.path.isfile(img_path):
                with open(img_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("X-Content-Type-Options", "nosniff")
                if ext == "svg":
                    # SVG can carry script; sandbox it if opened directly.
                    self.send_header("Content-Security-Policy", "sandbox")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception:
            self.send_response(500)
            self.end_headers()

    _FAVICON = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect width="100" height="100" rx="18" fill="#04120a"/>'
        '<g fill="#46ff78">'
        '<path d="M50 24c-14.4 0-26 11.6-26 26s11.6 26 26 26 26-11.6 26-26-11.6-26-26-26zm0 9'
        'c9.4 0 17 7.6 17 17s-7.6 17-17 17-17-7.6-17-17 7.6-17 17-17z"/>'
        '<path d="M50 6l5 13H45zM50 94l5-13H45zM6 50l13-5v10zM94 50l-13-5v10z'
        'M19 19l9 9-7 7zM81 81l-9-9 7-7zM19 81l9-9-7-7zM81 19l-9 9 7 7z"/>'
        '<circle cx="50" cy="50" r="8"/>'
        '</g></svg>'
    )

    def _send_asset(self, body: bytes, content_type: str, max_age: int = 86400) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"public, max-age={max_age}")
        self.end_headers()
        self.wfile.write(body)

    def _handle_favicon(self) -> None:
        self._send_asset(self._FAVICON.encode("utf-8"), "image/svg+xml")

    def _handle_manifest(self) -> None:
        """The web-app manifest, so the terminal installs to a phone home screen."""
        name = str(config.SKULL_NAME or "Omega-7")
        manifest = {
            "name": f"{name} Cogitator Terminal",
            "short_name": name,
            "description": f"Remote terminal for the {name} servo-skull.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#020a05",
            "theme_color": "#04120a",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": "/static/icon-maskable-512.png", "sizes": "512x512",
                 "type": "image/png", "purpose": "maskable"},
            ],
        }
        self._send_asset(json.dumps(manifest).encode("utf-8"), "application/manifest+json", 3600)

    def _handle_camera_capture(self) -> None:
        """Take a fresh frame through the optic and return it as a JPEG.

        A POST because it works the hardware: it wakes the sensor, waits for
        auto-exposure to settle and publishes the frame, so the ocular feed and
        anything else watching see the same picture.
        """
        try:
            from core import camera
            data, reason = camera.capture_still()
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 503)
            return
        if not data:
            self._send_json({"status": "error", "message": reason}, 503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(data)

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
        from core import display, temperature, brain
        try:
            disp_state = display.get_state()
        except Exception:
            disp_state = {}

        try:
            t_val = temperature.read_temp_c()
            if t_val is not None:
                temp = f"{t_val:.1f}°C"
            else:
                temp = "42.0°C"
        except Exception:
            temp = "Unavailable"

        from core import quiet, mood, proximity
        master_name = str(config._OWNER_PROFILE.get("name") or "Unknown").upper()
        active_game = brain.get_current_game() if hasattr(brain, "get_current_game") else "None"
        if not active_game:
            active_game = "None"

        def get_proximity():
            # Read the live in-memory reading; it is no longer mirrored to SQLite.
            return {
                "enabled": config.PROXIMITY_ENABLED,
                "available": proximity.available(),
                "distance_cm": round(proximity.get_latest_distance_cm(), 1) if proximity.get_latest_distance_cm() is not None else None,
                "summary": proximity.get_distance_summary_short(),
            }

        state_data = {
            "skull_name": config.SKULL_NAME,
            "display": disp_state if isinstance(disp_state, dict) else {},
            "temperature": temp or "Unavailable",
            "power": temperature.power_status(),
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
            "camera_active": (lambda: getattr(sys.modules.get("core.camera"), "is_camera_active", lambda: False)())() if "core.camera" in sys.modules else (config.data_path("latest_frame.jpg").exists() and (time.time() - config.data_path("latest_frame.jpg").stat().st_mtime) < 60.0),
            "audio_id": get_latest_web_audio()[1],
            "proximity": get_proximity(),
            "wifi": (lambda: getattr(sys.modules.get("core.wifi_provisioner"), "get_status", lambda: {})())() if "core.wifi_provisioner" in sys.modules else {},
            "is_configured": config.is_configured(),
        }
        self._send_json(state_data)

    def _handle_wifi_status(self) -> None:
        from core import wifi_provisioner
        self._send_json(wifi_provisioner.get_status())

    def _handle_wifi_scan(self) -> None:
        from core import wifi_provisioner
        networks = wifi_provisioner.scan_networks()
        self._send_json({"networks": networks})

    def _handle_custom_image(self) -> None:
        from core import display
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
        from core import display
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
            from core import camera
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
        """GET /api/game/status — current Bard's Tale agent state."""
        try:
            from games.bardstale import agent as _bt_agent
            self._send_json(_bt_agent.get_status())
        except Exception as e:
            self._send_json({"running": False, "error": str(e)})

    def _handle_game_start(self) -> None:
        """POST /api/game/start {"new": bool} — Omega-7 starts playing (resumes by default)."""
        try:
            data = self._read_json() or {}
            from games.bardstale import agent as _bt_agent
            from core import display as _disp
            # The running service is `python -m core.main` (__main__); importing
            # core.main would load a second copy with its own speech lock.
            _main = sys.modules.get("__main__")
            if not hasattr(_main, "_game_narrate"):
                import core.main as _main
            problem = _bt_agent.start(_main._game_narrate, new_game=bool(data.get("new")))
            if problem:
                self._send_json({"ok": False, "error": problem}, 400)
                return
            _disp.start_game_display()
            self._send_json({"ok": True})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_game_stop(self) -> None:
        """POST /api/game/stop — stop playing (progress is saved)."""
        try:
            from games.bardstale import agent as _bt_agent
            from core import display as _disp
            _bt_agent.stop()
            _disp.stop_game_display()
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)


    def _handle_campaign_load(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            name = data.get("name", "")
            from games.wfrp import campaign
            loaded = campaign.load_campaign(name, set_active=True)
            self._send_json({"ok": True, "active_campaign": loaded})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_new(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            name = data.get("name", "New Campaign")
            adventure = data.get("adventure", "")
            from games.wfrp import campaign
            created = campaign.new_campaign(name, adventure=adventure)
            self._send_json({"ok": True, "active_campaign": created})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_update(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            from games.wfrp import campaign
            active = campaign.get_active_campaign()
            if not active:
                self._send_json({"ok": False, "error": "No active campaign"}, 400)
                return
            for key in ("adventure", "current_location", "party_ambition_short", "party_ambition_long", "notes"):
                if key in data:
                    active[key] = data[key]
            campaign.save_campaign(active)
            self._send_json({"ok": True, "active_campaign": active})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)


    def _handle_campaign_character_delete(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            char_name = data.get("name", "").strip()
            from games.wfrp import campaign
            active = campaign.get_active_campaign()
            if not active:
                self._send_json({"ok": False, "error": "No active campaign"}, 400)
                return
            if char_name:
                campaign.delete_character(char_name)
            updated = campaign.get_active_campaign()
            self._send_json({"ok": True, "active_campaign": updated})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_character_upsert(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            char_dict = json.loads(raw_body)
            from games.wfrp import campaign
            active = campaign.get_active_campaign()
            if not active:
                self._send_json({"ok": False, "error": "No active campaign"}, 400)
                return
            campaign.upsert_character(char_dict)
            self._send_json({"ok": True, "active_campaign": campaign.get_active_campaign()})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_roll_char(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            race = data.get("race", "human")
            from games.wfrp import campaign
            race_key = campaign.resolve_race(race) or "human"
            char_block = campaign.roll_characteristics(race_key)
            self._send_json({"ok": True, "character_block": char_block})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)


    def _handle_campaign_npc_add(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            from games.wfrp import campaign, db
            active = campaign.get_active_campaign()
            if not active:
                self._send_json({"ok": False, "error": "No active campaign"}, 400)
                return
            slug = active.get("slug", "shadows-over-reikland")
            res = db.add_npc(slug, data.get("name", "NPC"), data.get("role_career", ""), data.get("disposition", "Neutral"), data.get("secrets_lore", ""), data.get("notes", ""))
            updated = campaign.get_active_campaign()
            self._send_json({"ok": True, "npc": res, "active_campaign": updated})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_timeline_add(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            data = json.loads(raw_body)
            from games.wfrp import campaign, db
            active = campaign.get_active_campaign()
            if not active:
                self._send_json({"ok": False, "error": "No active campaign"}, 400)
                return
            slug = active.get("slug", "shadows-over-reikland")
            db.add_timeline_event(slug, data.get("event_summary", ""), data.get("in_game_date", ""))
            updated = campaign.get_active_campaign()
            self._send_json({"ok": True, "active_campaign": updated})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_campaign_get(self) -> None:
        try:
            from games.wfrp import campaign
            active = campaign.get_active_campaign()
            c_list = campaign.list_campaigns()
            if not active and c_list:
                first_name = c_list[0].get("name") or c_list[0].get("slug")
                if first_name:
                    active = campaign.load_campaign(first_name, set_active=True)
            self._send_json({"ok": True, "active_campaign": active, "campaigns": c_list})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _read_json(self) -> dict:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw_body) if raw_body.strip() else {}
        except Exception:
            pass
        return {}

    def _handle_memory_get(self) -> None:
        try:
            from core import memory, config
            p = None
            if "?" in self.path:
                import urllib.parse
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                if "personality" in qs:
                    p = qs["personality"][0]
            active_p = p or config.get_personality_key()
            longterm = memory.load_longterm(personality=active_p)
            shortterm = memory.load(personality=active_p)
            self._send_json({"ok": True, "personality": active_p, "longterm": longterm, "shortterm": shortterm})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_memory_add(self) -> None:
        try:
            data = self._read_json() or {}
            fact = data.get("fact", "").strip()
            longterm = data.get("longterm", True)
            p = data.get("personality")
            if not fact:
                self._send_json({"ok": False, "error": "Fact is empty"}, 400)
                return
            from core import db, memory
            if longterm:
                msg = memory.remember(fact, personality=p)
            else:
                db.add_memory_fact(fact, longterm=False, personality=p)
                msg = f"Added auto-extracted fact: {fact}"
            self._send_json({"ok": True, "message": msg, "longterm": memory.load_longterm(personality=p), "shortterm": memory.load(personality=p)})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_memory_update(self) -> None:
        try:
            data = self._read_json() or {}
            old_fact = data.get("old_fact", "").strip()
            new_fact = data.get("new_fact", "").strip()
            longterm = data.get("longterm", True)
            p = data.get("personality")
            if not old_fact or not new_fact:
                self._send_json({"ok": False, "error": "Missing old_fact or new_fact"}, 400)
                return
            from core import db, memory
            db.update_memory_fact(old_fact, new_fact, longterm=bool(longterm), personality=p)
            self._send_json({"ok": True, "longterm": memory.load_longterm(personality=p), "shortterm": memory.load(personality=p)})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_memory_delete(self) -> None:
        try:
            data = self._read_json() or {}
            fact = data.get("fact", "").strip()
            longterm = data.get("longterm", True)
            p = data.get("personality")
            if not fact:
                self._send_json({"ok": False, "error": "Missing fact"}, 400)
                return
            from core import db, memory
            db.remove_memory_fact(fact, longterm=bool(longterm), personality=p)
            self._send_json({"ok": True, "longterm": memory.load_longterm(personality=p), "shortterm": memory.load(personality=p)})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_GET(self) -> None:
        global _web_client_connected
        if self._guard("GET"):
            return
        _web_client_connected = True

        path_clean = self.path.split("?")[0].rstrip("/")
        if not path_clean:
            path_clean = "/"

        if web_campaign.dispatch_request(self, self.path, "GET"):
            return

        if path_clean.startswith("/static/"):
            self._handle_static()
            return

        if path_clean.startswith("/module/"):
            self._handle_module_viewer()
            return

        if path_clean.startswith("/images/modules/") or path_clean.startswith("/asset/"):
            self._handle_module_image()
            return

        if path_clean.startswith("/rules_images/"):
            self._handle_rules_image()
            return

        get_routes = {
            "/": self._handle_root,
            "/campaign": self._handle_campaign_page,
            "/memory": self._handle_root,
            "/api/campaign": self._handle_campaign_get,
            "/api/memory": self._handle_memory_get,
            "/api/app.js": self._handle_app_js,
            "/manifest.webmanifest": self._handle_manifest,
            "/favicon.svg": self._handle_favicon,
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
                from core import camera
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
                    # Stored per personality; a plain ELEVENLABS_VOICE_ID was never read.
                    voice_owner = data.get("skull_name") or config.SKULL_NAME
                    settings_data[config.voice_id_setting_name(voice_owner)] = keys["elevenlabs_voice_id"]
                if "openai" in keys and keys["openai"]:
                    settings_data["OPENAI_API_KEY"] = keys["openai"]

            config.save_settings(settings_data)

            if "core.main" in sys.modules and hasattr(sys.modules["core.main"], "stop_setup_repeater"):
                try:
                    sys.modules["core.main"].stop_setup_repeater()
                except Exception:
                    pass

            if "owner" in data:
                config.save_owner_profile(data["owner"])

            if "wifi" in data and data["wifi"].get("ssid"):
                from core import wifi_provisioner
                wifi_provisioner.connect_network(data["wifi"]["ssid"], data["wifi"].get("password"))
                wifi_provisioner.stop_hotspot()

            self._send_json({"status": "ok", "message": "Appliance initialized successfully!"})

            # The name, keys and persona are read at import time across the app, so
            # the process restarts to load them; systemd brings it straight back
            # (Restart=on-failure counts exit code 3 as a failure) and the boot
            # phrase announces the newly configured unit. A manual run just logs it.
            if os.environ.get("INVOCATION_ID"):
                print("[web] Setup saved — restarting the service to load the new configuration.")
                threading.Timer(2.0, lambda: os._exit(3)).start()
            else:
                print("[web] Setup saved — restart the skull to load the new configuration.")
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_wifi_connect(self) -> None:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            ssid = data.get("ssid", "")
            password = data.get("password", "")
            from core import wifi_provisioner
            success, msg = wifi_provisioner.connect_network(ssid, password)
            self._send_json({"status": "ok" if success else "error", "message": msg})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_wifi_hotspot(self) -> None:
        try:
            from core import wifi_provisioner
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
                from core import display
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
                    from core import speaker_id, transcribe
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
        if self._guard("POST"):
            return
        path_clean = self.path.split("?")[0].rstrip("/")

        if web_campaign.dispatch_request(self, self.path, "POST"):
            return

        post_routes = {
            "/api/setup/test_key": self._handle_setup_test_key,
            "/api/setup/save": self._handle_setup_save,
            "/api/wifi/connect": self._handle_wifi_connect,
            "/api/wifi/hotspot": self._handle_wifi_hotspot,
            "/api/wake": self._handle_wake,
            "/api/screensaver": self._handle_screensaver,
            "/api/camera/capture": self._handle_camera_capture,
            "/api/command": self._handle_command,
            "/api/upload_audio": self._handle_upload_audio,
            "/api/game/start": self._handle_game_start,
            "/api/game/stop": self._handle_game_stop,
            "/api/campaign/load": self._handle_campaign_load,
            "/api/campaign/new": self._handle_campaign_new,
            "/api/campaign/update": self._handle_campaign_update,
            "/api/campaign/character/upsert": self._handle_campaign_character_upsert,
            "/api/campaign/character/delete": self._handle_campaign_character_delete,
            "/api/campaign/roll_char": self._handle_campaign_roll_char,
            "/api/campaign/npc/add": self._handle_campaign_npc_add,
            "/api/campaign/timeline/add": self._handle_campaign_timeline_add,
            "/api/memory/add": self._handle_memory_add,
            "/api/memory/update": self._handle_memory_update,
            "/api/memory/delete": self._handle_memory_delete,
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
        # The certificate and private key live with the other per-unit data, never
        # in the code directory: a key next to the source ended up committed to the
        # public repo, so every unit was serving the same (published) private key.
        config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        cert_file = str(config.data_path("cert.pem"))
        key_file = str(config.data_path("key.pem"))

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
            server.ssl_context = context  # handshakes happen per connection, off the accept loop
            global _https_enabled
            _https_enabled = True
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
    import socket
    port = getattr(config, "WEB_SERVER_PORT", 8080)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"[web] Web server port {port} already active (omega7-web standalone service).")
                return
    except Exception:
        pass
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

# Embedded Single-File HTML / CSS / JS Client
HTML_CLIENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="color-scheme" content="dark">
    <meta name="theme-color" content="#04120a">
    <meta name="description" content="Remote cogitator terminal for the Omega-7 servo-skull.">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Omega-7">
    <title>Omega-7 Cogitator Terminal</title>
    <link rel="manifest" href="/manifest.webmanifest">
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <link rel="apple-touch-icon" href="/static/icon-180.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700;900&family=IM+Fell+English:ital@0;1&family=MedievalSharp&family=Share+Tech+Mono&display=swap">
    <style>
        /* ══════════════════════════════════════════════════════════════════
           Legacy tokens. The WFRP campaign view and the global button rule
           below inherit these, so the values stay exactly as they were.
           ══════════════════════════════════════════════════════════════════ */
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

        /* High-tech chamfered button style (campaign buttons inherit this) */
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

        /* ══════════════════════════════════════════════════════════════════
           OMEGA-7 COGITATOR TERMINAL — design system
           Everything below is scoped to .o7 (the terminal and memory views)
           so none of it can reach the WFRP campaign pages.
           ══════════════════════════════════════════════════════════════════ */
        .o7,
        .o7-modal,
        .o7-toast,
        .o7-lightbox {
            /* spacing + radii */
            --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px;
            --sp-4: 16px; --sp-5: 24px; --sp-6: 36px;
            --r-1: 3px;   --r-2: 6px;   --r-3: 12px;

            /* surfaces */
            --surface-0: #020a05;
            --surface-1: #061308;
            --surface-2: #0a1d10;
            --surface-3: #0f2a17;
            --hairline: rgba(70, 255, 120, 0.15);
            --hairline-2: rgba(70, 255, 120, 0.32);

            /* ink — raised contrast over the old #117823 on near-black */
            --ink: #dcffe6;
            --ink-2: #93dfa8;
            --ink-3: #65b47e;

            /* signal colours */
            --acc: #46ff78;
            --acc-soft: rgba(70, 255, 120, 0.12);
            --acc-glow: rgba(70, 255, 120, 0.40);
            --ok: #46ff78;
            --warn: #ffc152;
            --crit: #ff5f4a;
            --info: #5cd8ff;

            --font-ui: 'Share Tech Mono', ui-monospace, 'SF Mono', 'Courier New', monospace;
            --shadow-1: 0 1px 0 rgba(70, 255, 120, 0.05) inset, 0 16px 36px -26px #000;
            --shadow-2: 0 0 0 1px var(--hairline), 0 24px 50px -30px #000;

            /* iOS home-screen / notch padding */
            --gutter: clamp(10px, 2.2vw, 28px);
        }

        .o7 {
            position: relative;
            min-height: 100vh;
            color: var(--ink);
            font-family: var(--font-ui);
            font-size: 15px;
            line-height: 1.5;
            background:
                radial-gradient(1200px 700px at 50% -8%, rgba(70, 255, 120, 0.055), transparent 70%),
                var(--surface-0);
            padding:
                calc(env(safe-area-inset-top, 0px) + var(--sp-3))
                calc(env(safe-area-inset-right, 0px) + var(--gutter))
                calc(env(safe-area-inset-bottom, 0px) + var(--sp-6))
                calc(env(safe-area-inset-left, 0px) + var(--gutter));
        }

        /* ── CRT atmosphere ───────────────────────────────────────────────
           One fixed, non-interactive layer instead of two stacked
           pseudo-elements. Switched off by the DISPLAY toggle and whenever
           the reader asks for reduced motion. */
        .o7-crt {
            position: fixed;
            inset: 0;
            z-index: 900;
            pointer-events: none;
            background:
                repeating-linear-gradient(180deg, rgba(0,0,0,0) 0 2px, rgba(0,0,0,0.20) 2px 4px),
                radial-gradient(130% 110% at 50% 45%, rgba(70,255,120,0.028) 0%, rgba(0,0,0,0.55) 100%);
            mix-blend-mode: normal;
            animation: o7-flicker 4s steps(2, end) infinite;
        }

        @keyframes o7-flicker {
            0%, 97% { opacity: 1; }
            98%     { opacity: 0.94; }
            100%    { opacity: 1; }
        }

        .o7[data-skin="clean"] .o7-crt { display: none; }

        @media (prefers-reduced-motion: reduce) {
            .o7-crt { animation: none; }
            .o7 *, .o7 *::before, .o7 *::after {
                animation-duration: 0.001s !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.001s !important;
            }
        }

        /* ── typography ───────────────────────────────────────────────── */
        .o7 h1, .o7 h2, .o7 h3,
        .o7-modal h1, .o7-modal h2, .o7-modal h3 {
            font-weight: 700;
            letter-spacing: 0.08em;
            line-height: 1.2;
            text-transform: uppercase;
        }
        .o7-label {
            font-size: 10.5px;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--ink-3);
            font-weight: 700;
        }
        .o7-num {
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum" 1;
        }
        .o7-sr {
            position: absolute;
            width: 1px; height: 1px;
            overflow: hidden;
            clip-path: inset(50%);
            white-space: nowrap;
        }

        /* ── focus ring: visible for keyboards, quiet for mice ─────────── */
        :is(.o7, .o7-modal, .o7-lightbox) :focus-visible {
            outline: 2px solid var(--acc);
            outline-offset: 2px;
            border-radius: var(--r-1);
        }
        :is(.o7, .o7-modal, .o7-lightbox) :focus:not(:focus-visible) { outline: none; }

        /* ── shell ────────────────────────────────────────────────────── */
        .o7-shell {
            width: 100%;
            max-width: 1480px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: var(--sp-4);
        }

        /* ── top bar ──────────────────────────────────────────────────── */
        .o7-topbar {
            position: sticky;
            top: calc(env(safe-area-inset-top, 0px) - var(--sp-3));
            z-index: 800;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--sp-3) var(--sp-4);
            padding: var(--sp-3) var(--sp-4);
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-2);
            background: linear-gradient(180deg, rgba(10, 32, 18, 0.96), rgba(4, 14, 8, 0.96));
            backdrop-filter: blur(10px) saturate(130%);
            -webkit-backdrop-filter: blur(10px) saturate(130%);
            box-shadow: var(--shadow-2);
        }

        .o7-brand {
            display: flex;
            align-items: center;
            gap: var(--sp-3);
            min-width: 0;
            margin-right: auto;
        }

        .o7-brand h1 {
            font-size: clamp(13px, 1.5vw, 17px);
            color: var(--ink);
            text-shadow: 0 0 14px var(--acc-glow);
            white-space: nowrap;
        }
        .o7-brand .o7-brand-sub {
            display: block;
            font-size: 9.5px;
            letter-spacing: 0.22em;
            color: var(--ink-3);
            text-shadow: none;
            margin-top: 2px;
        }

        .cog-logo {
            width: 30px;
            height: 30px;
            flex-shrink: 0;
            fill: var(--acc);
            filter: drop-shadow(0 0 6px var(--acc-glow));
            animation: slow-spin 24s linear infinite;
        }

        @keyframes slow-spin {
            0%   { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* ── nav rail ─────────────────────────────────────────────────── */
        .o7-nav {
            display: flex;
            align-items: center;
            gap: var(--sp-1);
            padding: 3px;
            border: 1px solid var(--hairline);
            border-radius: var(--r-2);
            background: rgba(0, 0, 0, 0.45);
        }

        .o7-nav-short { display: none; }

        .o7-nav a, .o7-nav button {
            all: unset;
            box-sizing: border-box;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 7px 12px;
            min-height: 36px;
            border-radius: var(--r-1);
            font: 700 11.5px/1 var(--font-ui);
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--ink-2);
            cursor: pointer;
            white-space: nowrap;
            transition: background 0.18s ease, color 0.18s ease;
        }

        .o7-nav a:hover, .o7-nav button:hover {
            background: var(--acc-soft);
            color: var(--ink);
        }

        .o7-nav a[aria-current="page"] {
            background: var(--acc);
            color: #021007;
            text-shadow: none;
        }

        /* ── connection pill ──────────────────────────────────────────── */
        .o7-conn {
            display: inline-flex;
            align-items: center;
            gap: var(--sp-2);
            padding: 7px 12px;
            border: 1px solid var(--hairline-2);
            border-radius: 999px;
            background: rgba(0, 0, 0, 0.45);
            font-size: 10.5px;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--ink-2);
            white-space: nowrap;
        }
        .o7-conn .o7-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
            background: var(--ok);
            box-shadow: 0 0 8px var(--ok);
            animation: o7-pulse-dot 2.4s ease-in-out infinite;
        }
        .o7-conn[data-link="stale"] { color: var(--warn); border-color: rgba(255, 193, 82, 0.5); }
        .o7-conn[data-link="stale"] .o7-dot { background: var(--warn); box-shadow: 0 0 8px var(--warn); }
        .o7-conn[data-link="offline"] { color: var(--crit); border-color: rgba(255, 95, 74, 0.55); }
        .o7-conn[data-link="offline"] .o7-dot { background: var(--crit); box-shadow: 0 0 8px var(--crit); animation: none; }

        @keyframes o7-pulse-dot {
            0%, 100% { opacity: 1; }
            50%      { opacity: 0.35; }
        }

        /* ── cards ────────────────────────────────────────────────────── */
        .o7-card {
            position: relative;
            display: flex;
            flex-direction: column;
            min-width: 0;
            gap: var(--sp-3);
            padding: var(--sp-4);
            border: 1px solid var(--hairline);
            border-radius: var(--r-2);
            background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
            box-shadow: var(--shadow-1);
        }

        /* corner brackets, drawn without extra markup */
        .o7-card::before, .o7-card::after {
            content: "";
            position: absolute;
            width: 12px; height: 12px;
            border: 2px solid var(--hairline-2);
            pointer-events: none;
        }
        .o7-card::before { top: -1px;    left: -1px;  border-width: 2px 0 0 2px; border-radius: var(--r-2) 0 0 0; }
        .o7-card::after  { bottom: -1px; right: -1px; border-width: 0 2px 2px 0; border-radius: 0 0 var(--r-2) 0; }

        .o7-card-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
            flex-wrap: wrap;
            padding-bottom: var(--sp-2);
            border-bottom: 1px solid var(--hairline);
        }

        .o7-card-head h2 {
            display: flex;
            align-items: center;
            gap: var(--sp-2);
            font-size: 11.5px;
            letter-spacing: 0.18em;
            color: var(--ink-2);
        }
        .o7-card-head h2::before {
            content: "";
            width: 3px;
            height: 13px;
            background: var(--acc);
            box-shadow: 0 0 8px var(--acc-glow);
            border-radius: 1px;
        }
        .o7-card-tools {
            display: flex;
            align-items: center;
            gap: var(--sp-2);
            flex-wrap: wrap;
        }

        /* ── layout ───────────────────────────────────────────────────── */
        .o7-main {
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: var(--sp-4);
            align-items: start;
        }
        .o7-col {
            display: grid;
            gap: var(--sp-4);
            min-width: 0;
            align-content: start;
        }
        .o7-feeds {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: var(--sp-4);
        }

        @media (min-width: 1080px) {
            .o7-main { grid-template-columns: minmax(0, 1.08fr) minmax(0, 1fr); }
        }

        /* Below the two-column break the columns dissolve, so the cards can be
           ordered for a phone: talk first, then look, then read. */
        @media (max-width: 1079px) {
            .o7-col { display: contents; }
            .o7-card-vox      { order: 1; }
            .o7-card-feeds    { order: 2; }
            .o7-card-vitals   { order: 3; }
            .o7-card-console  { order: 4; }
            .o7-card-aux      { order: 5; }
        }

        /* ── status strip ─────────────────────────────────────────────── */
        .o7-status {
            display: grid;
            gap: var(--sp-3);
            grid-template-columns: minmax(0, 1fr);
        }
        @media (min-width: 640px) {
            .o7-status { grid-template-columns: minmax(220px, 0.9fr) minmax(0, 1.1fr); align-items: center; }
        }

        .alert-banner {
            position: relative;
            display: flex;
            flex-direction: column;
            gap: 2px;
            padding: var(--sp-3) var(--sp-4);
            border: 1px solid var(--hairline-2);
            border-left: 3px solid var(--acc);
            border-radius: var(--r-2);
            background: var(--acc-soft);
            transition: background 0.3s ease, border-color 0.3s ease;
        }
        .alert-banner[data-state="busy"] {
            background: rgba(70, 255, 120, 0.17);
            border-left-color: var(--acc);
        }
        .alert-banner[data-state="busy"]::after {
            content: "";
            position: absolute;
            left: 0; right: 0; bottom: 0;
            height: 2px;
            border-radius: 0 0 var(--r-2) var(--r-2);
            background: linear-gradient(90deg, transparent, var(--acc), transparent);
            background-size: 220% 100%;
            animation: o7-sweep 1.6s linear infinite;
        }
        @keyframes o7-sweep {
            0%   { background-position: -110% 0; }
            100% { background-position: 110% 0; }
        }

        .alert-title {
            font-size: 10px;
            letter-spacing: 0.2em;
            color: var(--ink-3);
            text-transform: uppercase;
            font-weight: 700;
        }
        .alert-value {
            font-size: clamp(16px, 2.4vw, 23px);
            font-weight: 700;
            letter-spacing: 0.1em;
            color: var(--ink);
            text-shadow: 0 0 14px var(--acc-glow);
            text-transform: uppercase;
            word-break: break-word;
        }

        /* ── chips ────────────────────────────────────────────────────── */
        .o7-chips {
            display: grid;
            /* 165px keeps the four chips to 4-up, 2-up or 1-up — never a ragged 3+1 */
            grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
            gap: var(--sp-2);
            align-content: start;
        }
        .o7-chip {
            display: flex;
            flex-direction: column;
            gap: 3px;
            padding: var(--sp-2) var(--sp-3);
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.35);
            min-width: 0;
        }
        .o7-chip .telemetry-value,
        .o7-chip .o7-chip-val {
            font-size: 13px;
            font-weight: 700;
            color: var(--ink);
            word-break: break-word;
        }
        .o7-chip a { color: var(--acc); }

        /* ── meters ───────────────────────────────────────────────────── */
        .o7-meters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
            gap: var(--sp-2);
        }

        .o7-meter {
            --meter: var(--ok);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: var(--sp-2);
            padding: var(--sp-3) var(--sp-2);
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.35);
            min-width: 0;
        }
        .o7-meter[data-state="warn"] { --meter: var(--warn); border-color: rgba(255, 193, 82, 0.4); }
        .o7-meter[data-state="crit"] { --meter: var(--crit); border-color: rgba(255, 95, 74, 0.5); background: rgba(255, 95, 74, 0.07); }

        .gauge-label {
            font-size: 9.5px;
            letter-spacing: 0.1em;
            font-weight: 700;
            color: var(--ink-3);
            text-align: center;
            line-height: 1.3;
            word-break: break-word;
        }

        .pie-chart-container {
            position: relative;
            width: clamp(52px, 6vw, 66px);
            aspect-ratio: 1;
            display: grid;
            place-items: center;
        }
        .pie-chart {
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }
        .pie-bg {
            fill: none;
            stroke: rgba(70, 255, 120, 0.14);
            stroke-width: 3.2;
        }
        .pie-fill {
            fill: none;
            stroke: var(--meter);
            stroke-width: 3.6;
            stroke-linecap: round;
            filter: drop-shadow(0 0 4px var(--meter));
            transition: stroke-dasharray 0.5s cubic-bezier(0.2, 0.8, 0.25, 1), stroke 0.3s ease;
        }
        .gauge-val {
            position: absolute;
            font-size: 11px;
            font-weight: 700;
            color: var(--ink);
            text-align: center;
            line-height: 1.1;
            max-width: 90%;
            word-break: break-word;
        }
        #power-status {
            font-size: 9px;
            letter-spacing: 0.06em;
            text-align: center;
        }

        /* ── rangefinder ──────────────────────────────────────────────── */
        .o7-range {
            display: flex;
            flex-direction: column;
            gap: var(--sp-2);
            padding: var(--sp-3);
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.35);
        }
        .sensor-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-2);
            flex-wrap: wrap;
        }
        .sensor-header .telemetry-value {
            font-size: 13px;
            font-weight: 700;
            color: var(--ink);
        }
        .sensor-bar-container {
            position: relative;
            height: 10px;
            border-radius: 999px;
            background: rgba(0, 0, 0, 0.6);
            border: 1px solid var(--hairline);
            overflow: hidden;
        }
        .sensor-bar {
            height: 100%;
            width: 0%;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(70, 255, 120, 0.5), var(--acc));
            box-shadow: 0 0 10px var(--acc-glow);
            transition: width 0.45s cubic-bezier(0.1, 0.8, 0.3, 1);
        }
        .o7-ticks {
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            font-weight: 700;
            color: var(--ink-3);
        }

        /* ── feeds ────────────────────────────────────────────────────── */
        .o7-feed-frame {
            position: relative;
            width: 100%;
            aspect-ratio: 1;
            max-width: 340px;
            margin: 0 auto;
            display: grid;
            place-items: center;
            overflow: hidden;
            border-radius: var(--r-2);
            background: #000402;
            box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.95);
        }
        .ocular-ring {
            border: 2px solid var(--hairline-2);
            border-radius: 50%;
            box-shadow: 0 0 24px rgba(70, 255, 120, 0.12), inset 0 0 30px rgba(0, 0, 0, 0.95);
            transition: box-shadow 0.2s ease;
        }
        .camera-screen {
            border: 2px solid var(--hairline);
        }
        .ocular-canvas {
            width: 94%;
            aspect-ratio: 1;
            border-radius: 50%;
            display: block;
        }
        .camera-canvas {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .camera-placeholder-text {
            color: var(--ink-3);
            font-size: 10.5px;
            letter-spacing: 0.14em;
            text-align: center;
            line-height: 1.8;
        }
        .ocular-bezel-text {
            position: absolute;
            font-size: 8.5px;
            letter-spacing: 0.08em;
            color: var(--ink-3);
            z-index: 10;
            pointer-events: none;
        }
        .bezel-tl { top: 8px;    left: 10px; }
        .bezel-tr { top: 8px;    right: 10px; }
        .bezel-bl { bottom: 8px; left: 10px; }
        .bezel-br { bottom: 8px; right: 10px; }

        .custom-image-display {
            position: absolute;
            width: 94%;
            aspect-ratio: 1;
            border-radius: 50%;
            object-fit: cover;
            display: none;
            filter: sepia(1) hue-rotate(85deg) saturate(2.5) contrast(1.2) brightness(0.95);
            opacity: 0.95;
        }

        /* ── vox channel ──────────────────────────────────────────────── */
        .o7-vox { flex: 1; }

        .chat-container {
            display: flex;
            flex-direction: column;
            gap: var(--sp-2);
            height: clamp(260px, 40vh, 460px);
            padding: var(--sp-3);
            overflow-y: auto;
            overscroll-behavior: contain;
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.5);
            font-size: 13.5px;
            scroll-behavior: smooth;
        }

        .chat-bubble {
            max-width: 88%;
            padding: var(--sp-2) var(--sp-3);
            border-radius: var(--r-2);
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            animation: o7-rise 0.22s ease-out;
        }
        @keyframes o7-rise {
            from { opacity: 0; transform: translateY(4px); }
            to   { opacity: 1; transform: none; }
        }
        .chat-user {
            align-self: flex-end;
            background: rgba(70, 255, 120, 0.1);
            border: 1px solid var(--hairline-2);
            border-bottom-right-radius: var(--r-1);
            color: var(--ink);
        }
        .chat-skull {
            align-self: flex-start;
            background: linear-gradient(180deg, rgba(70, 255, 120, 0.16), rgba(70, 255, 120, 0.07));
            border: 1px solid var(--hairline-2);
            border-bottom-left-radius: var(--r-1);
            color: var(--ink);
            text-shadow: 0 0 10px rgba(70, 255, 120, 0.25);
        }

        .o7-quick {
            display: flex;
            gap: var(--sp-2);
            flex-wrap: wrap;
        }

        .input-bar {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto auto;
            gap: var(--sp-2);
        }
        .input-bar input {
            min-width: 0;
            padding: 11px var(--sp-3);
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.6);
            color: var(--ink);
            font-family: inherit;
            font-size: 16px; /* 16px keeps iOS from zooming on focus */
        }
        .input-bar input::placeholder { color: var(--ink-3); }
        .input-bar input:focus {
            outline: none;
            border-color: var(--acc);
            box-shadow: 0 0 0 3px rgba(70, 255, 120, 0.14);
        }

        @media (max-width: 520px) {
            .input-bar { grid-template-columns: minmax(0, 1fr) auto; }
            .input-bar .mic-btn { grid-column: 1 / -1; }
        }

        /* ── buttons (override the global chamfered rule inside .o7) ──── */
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            min-height: 38px;
            padding: 9px 14px;
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-1);
            background: rgba(70, 255, 120, 0.07);
            color: var(--ink);
            font: 700 11.5px/1 var(--font-ui);
            letter-spacing: 0.12em;
            text-transform: uppercase;
            text-shadow: none;
            text-decoration: none;
            cursor: pointer;
            clip-path: none;
            transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.08s ease;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn:hover {
            background: rgba(70, 255, 120, 0.18);
            border-color: var(--acc);
            color: var(--ink);
            box-shadow: none;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn:active { transform: translateY(1px); }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn[disabled] { opacity: 0.45; cursor: not-allowed; }

        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-primary {
            background: var(--acc);
            border-color: var(--acc);
            color: #021007;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-primary:hover {
            background: #6bffa0;
            border-color: #6bffa0;
            color: #021007;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-ghost {
            background: transparent;
            border-color: var(--hairline);
            color: var(--ink-2);
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-ghost:hover { background: var(--acc-soft); color: var(--ink); }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-danger {
            background: rgba(255, 95, 74, 0.12);
            border-color: rgba(255, 95, 74, 0.5);
            color: #ffb8ae;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-danger:hover {
            background: rgba(255, 95, 74, 0.25);
            border-color: var(--crit);
            color: #fff;
        }
        :is(.o7, .o7-modal, .o7-lightbox) .o7-btn-sm {
            min-height: 30px;
            padding: 6px 10px;
            font-size: 10.5px;
        }

        .btn-svg {
            width: 15px;
            height: 15px;
            fill: currentColor;
            flex-shrink: 0;
        }

        .o7 button.mic-btn.recording {
            background: var(--crit);
            border-color: var(--crit);
            color: #fff;
            animation: pulse-red 1.6s infinite;
        }
        @keyframes pulse-red {
            0%   { box-shadow: 0 0 0 0 rgba(255, 95, 74, 0.6); }
            70%  { box-shadow: 0 0 0 10px rgba(255, 95, 74, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 95, 74, 0); }
        }

        /* ── form controls ────────────────────────────────────────────── */
        .o7 select,
        .o7 textarea,
        .o7 input[type="text"],
        .o7 input[type="password"],
        .o7-modal select,
        .o7-modal textarea,
        .o7-modal input[type="text"],
        .o7-modal input[type="password"] {
            min-width: 0;
            padding: 9px var(--sp-3);
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.6);
            color: var(--ink);
            font-family: inherit;
            font-size: 14px;
        }
        .o7 select,
        .o7-modal select { padding-right: var(--sp-5); cursor: pointer; }
        .o7 select:focus,
        .o7 textarea:focus,
        .o7 input[type="text"]:focus,
        .o7 input[type="password"]:focus,
        .o7-modal select:focus,
        .o7-modal textarea:focus,
        .o7-modal input[type="text"]:focus,
        .o7-modal input[type="password"]:focus {
            outline: none;
            border-color: var(--acc);
            box-shadow: 0 0 0 3px rgba(70, 255, 120, 0.14);
        }
        .o7 label,
        .o7-modal label { font-size: 11px; letter-spacing: 0.1em; color: var(--ink-2); font-weight: 700; }

        /* ── auxiliary controls ───────────────────────────────────────── */
        .o7-aux-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: var(--sp-3);
        }
        .o7-aux-item {
            display: flex;
            flex-direction: column;
            gap: var(--sp-2);
            padding: var(--sp-3);
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.3);
            min-width: 0;
        }
        .o7-aux-row {
            display: flex;
            gap: var(--sp-2);
            flex-wrap: wrap;
            align-items: center;
        }
        .o7-aux-row > select { flex: 1 1 130px; }

        /* ── console ──────────────────────────────────────────────────── */
        .console-box {
            height: clamp(140px, 22vh, 260px);
            padding: var(--sp-2) var(--sp-3);
            overflow-y: auto;
            overscroll-behavior: contain;
            border: 1px solid var(--hairline);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.6);
            font-size: 11.5px;
            line-height: 1.6;
            color: var(--ink-2);
        }
        .console-line {
            white-space: pre-wrap;
            word-break: break-word;
            padding: 2px 0;
            border-bottom: 1px solid rgba(70, 255, 120, 0.06);
        }
        .console-line:last-child { border-bottom: 0; }

        /* ── memory bank view ─────────────────────────────────────────── */
        .o7-mem-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: var(--sp-4);
        }
        .o7-mem-list {
            display: flex;
            flex-direction: column;
            gap: var(--sp-2);
            max-height: 52vh;
            overflow-y: auto;
            overscroll-behavior: contain;
        }
        .o7-mem-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
            padding: var(--sp-2) var(--sp-3);
            border: 1px solid var(--hairline);
            border-left: 3px solid var(--acc);
            border-radius: var(--r-1);
            background: rgba(0, 0, 0, 0.35);
        }
        .o7-mem-item.o7-mem-auto { border-left-color: var(--info); }
        .o7-mem-item.o7-mem-auto .o7-mem-text { color: #bfeeff; }
        .o7-mem-text {
            flex: 1;
            min-width: 0;
            font-size: 13px;
            word-break: break-word;
        }
        .o7-mem-actions {
            display: flex;
            gap: var(--sp-1);
            flex-shrink: 0;
        }
        .o7-mem-empty {
            padding: var(--sp-3);
            font-size: 12.5px;
            color: var(--ink-3);
        }
        .o7-count {
            font-size: 11px;
            font-weight: 700;
            color: var(--ink-3);
            font-variant-numeric: tabular-nums;
        }

        /* ── wizard modal ─────────────────────────────────────────────── */
        .o7-modal {
            position: fixed;
            color: var(--ink);
            font-family: var(--font-ui);
            font-size: 15px;
            line-height: 1.5;
            inset: 0;
            z-index: 20000;
            padding: calc(env(safe-area-inset-top, 0px) + var(--sp-4)) 16px
                     calc(env(safe-area-inset-bottom, 0px) + 16px);
            background: rgba(1, 6, 3, 0.9);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            overflow-y: auto;
        }
        .o7-modal-panel {
            max-width: 660px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: var(--sp-4);
            padding: var(--sp-5);
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-3);
            background: linear-gradient(180deg, var(--surface-3), var(--surface-1));
            box-shadow: 0 40px 80px -30px #000, 0 0 0 1px rgba(70, 255, 120, 0.1);
        }
        .o7-modal-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
            flex-wrap: wrap;
            padding-bottom: var(--sp-3);
            border-bottom: 1px solid var(--hairline);
        }
        .o7-steps {
            display: flex;
            gap: var(--sp-1);
        }
        .o7-steps span {
            width: 30px;
            height: 3px;
            border-radius: 999px;
            background: var(--hairline);
        }
        .o7-steps span.active { background: var(--acc); box-shadow: 0 0 8px var(--acc-glow); }
        .o7-field {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .o7-field .o7-aux-row > input { flex: 1 1 160px; }
        .o7-field-note {
            font-size: 11px;
            color: var(--ink-3);
            min-height: 14px;
        }
        .o7-wizard-body {
            display: flex;
            flex-direction: column;
            gap: var(--sp-4);
        }
        .o7-wizard-actions {
            display: flex;
            justify-content: space-between;
            gap: var(--sp-2);
            flex-wrap: wrap;
            padding-top: var(--sp-2);
            border-top: 1px solid var(--hairline);
        }
        .o7-lede {
            font-size: 13px;
            line-height: 1.6;
            color: var(--ink-2);
        }

        /* ── toast ────────────────────────────────────────────────────── */
        .o7-toast {
            position: fixed;
            left: 50%;
            bottom: calc(env(safe-area-inset-bottom, 0px) + 20px);
            transform: translate(-50%, 140%);
            z-index: 21000;
            max-width: min(92vw, 420px);
            padding: 11px 18px;
            border: 1px solid var(--hairline-2);
            border-radius: 999px;
            background: rgba(6, 22, 12, 0.96);
            color: var(--ink);
            font-size: 12px;
            letter-spacing: 0.06em;
            box-shadow: 0 20px 40px -20px #000;
            opacity: 0;
            transition: transform 0.26s cubic-bezier(0.2, 0.9, 0.3, 1), opacity 0.26s ease;
            pointer-events: none;
        }
        .o7-toast.show {
            transform: translate(-50%, 0);
            opacity: 1;
        }

        /* ── snapshot viewer ──────────────────────────────────────────── */
        .o7-lightbox {
            position: fixed;
            inset: 0;
            z-index: 20500;
            display: none;
            place-items: center;
            padding: calc(env(safe-area-inset-top, 0px) + 16px) 16px
                     calc(env(safe-area-inset-bottom, 0px) + 16px);
            background: rgba(1, 6, 3, 0.92);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
        }
        .o7-lightbox[data-open="true"] { display: grid; }

        .o7-lightbox-panel {
            display: flex;
            flex-direction: column;
            gap: var(--sp-3);
            max-width: min(900px, 100%);
            max-height: 100%;
            padding: var(--sp-3);
            border: 1px solid var(--hairline-2);
            border-radius: var(--r-2);
            background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
            box-shadow: 0 40px 80px -30px #000;
        }
        .o7-lightbox-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
        }
        .o7-lightbox img {
            display: block;
            min-height: 0;
            max-width: 100%;
            max-height: 70vh;
            object-fit: contain;
            border-radius: var(--r-1);
            background: #000;
        }

        /* ── narrow screens ───────────────────────────────────────────── */
        @media (max-width: 680px) {
            .o7 { font-size: 14px; }
            .o7-topbar { padding: var(--sp-2) var(--sp-3); gap: var(--sp-2); }
            .o7-brand h1 { font-size: 12.5px; letter-spacing: 0.04em; white-space: normal; }
            .o7-brand .o7-brand-sub { display: none; }
            .cog-logo { width: 22px; height: 22px; }
            .o7-nav { flex: 1 1 100%; justify-content: space-between; }
            .o7-nav a, .o7-nav button { flex: 1; justify-content: center; padding: 8px 6px; letter-spacing: 0.04em; }
            .o7-card { padding: var(--sp-3); }
            .o7-meters { grid-template-columns: repeat(auto-fit, minmax(84px, 1fr)); }
            .o7-modal-panel { padding: var(--sp-4); }
        }

        @media (max-width: 430px) {
            .o7-nav .o7-nav-icon, .o7-nav .o7-nav-text { display: none; }
            .o7-nav .o7-nav-short { display: inline; }
            .o7-nav a, .o7-nav button { padding: 8px 4px; }
        }
    </style>
</head>
<body>
    <div id="view-terminal" class="o7">
        <div class="o7-crt" aria-hidden="true"></div>

        <div class="o7-shell">

            <!-- ── Top bar: identity, navigation, link health ───────────── -->
            <header class="o7-topbar">
                <div class="o7-brand">
                    <svg class="cog-logo" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
                        <path d="M50 20c-16.5 0-30 13.5-30 30s13.5 30 30 30 30-13.5 30-30-13.5-30-30-30zm0 10c11 0 20 9 20 20s-9 20-20 20-20-9-20-20 9-20 20-20z"/>
                        <path d="M50 0l6 14h-12zM50 100l6-14h-12zM0 50l14-6v12zM100 50l-14-6v12zM15 15l10 10-8 8zM85 85l-10-10 8-8zM15 85l10-10-8-8zM85 15l-10 10 8 8z"/>
                    </svg>
                    <h1>
                        Omega-7 Cogitator Terminal
                        <span class="o7-brand-sub">Adeptus Mechanicus remote rite</span>
                    </h1>
                </div>

                <nav class="o7-nav" aria-label="Terminal sections">
                    <a href="/" aria-current="page" onclick="event.preventDefault(); navigateToView('/');" title="Cogitator terminal">
                        <span class="o7-nav-icon" aria-hidden="true">▣</span><span class="o7-nav-text">Terminal</span><span class="o7-nav-short" aria-hidden="true">Term</span>
                    </a>
                    <a href="/memory" onclick="event.preventDefault(); navigateToView('/memory');" title="Long-term memory bank">
                        <span class="o7-nav-icon" aria-hidden="true">🧠</span><span class="o7-nav-text">Memory</span><span class="o7-nav-short" aria-hidden="true">Mem</span>
                    </a>
                    <a href="/campaign" title="Roleplaying campaign">
                        <span class="o7-nav-icon" aria-hidden="true">🎲</span><span class="o7-nav-text">Campaign</span><span class="o7-nav-short" aria-hidden="true">Camp</span>
                    </a>
                    <button type="button" onclick="o7OpenWizard()" title="Appliance initialization wizard">
                        <span class="o7-nav-icon" aria-hidden="true">⚙</span><span class="o7-nav-text">Setup</span><span class="o7-nav-short" aria-hidden="true">Setup</span>
                    </button>
                    <button type="button" id="skin-btn" onclick="o7ToggleSkin()" title="Toggle the CRT scanline overlay">
                        <span class="o7-nav-icon" aria-hidden="true">◐</span><span class="o7-nav-text">CRT</span><span class="o7-nav-short" aria-hidden="true">CRT</span>
                    </button>
                </nav>

                <div class="o7-conn" id="conn-pill" data-link="live" role="status" aria-live="polite">
                    <span class="o7-dot" aria-hidden="true"></span>
                    <span id="conn-label">Linking</span>
                </div>
            </header>

            <!-- ── Machine state + at-a-glance disposition ──────────────── -->
            <section class="o7-card" aria-label="Machine spirit status">
                <div class="o7-status">
                    <div class="alert-banner" id="alert-banner" data-state="idle" role="status" aria-live="polite">
                        <div class="alert-title" id="alert-title">System Status</div>
                        <div class="alert-value" id="alert-value">System Optimal</div>
                    </div>

                    <div class="o7-chips">
                        <div class="o7-chip">
                            <span class="o7-label">Master</span>
                            <span id="master-val" class="o7-chip-val">Unknown</span>
                        </div>
                        <div class="o7-chip">
                            <span class="o7-label">Disposition</span>
                            <span id="mood-val" class="telemetry-value">Dutiful</span>
                        </div>
                        <div class="o7-chip">
                            <span class="o7-label">Silent mode</span>
                            <span id="silent-val" class="telemetry-value">Inactive</span>
                        </div>
                        <div class="o7-chip">
                            <span class="o7-label">Active game</span>
                            <span id="game-val" class="telemetry-value">None</span>
                        </div>
                    </div>
                </div>
            </section>

            <main class="o7-main">

                <!-- ── Left column: senses and vitals ───────────────────── -->
                <div class="o7-col">

                    <section class="o7-card o7-card-feeds" aria-label="Sensor feeds">
                        <div class="o7-card-head">
                            <h2>Sensor Feeds</h2>
                            <div class="o7-card-tools">
                                <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" id="snapshot-btn" onclick="o7Snapshot()" title="Take a fresh frame through the camera optic">Snapshot</button>
                            </div>
                        </div>

                        <div class="o7-feeds">
                            <figure>
                                <div class="o7-feed-frame ocular-ring" id="eye-ring">
                                    <div class="ocular-bezel-text bezel-tl">TGT: LOCK</div>
                                    <div class="ocular-bezel-text bezel-tr">Z: 4.0X</div>
                                    <div class="ocular-bezel-text bezel-bl">SENS: IR/NV</div>
                                    <div class="ocular-bezel-text bezel-br">RA: 18h36m</div>
                                    <img class="ocular-canvas" id="eye-stream" src="/api/ocular_stream.mjpeg" alt="Live view of the servo-skull eye display">
                                </div>
                                <figcaption class="o7-label" style="text-align:center; margin-top:8px;">Ocular display</figcaption>
                            </figure>

                            <figure>
                                <div class="o7-feed-frame camera-screen" id="camera-screen">
                                    <div class="ocular-bezel-text bezel-tl">CAM: 01</div>
                                    <div class="ocular-bezel-text bezel-tr" id="cam-bezel-tr">FPS: --</div>
                                    <div class="ocular-bezel-text bezel-bl" id="cam-bezel-bl">MODE: STANDBY</div>
                                    <div class="ocular-bezel-text bezel-br">RESOL: 640x480</div>
                                    <img class="camera-canvas" id="camera-stream" alt="Live camera feed" style="display: none;">
                                    <div class="camera-placeholder-text" id="camera-standby">[ No camera stream ]<br>Standby</div>
                                </div>
                                <figcaption class="o7-label" style="text-align:center; margin-top:8px;">Pict-capture optic</figcaption>
                            </figure>
                        </div>
                    </section>

                    <section class="o7-card o7-card-vitals" aria-label="Machine vitals">
                        <div class="o7-card-head">
                            <h2>Vitals</h2>
                            <span class="o7-label" id="vitals-stamp">--</span>
                        </div>

                        <div class="o7-meters">
                            <div class="o7-meter" id="meter-cpu">
                                <span class="gauge-label">CPU</span>
                                <div class="pie-chart-container">
                                    <svg class="pie-chart" viewBox="0 0 36 36" aria-hidden="true">
                                        <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path id="cpu-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <span id="cpu-val" class="gauge-val o7-num">0%</span>
                                </div>
                            </div>

                            <div class="o7-meter" id="meter-temp">
                                <span class="gauge-label">Core temp</span>
                                <div class="pie-chart-container">
                                    <svg class="pie-chart" viewBox="0 0 36 36" aria-hidden="true">
                                        <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path id="temp-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <span id="temp-val" class="gauge-val o7-num">0°C</span>
                                </div>
                                <span id="power-status" class="gauge-label" style="display:none"></span>
                            </div>

                            <div class="o7-meter" id="meter-ram">
                                <span class="gauge-label" id="ram-label">RAM</span>
                                <div class="pie-chart-container">
                                    <svg class="pie-chart" viewBox="0 0 36 36" aria-hidden="true">
                                        <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path id="ram-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <span id="ram-val" class="gauge-val o7-num">0%</span>
                                </div>
                            </div>

                            <div class="o7-meter" id="meter-storage">
                                <span class="gauge-label" id="storage-label">Storage</span>
                                <div class="pie-chart-container">
                                    <svg class="pie-chart" viewBox="0 0 36 36" aria-hidden="true">
                                        <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path id="storage-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <span id="storage-val" class="gauge-val o7-num">0%</span>
                                </div>
                            </div>

                            <div class="o7-meter" id="meter-fabricator">
                                <span class="gauge-label">Fabricator</span>
                                <div class="pie-chart-container">
                                    <svg class="pie-chart" viewBox="0 0 36 36" aria-hidden="true">
                                        <path class="pie-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                        <path id="fabricator-pie" class="pie-fill" stroke-dasharray="0, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                                    </svg>
                                    <span id="fabricator-val" class="gauge-val o7-num">0%</span>
                                </div>
                            </div>
                        </div>

                        <div class="o7-range">
                            <div class="sensor-header">
                                <span class="o7-label">Laser rangefinder &mdash; max 8.0 m</span>
                                <span id="range-val" class="telemetry-value o7-num">-- cm (-- m)</span>
                            </div>
                            <div class="sensor-bar-container">
                                <div id="range-bar" class="sensor-bar"></div>
                            </div>
                            <div class="o7-ticks" aria-hidden="true">
                                <span>0m</span><span>2m</span><span>4m</span><span>6m</span><span>8m</span>
                            </div>
                        </div>
                    </section>

                    <section class="o7-card o7-card-aux" aria-label="Auxiliary controls">
                        <div class="o7-card-head">
                            <h2>Auxiliary Controls</h2>
                        </div>

                        <div class="o7-aux-grid">
                            <div class="o7-aux-item">
                                <span class="o7-label">Visual emulation</span>
                                <div class="o7-aux-row">
                                    <label class="o7-sr" for="screensaver-select">Screensaver</label>
                                    <select id="screensaver-select">
                                        <option value="">-- Select screensaver --</option>
                                    </select>
                                    <button type="button" class="o7-btn" onclick="playScreensaver()">Run</button>
                                </div>
                            </div>

                            <div class="o7-aux-item">
                                <span class="o7-label">Vox audio output</span>
                                <div class="o7-aux-row">
                                    <button type="button" class="o7-btn" id="web-audio-btn" onclick="toggleWebAudio()">🔊 Web audio: enabled</button>
                                </div>
                            </div>

                            <div class="o7-aux-item">
                                <span class="o7-label">Wi-Fi provisioning</span>
                                <div class="o7-aux-row">
                                    <span id="wifi-status-text" style="font-size: 11px;">[ Disconnected ]</span>
                                </div>
                                <div class="o7-aux-row">
                                    <button type="button" class="o7-btn o7-btn-sm" onclick="scanWifiNetworks()">📶 Scan</button>
                                    <button type="button" class="o7-btn o7-btn-sm" onclick="toggleHotspot()">📡 AP hotspot</button>
                                </div>
                            </div>

                            <div class="o7-aux-item">
                                <span class="o7-label">Long-term memory</span>
                                <div class="o7-aux-row">
                                    <a class="o7-btn" href="/memory" onclick="event.preventDefault(); navigateToView('/memory');">🧠 Memory bank</a>
                                </div>
                            </div>
                        </div>
                    </section>
                </div>

                <!-- ── Right column: conversation and telemetry log ─────── -->
                <div class="o7-col">

                    <section class="o7-card o7-vox o7-card-vox" aria-label="Vox channel">
                        <div class="o7-card-head">
                            <h2>Vox Channel</h2>
                            <div class="o7-card-tools">
                                <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7CopyTranscript()" title="Copy the transcript to the clipboard">Copy</button>
                                <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="triggerWake()" title="Wake the skull and have it listen">Wake</button>
                            </div>
                        </div>

                        <div class="chat-container" id="chat-container" role="log" aria-live="polite" aria-label="Vox transcript">
                            <div class="chat-bubble chat-skull">System initialized. Awaiting commands, master.</div>
                        </div>

                        <div class="o7-quick" role="group" aria-label="Quick commands">
                            <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7Quick('Give me a status report.')">Status report</button>
                            <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7Quick('What do you see right now?')">What do you see</button>
                            <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7Quick('What is the weather today?')">Weather</button>
                            <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7Quick('Enter silent mode.')">Silence</button>
                        </div>

                        <div class="input-bar">
                            <label class="o7-sr" for="command-input">Command</label>
                            <input type="text" id="command-input" autocomplete="off" placeholder="Enter high-level command..." onkeydown="o7CommandKey(event)">
                            <button type="button" class="o7-btn o7-btn-primary send-btn" onclick="sendCommand()">Send</button>
                            <button type="button" class="o7-btn mic-btn" id="mic-btn" onclick="toggleMicRecording()" title="Click to record web mic audio">
                                <svg class="btn-svg" viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                                </svg>
                                <span id="mic-btn-label">Rec</span>
                            </button>
                        </div>
                        <p class="o7-label" style="color:var(--ink-3)">Press / to focus &middot; up and down arrows recall earlier commands</p>
                    </section>

                    <section class="o7-card o7-card-console" aria-label="Telemetry console">
                        <div class="o7-card-head">
                            <h2>Telemetry Console</h2>
                            <div class="o7-card-tools">
                                <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" id="console-follow-btn" onclick="o7ToggleFollow()" title="Follow or freeze the log tail">Following</button>
                            </div>
                        </div>
                        <div class="console-box" id="console-box" role="log" aria-label="Telemetry log" tabindex="0">
                            <div class="console-line">[SYSTEM] Remote connection established.</div>
                        </div>
                    </section>
                </div>
            </main>
        </div>
    </div>

    <div class="o7-toast" id="o7-toast" role="status" aria-live="polite"></div>

    <div class="o7-lightbox" id="o7-lightbox" data-open="false" role="dialog" aria-modal="true"
         aria-label="Pict-capture snapshot" onclick="if (event.target === this) o7CloseSnapshot()">
        <div class="o7-lightbox-panel">
            <div class="o7-lightbox-head">
                <span class="o7-label" id="o7-lightbox-cap">Pict-capture</span>
                <div class="o7-card-tools">
                    <a class="o7-btn o7-btn-ghost o7-btn-sm" id="o7-lightbox-download" download="omega7-snapshot.jpg" href="#">Save</a>
                    <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7CloseSnapshot()">Close</button>
                </div>
            </div>
            <img id="o7-lightbox-img" alt="The most recent frame from the servo-skull camera">
        </div>
    </div>


    <!-- ROLEPLAYING CAMPAIGN DASHBOARD VIEW -->
    
    <!-- AUTHENTIC WFRP 4E CORE RULEBOOK PAGE SPREAD VIEW -->
    <div id="view-campaign" style="display: none; min-height: 100vh; background: #160e08; color: #1c130b; font-family: var(--font-body); padding: 30px 15px; box-sizing: border-box;">
        
        <!-- Open Rulebook Page Spread Container -->
        <div style="max-width: 1240px; margin: 0 auto; background: #f6eee0; border: 2px solid #3d2f23; border-radius: 4px; padding: 40px 50px; box-shadow: 0 20px 60px rgba(0,0,0,0.9); position: relative; background-image: radial-gradient(circle at 50% 50%, #f9f2e6 0%, #f1e6d4 100%); color: #1c130b;">
            
            <!-- Campaign Name Leather Tab Badge (Top Left Corner) -->
            <div id="c-tab-badge" style="position: absolute; top: -1px; left: 30px; background: #7a1717; color: #f7efe2; font-family: var(--font-title); font-size: 13px; font-weight: bold; padding: 6px 16px; border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; border: 1px solid #4a0e0e; border-top: none; box-shadow: 0 2px 6px rgba(0,0,0,0.35); text-transform: uppercase; letter-spacing: 1.5px;">SHADOWS OVER REIKLAND</div>

            <!-- Running Header Bar (Matching WFRP Rulebook Top Margin) -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #2c1e14; padding-bottom: 8px; margin-bottom: 28px; margin-left: 45px; font-family: var(--font-title); font-size: 11px; font-weight: bold; color: #2c1e14; letter-spacing: 2.5px;">
                <div>WARHAMMER FANTASY ROLEPLAY</div>
                <div style="color: #7a1717; letter-spacing: 1.5px;">OLD WORLD CAMPAIGN MANAGER</div>
                <div style="display: flex; gap: 10px; align-items: center; letter-spacing: normal;">
                    <select id="campaign-select" onchange="switchCampaign(this.value)" style="background: #fffbf4; border: 1.5px solid #6c5d4f; padding: 4px 10px; font-family: var(--font-body); font-size: 13px; font-weight: bold; color: #1c130b; border-radius: 3px;">
                        <option value="">-- Select Campaign --</option>
                    </select>
                    <button onclick="createNewCampaignPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ NEW</button>
                    <button onclick="navigateToView('/')" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 4px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">⬅ TERMINAL</button>
                </div>
            </div>


            <!-- Two-Column Overview Spread (Matching WFRP Rulebook Sidebar Callout Style) -->
            <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px; margin-bottom: 32px;">
                
                <!-- Left Column: Adventure & Location Summary -->
                <div style="background: #e9e0d0; border: 2px solid #6c5d4f; border-radius: 4px; padding: 20px; box-shadow: inset 0 0 10px rgba(0,0,0,0.05);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; border-bottom: 1.5px solid #8b7961; padding-bottom: 10px;">
                        <div>
                            <span style="font-family: var(--font-title); font-size: 11px; font-weight: bold; color: #7a1717; letter-spacing: 1.5px; text-transform: uppercase;">CURRENT ADVENTURE MODULE</span>
                            <div id="c-adventure" style="font-family: var(--font-title); font-size: 20px; font-weight: bold; color: #1c130b; margin-top: 2px;">Shadows Over Reikland</div>
                        </div>
                        <div style="text-align: right;">
                            <span style="font-family: var(--font-title); font-size: 11px; font-weight: bold; color: #5c4732; letter-spacing: 1px;">LOCATION</span>
                            <div id="c-location" style="font-size: 16px; font-weight: bold; color: #7a1717; margin-top: 2px;">The Reikland</div>
                        </div>
                    </div>
                    <!-- Editable Party Ambitions Section -->
                    <div style="margin-top: 14px; border-top: 1.5px dashed #8b7961; padding-top: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-family: var(--font-title); font-size: 12px; font-weight: bold; color: #7a1717; letter-spacing: 1px; text-transform: uppercase;">⚔️ PARTY AMBITIONS</span>
                            <button id="save-party-ambitions-btn" type="button" onclick="savePartyAmbitions()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px; box-shadow: 0 2px 4px rgba(0,0,0,0.15);">💾 SAVE PARTY AMBITIONS</button>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 13px;">
                            <div>
                                <label style="font-family: var(--font-title); font-weight: bold; color: #7a1717; font-size: 12px; display: block; margin-bottom: 4px;">Short-Term Ambition:</label>
                                <input type="text" id="c-amb-short-inp" onchange="savePartyAmbitions()" placeholder="e.g. Uncover who poisoned the well in Ubersreik" style="width: 100%; border: 1.5px solid #8b7961; background: #fffbf4; padding: 6px 10px; font-size: 13px; font-weight: bold; color: #1c130b; border-radius: 3px; box-sizing: border-box;">
                            </div>
                            <div>
                                <label style="font-family: var(--font-title); font-weight: bold; color: #7a1717; font-size: 12px; display: block; margin-bottom: 4px;">Long-Term Ambition:</label>
                                <input type="text" id="c-amb-long-inp" onchange="savePartyAmbitions()" placeholder="e.g. Expose and purge the Purple Hand cultists in Altdorf" style="width: 100%; border: 1.5px solid #8b7961; background: #fffbf4; padding: 6px 10px; font-size: 13px; font-weight: bold; color: #1c130b; border-radius: 3px; box-sizing: border-box;">
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Quick Campaign Actions (Styled like XP Costs Box) -->
                <div style="background: #e3d8c6; border: 2px solid #4a3c30; border-radius: 4px; overflow: hidden;">
                    <div style="background: #3d2f23; color: #f7efe2; font-family: var(--font-title); font-size: 13px; font-weight: bold; letter-spacing: 1px; padding: 10px 14px; text-align: center; border-bottom: 2px solid #231911;">
                        CAMPAIGN ACTIONS
                    </div>
                    <div style="padding: 16px; display: flex; flex-direction: column; gap: 10px;">
                        <button onclick="rollNewPartyCharacterPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 10px 14px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px; text-align: left; transition: background 0.2s;">🎲 ROLL NEW CHARACTER (2d10 Stats)</button>
                        <button onclick="openCharSheetModalForNew()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 10px 14px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px; text-align: left; transition: background 0.2s;">➕ ADD BLANK CHARACTER SHEET</button>
                    </div>
                </div>
            </div>

            <!-- Compendium Sub-Navigation Bar -->
            <div style="display: flex; gap: 12px; margin-bottom: 24px; border-bottom: 2px solid #7a1717; padding-bottom: 12px; flex-wrap: wrap;">
                <button id="comp-tab-roster" onclick="switchCompendiumTab('roster')" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">🛡️ PARTY ROSTER</button>
                <button id="comp-btn-module-viewer" onclick="window.open('/module/rough-nights-and-hard-days', '_blank')" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">📚 ADVENTURE MODULE VIEWER</button>
                <button id="comp-tab-npcs" onclick="switchCompendiumTab('npcs')" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">👥 DRAMATIS PERSONAE</button>
                <button id="comp-tab-locations" onclick="switchCompendiumTab('locations')" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">🗺️ GEOGRAPHY & SITES</button>
                <button id="comp-tab-quests" onclick="switchCompendiumTab('quests')" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">📜 QUEST LOG</button>
                <button id="comp-tab-timeline" onclick="switchCompendiumTab('timeline')" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">⏳ SESSION TIMELINE</button>
            </div>

            <!-- TAB 1: ROSTER GRID CONTAINER -->
            <div id="comp-pane-roster">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">PARTY HEROES & AGENTS</h2>
                    <span id="roster-count-badge" style="font-family: var(--font-title); font-size: 13px; font-weight: bold; color: #5c4732;">1 CHARACTER</span>
                </div>
                <!-- Character Cards Grid (WFRP Rulebook Table Style) -->
                <div id="character-roster-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; margin-bottom: 36px;">
                    <div style="grid-column: 1/-1; text-align: center; padding: 40px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732; font-size: 15px;">
                        Loading party roster...
                    </div>
                </div>
            </div>

            <!-- TAB 2: NPCS CONTAINER -->
            <div id="comp-pane-npcs" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">DRAMATIS PERSONAE (NPCS)</h2>
                    <button onclick="addNpcPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 14px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD NEW NPC</button>
                </div>
                <div id="comp-npc-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; margin-bottom: 30px;">
                    <div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No NPCs recorded yet. Click "Add New NPC" to begin tracking.</div>
                </div>
            </div>

            <!-- TAB 3: LOCATIONS CONTAINER -->
            <div id="comp-pane-locations" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">OLD WORLD GEOGRAPHY & SITES</h2>
                    <button onclick="addLocationPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 14px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD NEW LOCATION</button>
                </div>
                <div id="comp-location-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; margin-bottom: 30px;">
                    <div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No locations recorded yet.</div>
                </div>
            </div>

            <!-- TAB 4: QUESTS CONTAINER -->
            <div id="comp-pane-quests" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">QUEST LOG & ENCOUNTERS</h2>
                    <button onclick="addQuestPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 14px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD QUEST</button>
                </div>
                <div id="comp-quest-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; margin-bottom: 30px;">
                    <div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No active quests logged.</div>
                </div>
            </div>

            <!-- TAB 5: TIMELINE CONTAINER -->
            <div id="comp-pane-timeline" style="display: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">SESSION TIMELINE LOGS</h2>
                    <button onclick="addTimelineEventPrompt()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 14px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ LOG TIMELINE EVENT</button>
                </div>
                <div id="comp-timeline-list" style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px;">
                    <div style="text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No timeline entries recorded.</div>
                </div>
            </div>

            <!-- Gamemaster Session Journal (WFRP Parchment Style) -->
            <div style="background: #e9e0d0; border: 2px solid #6c5d4f; border-radius: 4px; padding: 20px; margin-bottom: 10px;">
                <div style="font-family: var(--font-title); font-size: 16px; font-weight: bold; color: #7a1717; margin-bottom: 10px;">📜 GAMEMASTER SESSION NOTES & JOURNAL</div>
                <textarea id="c-notes-input" rows="5" placeholder="Record session recap, key NPCs encountered, clues discovered, and pending threats..." style="width: 100%; border: 1.5px solid #6c5d4f; background: #fffbf4; font-family: var(--font-body); font-size: 15px; color: #1c130b; padding: 12px; box-sizing: border-box; border-radius: 3px; line-height: 1.5;"></textarea>
                <div style="display: flex; justify-content: flex-end; margin-top: 12px;">
                    <button id="save-session-notes-btn" onclick="saveCampaignNotes()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 20px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 3px; box-shadow: 0 2px 6px rgba(0,0,0,0.2);">💾 SAVE NOTES</button>
                </div>
            </div>

        </div>
    </div>

    <!-- WFRP 4E Core Rulebook Character Sheet Overlay Modal (Pages 344 & 345) -->
    
    
    
    <!-- COMPENDIUM ENTITY DETAIL & GM SECRETS READOUT MODAL -->
    <div id="compendium-detail-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(10,8,6,0.92); z-index: 28000; padding: 20px; box-sizing: border-box; display: none; justify-content: center; align-items: center; overflow-y: auto;">
        <div style="max-width: 680px; width: 100%; background: #f6eee0; border: 3px double #7a1717; border-radius: 6px; padding: 28px; box-shadow: 0 15px 50px rgba(0,0,0,0.9); color: #1c130b; position: relative;">
            
            <!-- Modal Header -->
            <div style="border-bottom: 2px solid #7a1717; padding-bottom: 12px; margin-bottom: 18px; display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <span id="comp-detail-type-badge" style="font-family: var(--font-title); font-size: 11px; font-weight: bold; background: #7a1717; color: #f7efe2; padding: 3px 8px; border-radius: 3px; letter-spacing: 1px;">NPC</span>
                    <h2 id="comp-detail-title" style="font-family: var(--font-title); font-size: 24px; font-weight: bold; color: #1c130b; margin: 6px 0 0 0;">Entity Title</h2>
                </div>
                <button onclick="closeCompendiumModal()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 6px 14px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">✖ CLOSE</button>
            </div>

            <!-- Meta Attributes Strip -->
            <div id="comp-detail-meta" style="display: flex; gap: 14px; font-size: 13px; color: #4a3c30; font-weight: bold; margin-bottom: 18px; background: #e9e0d0; padding: 10px 14px; border-radius: 4px; border: 1px solid #6c5d4f;">
                <div>Role: <span id="comp-detail-role">--</span></div>
            </div>

            <!-- Section 1: Public Player Knowledge -->
            <div style="margin-bottom: 20px;">
                <div style="font-family: var(--font-title); font-size: 14px; font-weight: bold; color: #7a1717; margin-bottom: 6px; letter-spacing: 0.5px;">📖 PUBLIC PLAYER KNOWLEDGE</div>
                <div id="comp-detail-public-body" style="background: #fffbf4; border: 1.5px solid #6c5d4f; border-radius: 4px; padding: 14px; font-size: 15px; line-height: 1.5; color: #1c130b; min-height: 80px; white-space: pre-wrap;">
                    No public notes recorded.
                </div>
            </div>

            <!-- Section 2: Expandable GM Secrets & Lore -->
            <div style="margin-bottom: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="font-family: var(--font-title); font-size: 14px; font-weight: bold; color: #7a1717; letter-spacing: 0.5px;">🕵️ GAMEMASTER SECRETS & UNREVEALED LORE</div>
                    <button id="toggle-gm-secret-btn" onclick="toggleGmSecrets()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">🔒 SHOW GM SECRETS</button>
                </div>
                
                <div id="comp-detail-secret-container" style="display: none; background: #fdf2f2; border: 1.5px solid #7a1717; border-radius: 4px; padding: 14px; font-size: 15px; line-height: 1.5; color: #4a0e0e; white-space: pre-wrap;">
                    <div style="font-style: italic; color: #7a1717; font-size: 13px; margin-bottom: 6px;">[ CONFIDENTIAL GM INFORMATION — NOT KNOWN TO PLAYERS ]</div>
                    <span id="comp-detail-secret-body">No GM secrets recorded for this entry.</span>
                </div>
            </div>

            <!-- Footer Actions -->
            <div style="border-top: 2px solid #8b7961; padding-top: 14px; display: flex; justify-content: space-between; align-items: center;">
                <button onclick="deleteCurrentCompendiumEntity()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 16px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">🗑️ DELETE</button>
                <div style="display: flex; gap: 10px;">
                    <button onclick="editCurrentCompendiumEntity()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 16px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">✏️ EDIT ENTRY</button>
                    <button onclick="closeCompendiumModal()" style="background: #5c4732; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 16px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">✖ CLOSE</button>
                </div>
            </div>

        </div>
    </div>

    <!-- DELETE CHARACTER CONFIRMATION MODAL -->
    <div id="delete-confirm-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(10,8,6,0.92); z-index: 30000; padding: 20px; box-sizing: border-box; display: none; justify-content: center; align-items: center;">
        <div style="max-width: 480px; width: 100%; background: #f6eee0; border: 3px double #7a1717; border-radius: 6px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.9); color: #1c130b; text-align: center; position: relative;">
            <div style="font-family: var(--font-title); font-size: 20px; font-weight: bold; color: #7a1717; margin-bottom: 12px;">⚠️ CONFIRM CHARACTER DELETION</div>
            <p style="font-size: 14px; margin-bottom: 16px; color: #2c1e14; line-height: 1.4;">Are you sure you want to permanently delete <strong id="delete-target-char-name" style="color: #7a1717;">Character</strong> from this campaign?</p>
            <p style="font-size: 13px; font-weight: bold; color: #5c4732; margin-bottom: 12px;">Type <code style="background: #e9e0d0; padding: 2px 6px; border: 1px solid #7a1717; color: #7a1717; font-weight: bold;">DELETE</code> below to confirm:</p>
            
            <input type="text" id="delete-confirm-input" placeholder="Type DELETE to confirm" style="width: 100%; padding: 10px; border: 1.5px solid #7a1717; background: #fffbf4; font-family: var(--font-body); font-size: 15px; font-weight: bold; text-align: center; color: #1c130b; border-radius: 4px; box-sizing: border-box; margin-bottom: 20px;" onkeyup="checkDeleteConfirmInput(this.value)">
            
            <div style="display: flex; gap: 12px; justify-content: center;">
                <button id="delete-confirm-submit-btn" disabled onclick="executeDeleteCharacter()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 20px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 4px; opacity: 0.5;">PERMANENTLY DELETE</button>
                <button onclick="closeDeleteConfirmModal()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 20px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 4px;">CANCEL</button>
            </div>
        </div>
    </div>

    <!-- WFRP 4E Web Character Creation Wizard Modal -->
    <div id="char-creation-wizard-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(10,8,6,0.95); z-index: 26000; padding: 20px; box-sizing: border-box; overflow-y: auto;">
        <div style="max-width: 860px; margin: 20px auto; background: #f4e7d0; border: 4px double #5c4732; border-radius: 4px; color: #1c130b; font-family: var(--font-body); font-size: 14px; padding: 28px; box-shadow: 0 0 45px rgba(0,0,0,0.9); position: relative;">
            
            <!-- Modal Header -->
            <div style="border-bottom: 3px double #7a1717; padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
                <div style="font-family: var(--font-title); font-size: 20px; font-weight: bold; color: #7a1717; letter-spacing: 1.5px;">⚜ WARHAMMER FANTASY CHARACTER CREATION WIZARD ⚜</div>
                <button onclick="closeCharCreationWizard()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 6px 14px; font-family: var(--font-title); font-weight: bold; font-size: 12px; cursor: pointer; border-radius: 3px;">✖ CANCEL</button>
            </div>

            <!-- Wizard Navigation Steps Bar -->
            <div style="display: flex; gap: 8px; margin-bottom: 22px; border-bottom: 2px solid #8b7961; padding-bottom: 10px; font-family: var(--font-title); font-size: 12px; font-weight: bold;">
                <div id="cc-step-badge-1" style="flex: 1; text-align: center; padding: 8px; background: #7a1717; color: #f5ebd9; border: 1.5px solid #d4af37; border-radius: 4px;">1. SPECIES & STATS</div>
                <div id="cc-step-badge-2" style="flex: 1; text-align: center; padding: 8px; background: #3a2a1a; color: #c9b897; border: 1.5px solid #5c4732; border-radius: 4px;">2. CLASS & CAREER</div>
                <div id="cc-step-badge-3" style="flex: 1; text-align: center; padding: 8px; background: #3a2a1a; color: #c9b897; border: 1.5px solid #5c4732; border-radius: 4px;">3. DETAILS & AMBITIONS</div>
                <div id="cc-step-badge-4" style="flex: 1; text-align: center; padding: 8px; background: #3a2a1a; color: #c9b897; border: 1.5px solid #5c4732; border-radius: 4px;">4. REVIEW & FINISH</div>
            </div>

            <!-- STEP 1: SPECIES & CHARACTERISTICS ALLOCATION -->
            <div id="cc-step-1">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">STEP 1: SPECIES & CHARACTERISTIC DETERMINATION</legend>
                    
                    <!-- Species Selection Grid -->
                    <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px;">
                        <label style="display: flex; flex-direction: column; align-items: center; padding: 10px; background: #fff8ee; border: 2px solid #8b7961; border-radius: 4px; cursor: pointer; text-align: center;">
                            <input type="radio" name="cc-species" value="human" checked onchange="onWizardSpeciesOrGenModeChange()" style="accent-color: #7a1717;">
                            <strong style="margin-top: 4px; color: #7a1717;">👱 Human</strong>
                            <span style="font-size: 11px; color: #666;">Reiklander (+20 XP)</span>
                        </label>
                        <label style="display: flex; flex-direction: column; align-items: center; padding: 10px; background: #fff8ee; border: 2px solid #8b7961; border-radius: 4px; cursor: pointer; text-align: center;">
                            <input type="radio" name="cc-species" value="dwarf" onchange="onWizardSpeciesOrGenModeChange()" style="accent-color: #7a1717;">
                            <strong style="margin-top: 4px; color: #7a1717;">🧔 Dwarf</strong>
                            <span style="font-size: 11px; color: #666;">High T, WP & Dex</span>
                        </label>
                        <label style="display: flex; flex-direction: column; align-items: center; padding: 10px; background: #fff8ee; border: 2px solid #8b7961; border-radius: 4px; cursor: pointer; text-align: center;">
                            <input type="radio" name="cc-species" value="halfling" onchange="onWizardSpeciesOrGenModeChange()" style="accent-color: #7a1717;">
                            <strong style="margin-top: 4px; color: #7a1717;">🦶 Halfling</strong>
                            <span style="font-size: 11px; color: #666;">High BS, Dex & Fel</span>
                        </label>
                        <label style="display: flex; flex-direction: column; align-items: center; padding: 10px; background: #fff8ee; border: 2px solid #8b7961; border-radius: 4px; cursor: pointer; text-align: center;">
                            <input type="radio" name="cc-species" value="high_elf" onchange="onWizardSpeciesOrGenModeChange()" style="accent-color: #7a1717;">
                            <strong style="margin-top: 4px; color: #7a1717;">🧝 High Elf</strong>
                            <span style="font-size: 11px; color: #666;">High I, Ag & Int</span>
                        </label>
                        <label style="display: flex; flex-direction: column; align-items: center; padding: 10px; background: #fff8ee; border: 2px solid #8b7961; border-radius: 4px; cursor: pointer; text-align: center;">
                            <input type="radio" name="cc-species" value="wood_elf" onchange="onWizardSpeciesOrGenModeChange()" style="accent-color: #7a1717;">
                            <strong style="margin-top: 4px; color: #7a1717;">🍃 Wood Elf</strong>
                            <span style="font-size: 11px; color: #666;">High Ag, BS & I</span>
                        </label>
                    </div>

                    <!-- Generation Mode Selector Bar -->
                    <div style="display: flex; justify-content: space-between; align-items: center; background: #fff8ee; border: 1.5px solid #8b7961; padding: 10px 14px; border-radius: 4px; margin-bottom: 16px;">
                        <div style="display: flex; gap: 16px; align-items: center; font-size: 13px;">
                            <strong style="color: #7a1717;">Generation Method:</strong>
                            <label style="cursor: pointer; font-weight: bold; color: #1c130b;">
                                <input type="radio" name="cc-gen-mode" value="random" checked onchange="toggleWizardGenMode()" style="accent-color: #7a1717;"> 🎲 Random Roll (2d10)
                            </label>
                            <label style="cursor: pointer; font-weight: bold; color: #1c130b;">
                                <input type="radio" name="cc-gen-mode" value="assign" onchange="toggleWizardGenMode()" style="accent-color: #7a1717;"> ⚖ Point Allocation (100 Points Pool)
                            </label>
                        </div>
                        <div id="cc-pool-tracker" style="display: none; font-size: 13px; font-weight: bold; color: #2e7d32; background: #fff; padding: 4px 12px; border: 1.5px solid #8b7961; border-radius: 4px;">
                            Points Pool Remaining: <span id="cc-pool-remaining" style="font-size: 15px; color: #7a1717;">0</span> / 100
                        </div>
                    </div>

                    <!-- Random Roll Control Bar -->
                    <div id="cc-random-controls" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
                        <button type="button" onclick="rollWizardCharacteristics()" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 18px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">🎲 ROLL CHARACTERISTICS (2d10 + Base)</button>
                        <div id="cc-roll-status" style="font-size: 12px; font-weight: bold; color: #2e7d32;"></div>
                    </div>

                    <!-- Characteristics Output Grid (10 Stats) -->
                    <div style="display: grid; grid-template-columns: repeat(10, 1fr); gap: 6px; text-align: center; margin-bottom: 16px;">
                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">WS</div>
                            <div id="cc-assign-ctrl-WS" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('WS', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-WS" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('WS', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-WS" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">BS</div>
                            <div id="cc-assign-ctrl-BS" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('BS', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-BS" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('BS', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-BS" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">S</div>
                            <div id="cc-assign-ctrl-S" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('S', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-S" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('S', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-S" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">T</div>
                            <div id="cc-assign-ctrl-T" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('T', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-T" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('T', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-T" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">I</div>
                            <div id="cc-assign-ctrl-I" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('I', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-I" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('I', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-I" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">Ag</div>
                            <div id="cc-assign-ctrl-Ag" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('Ag', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-Ag" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('Ag', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-Ag" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">Dex</div>
                            <div id="cc-assign-ctrl-Dex" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('Dex', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-Dex" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('Dex', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-Dex" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">Int</div>
                            <div id="cc-assign-ctrl-Int" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('Int', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-Int" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('Int', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-Int" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">WP</div>
                            <div id="cc-assign-ctrl-WP" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('WP', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-WP" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('WP', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-WP" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>

                        <div style="background: #fff; border: 1.5px solid #8b7961; border-radius: 4px; padding: 6px;">
                            <div style="font-weight:bold; color:#7a1717; font-size:12px;">Fel</div>
                            <div id="cc-assign-ctrl-Fel" style="display: none; margin: 4px 0; font-size: 11px;">
                                <button type="button" onclick="adjustStatAlloc('Fel', -1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">-</button>
                                <span id="cc-alloc-Fel" style="font-weight:bold; margin: 0 2px;">10</span>
                                <button type="button" onclick="adjustStatAlloc('Fel', 1)" style="padding:1px 5px; font-weight:bold; cursor:pointer;">+</button>
                            </div>
                            <input type="number" id="cc-stat-Fel" onchange="recalcWizardDerivedStats()" style="width:100%; text-align:center; border:none; font-weight:bold; font-size:15px; color:#1c130b;" value="30">
                        </div>
                    </div>

                    <!-- Derived Stats Summary Box -->
                    <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; background: #fff8ee; border: 1.5px solid #8b7961; border-radius: 4px; padding: 10px; text-align: center; font-size: 12px;">
                        <div><strong>Movement:</strong> <span id="cc-derived-move" style="font-weight:bold; color:#7a1717; font-size:14px;">4</span></div>
                        <div><strong>Wounds:</strong> <span id="cc-derived-wounds" style="font-weight:bold; color:#7a1717; font-size:14px;">12</span></div>
                        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center;">
                            <strong>Fate / Fortune:</strong>
                            <div style="display:flex; justify-content:center; align-items:center; gap:5px; margin-top:4px;">
                                <button type="button" onclick="adjustWizardExtraPoints('fate', -1)" style="padding:0 5px; cursor:pointer;">-</button>
                                <span id="cc-derived-fate" style="font-weight:bold; color:#7a1717; font-size:14px;">2 / 2</span>
                                <button type="button" onclick="adjustWizardExtraPoints('fate', 1)" style="padding:0 5px; cursor:pointer;">+</button>
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center;">
                            <strong>Resilience / Resolve:</strong>
                            <div style="display:flex; justify-content:center; align-items:center; gap:5px; margin-top:4px;">
                                <button type="button" onclick="adjustWizardExtraPoints('resilience', -1)" style="padding:0 5px; cursor:pointer;">-</button>
                                <span id="cc-derived-resilience" style="font-weight:bold; color:#7a1717; font-size:14px;">1 / 1</span>
                                <button type="button" onclick="adjustWizardExtraPoints('resilience', 1)" style="padding:0 5px; cursor:pointer;">+</button>
                            </div>
                        </div>
                        <div><strong>Starting XP Bonus:</strong> <span id="cc-derived-xp" style="font-weight:bold; color:#2e7d32; font-size:14px;">+20 XP</span></div>
                    </div>
                    <div id="cc-extra-points-tracker" style="text-align:center; font-size:12px; font-weight:bold; color:#7a1717; margin-top:8px;">
                        Extra Points Remaining: <span id="cc-extra-points-remaining">3</span>
                    </div>
                </fieldset>

                <div style="display: flex; justify-content: flex-end; gap: 10px;">
                    <button type="button" onclick="switchWizardStep(2)" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 20px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">NEXT: CLASS & CAREER ➔</button>
                </div>
            </div>

            <!-- STEP 2: CLASS & CAREER -->
            <div id="cc-step-2" style="display: none;">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">STEP 2: CLASS & CAREER DETERMINATION</legend>

                    <!-- Career Determination Mode Selector -->
                    <div style="display: flex; justify-content: space-between; align-items: center; background: #fff8ee; border: 1.5px solid #8b7961; padding: 10px 14px; border-radius: 4px; margin-bottom: 16px;">
                        <div style="display: flex; gap: 16px; align-items: center; font-size: 13px;">
                            <strong style="color: #7a1717;">Career Selection Mode:</strong>
                            <label style="cursor: pointer; font-weight: bold; color: #1c130b;">
                                <input type="radio" name="cc-career-mode" value="random" checked onchange="toggleWizardCareerMode()" style="accent-color: #7a1717;"> 🎲 Random Career Roll (+50 XP)
                            </label>
                            <label style="cursor: pointer; font-weight: bold; color: #1c130b;">
                                <input type="radio" name="cc-career-mode" value="select" onchange="toggleWizardCareerMode()" style="accent-color: #7a1717;"> ⚖ Select Class & Career (+0 XP)
                            </label>
                        </div>
                    </div>

                    <!-- Random Career Roll Action Bar -->
                    <div id="cc-career-random-bar" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                        <button type="button" onclick="rollWizardRandomCareer()" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 18px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">🎲 ROLL RANDOM CAREER (1d100 Table)</button>
                        <div id="cc-career-roll-status" style="font-size: 12px; font-weight: bold; color: #2e7d32;"></div>
                    </div>

                    <!-- Class & Career Inputs -->
                    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 14px;">
                        <div>
                            <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Class:</label>
                            <select id="cc-class-select" onchange="onWizardClassSelectChange()" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; font-weight:bold; color:#1c130b; padding:6px; border-radius:3px;">
                                <option value="Academics">Academics (Apothecary, Engineer, Lawyer, Physician, Scholar, Wizard)</option>
                                <option value="Burghers">Burghers (Agitator, Artisan, Beggar, Investigator, Merchant, Watchman)</option>
                                <option value="Courtiers">Courtiers (Advisor, Artist, Duellist, Envoy, Noble, Servant)</option>
                                <option value="Peasants">Peasants (Bailiff, Hedge Witch, Herbalist, Hunter, Miner, Villager)</option>
                                <option value="Rangers">Rangers (Bounty Hunter, Coachman, Entertainer, Flagellant, Road Warden)</option>
                                <option value="Riverfolk">Riverfolk (Boatman, Huffer, Riverwarden, Seaman, Smuggler, Stevedore)</option>
                                <option value="Rogues">Rogues (Baiter, Charlatan, Fence, Grave Robber, Outlaw, Racketeer, Thief)</option>
                                <option value="Warriors" selected>Warriors (Cavalryman, Guard, Knight, Pit Fighter, Protagonist, Soldier, Slayer)</option>
                            </select>
                        </div>
                        <div>
                            <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Career:</label>
                            <select id="cc-career-select" onchange="onWizardCareerSelectChange()" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; font-weight:bold; color:#1c130b; padding:6px; box-sizing:border-box; border-radius:3px;">
                                <!-- Dynamically populated based on chosen class -->
                            </select>
                            <input type="hidden" id="cc-career-input" value="Soldier">
                        </div>
                    </div>

                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;">
                        <div>
                            <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Career Level:</label>
                            <input type="text" id="cc-career-level" value="1 (Novice)" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:6px; box-sizing:border-box;">
                        </div>
                        <div>
                            <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Status Tier (Conformed):</label>
                            <input type="text" id="cc-status" value="Silver 1" readonly style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; font-weight:bold; color:#7a1717; padding:6px; box-sizing:border-box;">
                        </div>
                        <div>
                            <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Career XP Bonus:</label>
                            <div id="cc-career-xp-badge" style="font-size: 14px; font-weight: bold; color: #2e7d32; padding: 6px; background: #fff8ee; border: 1.5px solid #8b7961; border-radius: 3px; text-align: center;">+50 XP (Random Roll)</div>
                        </div>
                    </div>

                    <div style="margin-top: 14px;">
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Conformed Starter Kit Trappings:</label>
                        <textarea id="cc-starter-kit" rows="2" oninput="checkWizardOrTrappingChoices()" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:6px; box-sizing:border-box; border-radius:3px; resize:vertical; font-family:var(--font-body);"></textarea>
                    </div>

                    <!-- Required "OR" Trappings Choice Container -->
                    <div id="cc-or-choices-container" style="display: none; margin-top: 14px; background: #fff3cd; border: 2px solid #856404; padding: 12px; border-radius: 4px;">
                        <strong style="color: #856404; font-size: 13px; display: block; margin-bottom: 6px;">⚠️ Trapping Choice(s) Required: Please select your preferred item for each option below:</strong>
                        <div id="cc-or-choices-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
                    </div>
                </fieldset>

                <div style="display: flex; justify-content: space-between;">
                    <button type="button" onclick="switchWizardStep(1)" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">⬅ BACK</button>
                    <button type="button" onclick="switchWizardStep(3)" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 20px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">NEXT: DETAILS & AMBITIONS ➔</button>
                </div>
            </div>

            <!-- STEP 3: DETAILS & AMBITIONS -->
            <div id="cc-step-3" style="display: none;">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">STEP 3: PERSONAL DETAILS & AMBITIONS</legend>
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 14px;">
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Character Name:</label><input type="text" id="cc-name" value="Karl Franz" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; font-weight:bold; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Age:</label><input type="number" id="cc-age" value="25" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Height:</label><input type="text" id="cc-height" value="5'10&quot;" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Hair:</label><input type="text" id="cc-hair" value="Brown" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Eyes:</label><input type="text" id="cc-eyes" value="Blue" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Star Sign:</label><input type="text" id="cc-starsign" value="The Two Bullocks" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:13px; color:#1c130b; padding:5px; box-sizing:border-box;"></div>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Short-Term Ambition:</label>
                        <input type="text" id="cc-amb-short" value="Earn 5 Gold Crowns and buy a sturdy sword." style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:12px; color:#1c130b; padding:5px; box-sizing:border-box;">
                    </div>
                    <div>
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">Long-Term Ambition:</label>
                        <input type="text" id="cc-amb-long" value="Become a recognized Captain in the Reikland Guard." style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:12px; color:#1c130b; padding:5px; box-sizing:border-box;">
                    </div>
                </fieldset>

                <div style="display: flex; justify-content: space-between;">
                    <button type="button" onclick="switchWizardStep(2)" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">⬅ BACK</button>
                    <button type="button" onclick="switchWizardStep(4)" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 20px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">NEXT: REVIEW & FINISH ➔</button>
                </div>
            </div>

            <!-- STEP 4: REVIEW & FINISH -->
            <div id="cc-step-4" style="display: none;">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">STEP 4: CONFIRM & CREATE CHARACTER</legend>
                    <div id="cc-review-summary" style="font-size: 13px; color: #1c130b;">
                        <!-- Dynamic summary inserted here -->
                    </div>
                </fieldset>

                <div style="display: flex; justify-content: space-between;">
                    <button type="button" onclick="switchWizardStep(3)" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">⬅ BACK</button>
                    <button type="button" onclick="finishCharacterCreationWizard()" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 10px 24px; font-family: var(--font-title); font-weight: bold; font-size: 14px; cursor: pointer; border-radius: 4px; box-shadow: 0 0 15px rgba(122,23,23,0.6);">⚜ CREATE CHARACTER & ADD TO PARTY</button>
                </div>
            </div>

        </div>
    </div>

    <!-- WFRP 4E Core Rulebook Character Sheet Overlay Modal -->
    <div id="char-sheet-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(10,8,6,0.94); z-index: 25000; padding: 20px; box-sizing: border-box; overflow-y: auto;">
        <datalist id="trappings-list"></datalist>
        <datalist id="weapons-list"></datalist>
        <datalist id="armour-list"></datalist>
        <datalist id="hirelings-list"></datalist>
        <div style="max-width: 1020px; margin: 10px auto; background: #f4e7d0; border: 4px double #5c4732; border-radius: 4px; color: #1c130b; font-family: var(--font-body); font-size: 14px; padding: 28px; box-shadow: 0 0 45px rgba(0,0,0,0.9); position: relative;">
            
            <!-- Modal Header Bar -->
            <div style="border-bottom: 3px double #7a1717; padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
                <div id="modal-char-title" style="font-family: var(--font-title); font-size: 22px; font-weight: bold; color: #7a1717; letter-spacing: 1.5px;">⚜ WARHAMMER FANTASY ROLEPLAY CHARACTER SHEET ⚜</div>
                <div style="display: flex; gap: 8px;">
                    <button onclick="openDeleteConfirmModal()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 14px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 3px;">🗑️ DELETE</button>
                    <button onclick="closeCharSheetModal()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 6px 16px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 3px;">✖ CLOSE</button>
                </div>
            </div>

            <!-- Navigation Tabs -->
            <div style="display: flex; gap: 10px; margin-bottom: 22px; border-bottom: 2px solid #8b7961; padding-bottom: 10px;">
                <button id="tab-btn-p344" onclick="switchModalTab('p344')" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 10px 20px; font-family: var(--font-title); font-size: 13px; font-weight: bold; cursor: pointer; border-radius: 4px;">CORE & SKILLS</button>
                <button id="tab-btn-p345" onclick="switchModalTab('p345')" style="background: #3a2a1a; color: #dcd0bc; border: 2px solid #5c4732; padding: 10px 20px; font-family: var(--font-title); font-size: 13px; cursor: pointer; border-radius: 4px;">COMBAT & WEALTH</button>
                <button id="tab-btn-ambitions" onclick="switchModalTab('ambitions')" style="background: #3a2a1a; color: #dcd0bc; border: 2px solid #5c4732; padding: 10px 20px; font-family: var(--font-title); font-size: 13px; cursor: pointer; border-radius: 4px;">AMBITIONS</button>
                <button id="tab-btn-questions" onclick="switchModalTab('questions')" style="background: #3a2a1a; color: #dcd0bc; border: 2px solid #5c4732; padding: 10px 20px; font-family: var(--font-title); font-size: 13px; cursor: pointer; border-radius: 4px;">TEN QUESTIONS</button>
            </div>

            <!-- TAB 1: CORE & SKILLS -->
            <div id="modal-tab-p344">
                <!-- Personal Details Block -->
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">PERSONAL DETAILS</legend>
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; font-size: 13px;">
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Name:</label><input type="text" id="m-char-name" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; font-weight:bold; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Species:</label><input type="text" id="m-char-race" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Class:</label><input type="text" id="m-char-class" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Career:</label><input type="text" id="m-char-career" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Career Level:</label><input type="text" id="m-char-level" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Career Path:</label><input type="text" id="m-char-path" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Status:</label><input type="text" id="m-char-status" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Age:</label><input type="number" id="m-char-age" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Height:</label><input type="text" id="m-char-height" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Hair:</label><input type="text" id="m-char-hair" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Eyes:</label><input type="text" id="m-char-eyes" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Dooming:</label><input type="text" id="m-char-doomed" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Star Sign:</label><input type="text" id="m-char-starsign" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                        <div style="grid-column: span 3;"><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:3px;">Motivation:</label><input type="text" id="m-char-motivation" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:4px 6px; box-sizing:border-box;"></div>
                    </div>
                </fieldset>

                <!-- Characteristics Grid (10 Stats) -->
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">CHARACTERISTICS</legend>
                    <div style="display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; text-align: center;">
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">WS</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-WS-init" oninput="calcStatTotal('WS')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-WS-adv" oninput="calcStatTotal('WS')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-WS-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">BS</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-BS-init" oninput="calcStatTotal('BS')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-BS-adv" oninput="calcStatTotal('BS')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-BS-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">S</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-S-init" oninput="calcStatTotal('S')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-S-adv" oninput="calcStatTotal('S')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-S-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">T</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-T-init" oninput="calcStatTotal('T')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-T-adv" oninput="calcStatTotal('T')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-T-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">I</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-I-init" oninput="calcStatTotal('I')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-I-adv" oninput="calcStatTotal('I')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-I-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">Ag</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-Ag-init" oninput="calcStatTotal('Ag')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-Ag-adv" oninput="calcStatTotal('Ag')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-Ag-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">Dex</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-Dex-init" oninput="calcStatTotal('Dex')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-Dex-adv" oninput="calcStatTotal('Dex')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-Dex-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">Int</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-Int-init" oninput="calcStatTotal('Int')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-Int-adv" oninput="calcStatTotal('Int')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-Int-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">WP</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-WP-init" oninput="calcStatTotal('WP')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-WP-adv" oninput="calcStatTotal('WP')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-WP-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                        <div>
                            <div style="font-family:var(--font-title); font-weight:bold; background:#7a1717; color:#f5ebd9; padding:4px 0; font-size:13px; border-radius:3px 3px 0 0;">Fel</div>
                            <div style="font-size:10px; color:#666; margin-top:2px;">Initial</div>
                            <input type="number" id="m-stat-Fel-init" oninput="calcStatTotal('Fel')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; color:#666; margin-top:2px;">Adv</div>
                            <input type="number" id="m-stat-Fel-adv" oninput="calcStatTotal('Fel')" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b; padding:3px 0;">
                            <div style="font-size:10px; font-weight:bold; color:#7a1717; margin-top:2px;">Total</div>
                            <input type="number" id="m-stat-Fel-tot" readonly style="width:100%; text-align:center; border:2px solid #7a1717; background:#fcefdc; font-weight:bold; font-size:15px; color:#7a1717; padding:3px 0;">
                        </div>
                    </div>
                </fieldset>

                <!-- Pools & Derived Values -->
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px;">
                    <!-- Fate & Fortune -->
                    <div style="border: 1.5px solid #8b7961; border-radius: 4px; padding: 12px; background: #faf4e8; font-size: 13px;">
                        <div style="font-family:var(--font-title); font-weight:bold; color:#7a1717; border-bottom: 1.5px solid #8b7961; margin-bottom: 8px; padding-bottom: 4px;">FATE & FORTUNE</div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
                            <span style="font-weight:bold; color:#2b1f14;">Fate:</span><input type="number" id="m-char-fate-total" style="width: 50px; text-align:center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 2px;">
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight:bold; color:#2b1f14;">Fortune:</span><input type="number" id="m-char-fortune-curr" style="width: 50px; text-align:center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 2px;">
                        </div>
                    </div>

                    <!-- Resilience & Resolve -->
                    <div style="border: 1.5px solid #8b7961; border-radius: 4px; padding: 12px; background: #faf4e8; font-size: 13px;">
                        <div style="font-family:var(--font-title); font-weight:bold; color:#7a1717; border-bottom: 1.5px solid #8b7961; margin-bottom: 8px; padding-bottom: 4px;">RESILIENCE & RESOLVE</div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
                            <span style="font-weight:bold; color:#2b1f14;">Resilience:</span><input type="number" id="m-char-resilience-tot" style="width: 50px; text-align:center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 2px;">
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight:bold; color:#2b1f14;">Resolve:</span><input type="number" id="m-char-resolve-curr" style="width: 50px; text-align:center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 2px;">
                        </div>
                    </div>

                    <!-- Movement -->
                    <div style="border: 1.5px solid #8b7961; border-radius: 4px; padding: 12px; background: #faf4e8; font-size: 13px;">
                        <div style="font-family:var(--font-title); font-weight:bold; color:#7a1717; border-bottom: 1.5px solid #8b7961; margin-bottom: 8px; padding-bottom: 4px;">MOVEMENT</div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
                            <span style="font-weight:bold; color:#2b1f14;">Move (M):</span><input type="number" id="m-char-move-base" oninput="calcMovement()" style="width: 45px; text-align:center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 2px;">
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size: 12px; color:#4a1212; font-weight: bold;">
                            <span>Walk: <input type="number" id="m-char-move-walk" readonly style="width: 30px; border:none; background:transparent; font-weight:bold; font-size:13px; color:#7a1717;"></span>
                            <span>Run: <input type="number" id="m-char-move-run" readonly style="width: 30px; border:none; background:transparent; font-weight:bold; font-size:13px; color:#7a1717;"></span>
                        </div>
                    </div>

                    <!-- Experience (XP) -->
                    <div style="border: 1.5px solid #8b7961; border-radius: 4px; padding: 12px; background: #faf4e8; font-size: 13px;">
                        <div style="font-family:var(--font-title); font-weight:bold; color:#7a1717; border-bottom: 1.5px solid #8b7961; margin-bottom: 8px; padding-bottom: 4px;">EXPERIENCE (XP)</div>
                        <div style="display:flex; justify-content:space-between; margin-bottom: 4px;"><span>Current:</span><input type="number" id="m-char-xp-curr" style="width: 55px; text-align:center; border: 1.5px solid #8b7961; font-size: 13px; font-weight: bold; color: #1c130b; padding: 1px;"></div>
                        <div style="display:flex; justify-content:space-between; margin-bottom: 4px;"><span>Spent:</span><input type="number" id="m-char-xp-spent" style="width: 55px; text-align:center; border: 1.5px solid #8b7961; font-size: 13px; font-weight: bold; color: #1c130b; padding: 1px;"></div>
                        <div style="display:flex; justify-content:space-between;"><span>Total:</span><input type="number" id="m-char-xp-tot" style="width: 55px; text-align:center; border: 1.5px solid #8b7961; font-size: 13px; font-weight: bold; color: #1c130b; padding: 1px;"></div>
                    </div>
                </div>

                <!-- 25 Basic Skills Interactive Grid -->
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; margin-bottom: 20px; background: #faf4e8;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">25 BASIC SKILLS</legend>
                    <div id="m-basic-skills-grid" style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;"></div>
                </fieldset>

                <!-- Advanced Skills & Talents -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 20px;">
                    <div>
                        <label style="font-family:var(--font-title); font-weight:bold; color:#7a1717; font-size:14px; display:block; margin-bottom:4px;">ADVANCED & GROUPED SKILLS:</label>
                        <textarea id="m-char-skills" rows="4" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:8px; box-sizing:border-box; border-radius:3px;"></textarea>
                    </div>
                    <div>
                        <label style="font-family:var(--font-title); font-weight:bold; color:#7a1717; font-size:14px; display:block; margin-bottom:4px;">TALENTS & QUALITIES:</label>
                        <textarea id="m-char-talents" rows="4" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:8px; box-sizing:border-box; border-radius:3px;"></textarea>
                    </div>
                </div>
            </div>

                        <!-- TAB 2: COMBAT & WEALTH (AUTHENTIC WFRP PAGE 345 TABLES) -->
            <div id="modal-tab-p345" style="display: none;">
                
                <!-- Top Row: Wounds Calculator & Armour AP Diagram -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
                    <!-- Wounds Calculator -->
                    <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                        <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">WOUNDS CALCULATOR (SB + TBx2 + WPB + Hardy)</legend>
                        <div style="display: flex; gap: 10px; align-items: center; font-size: 13px; margin-bottom: 12px;">
                            <span>SB: <input type="number" id="m-wnd-sb" readonly style="width:35px; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#7a1717;"></span>
                            <span>+ TBx2: <input type="number" id="m-wnd-tb2" readonly style="width:38px; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#7a1717;"></span>
                            <span>+ WPB: <input type="number" id="m-wnd-wpb" readonly style="width:35px; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#7a1717;"></span>
                            <span>+ Hardy: <input type="number" id="m-wnd-hardy" oninput="calcWoundsFormula()" style="width:35px; text-align:center; border:1.5px solid #8b7961; font-size:13px; font-weight:bold; color:#1c130b;" value="0"></span>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: center; border-top: 1.5px solid #8b7961; padding-top: 10px;">
                            <div><label style="font-weight:bold; color:#7a1717; font-size:14px;">Max Wounds:</label> <input type="number" id="m-char-wounds-max" style="width:55px; text-align:center; border:2px solid #7a1717; font-weight:bold; font-size:16px; color:#7a1717; background:#fff;"></div>
                            <div><label style="font-weight:bold; color:#7a1717; font-size:14px;">Current Wounds:</label> <input type="number" id="m-char-wounds-curr" style="width:55px; text-align:center; border:2px solid #7a1717; font-weight:bold; font-size:16px; color:#7a1717; background:#fff;"></div>
                        </div>
                    </fieldset>

                    <!-- Armour Locations AP Diagram -->
                    <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                        <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">ARMOUR POINTS (AP) DIAGRAM</legend>
                        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; font-size: 12px; text-align: center;">
                            <div><span style="font-weight:bold; color:#7a1717;">Head (01-09)</span><input type="number" id="m-arm-head" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                            <div><span style="font-weight:bold; color:#7a1717;">Body (45-79)</span><input type="number" id="m-arm-body" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                            <div><span style="font-weight:bold; color:#7a1717;">L.Arm (10-24)</span><input type="number" id="m-arm-larm" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                            <div><span style="font-weight:bold; color:#7a1717;">R.Arm (25-44)</span><input type="number" id="m-arm-rarm" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                            <div><span style="font-weight:bold; color:#7a1717;">L.Leg (80-89)</span><input type="number" id="m-arm-lleg" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                            <div><span style="font-weight:bold; color:#7a1717;">R.Leg (90-00)</span><input type="number" id="m-arm-rleg" style="width:100%; text-align:center; border:1.5px solid #8b7961; font-size:14px; font-weight:bold; color:#1c130b;"></div>
                        </div>
                    </fieldset>
                </div>

                <!-- SECTION 1: WEAPONS TABLE (PAGE 345) -->
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8; margin-bottom: 20px;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">⚔️ WEAPONS TABLE</legend>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #1c130b;">
                        <thead>
                            <tr style="background: #3d2f23; color: #f7efe2; font-family: var(--font-title); font-size: 12px; text-align: left;">
                                <th style="padding: 6px; border: 1px solid #231911; width: 110px;">Base Type (Derived)</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 140px;">Specific Name (Editable)</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 75px;">Group</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 45px; text-align: center;">Enc</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 90px;">Range/Reach</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 75px;">Damage</th>
                                <th style="padding: 6px; border: 1px solid #231911;">Qualities & Flaws</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 35px; text-align: center;"></th>
                            </tr>
                        </thead>
                        <tbody id="m-weapons-table-body">
                            <!-- Dynamic weapon rows inserted here -->
                        </tbody>
                    </table>
                    <div style="margin-top: 8px;">
                        <button type="button" onclick="addWeaponRow()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 10px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD WEAPON ROW</button>
                    </div>
                </fieldset>

                <!-- SECTION 2: SPELLS AND PRAYERS TABLE (PAGE 345) -->
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8; margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">✨ SPELLS AND PRAYERS TABLE</legend>
                        <div style="font-size: 13px; font-weight: bold; color: #7a1717; background: #fffbf4; border: 1.5px solid #7a1717; padding: 4px 10px; border-radius: 4px;">
                            Sin Points: <input type="number" id="m-char-sin" style="width: 45px; text-align: center; border: 1px solid #8b7961; font-weight: bold; font-size: 14px; color: #7a1717;" value="0">
                        </div>
                    </div>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #1c130b; margin-top: 8px;">
                        <thead>
                            <tr style="background: #3d2f23; color: #f7efe2; font-family: var(--font-title); font-size: 12px; text-align: left;">
                                <th style="padding: 6px; border: 1px solid #231911;">Name</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 55px; text-align: center;">TN</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 90px;">Range</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 90px;">Target</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 90px;">Duration</th>
                                <th style="padding: 6px; border: 1px solid #231911;">Effect</th>
                                <th style="padding: 6px; border: 1px solid #231911; width: 35px; text-align: center;"></th>
                            </tr>
                        </thead>
                        <tbody id="m-spells-table-body">
                            <!-- Dynamic spell rows inserted here -->
                        </tbody>
                    </table>
                    <div style="margin-top: 8px;">
                        <button type="button" onclick="openSpellSelectModal()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 10px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD SPELL / PRAYER ROW</button>
                    </div>
                </fieldset>

                <!-- SECTION 3: TRAPPINGS, ENCUMBRANCE SUMMARY & WEALTH (PAGE 345) -->
                <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 20px; align-items: start;">
                    
                    <!-- Left Column: Trappings & Hirelings -->
                    <div style="display: flex; flex-direction: column; gap: 16px;">
                        
                        <!-- Left: Trappings Detailed Table -->
                        <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                            <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">🎒 TRAPPINGS TABLE</legend>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #1c130b;">
                                <thead>
                                    <tr style="background: #3d2f23; color: #f7efe2; font-family: var(--font-title); font-size: 12px; text-align: left;">
                                        <th style="padding: 6px; border: 1px solid #231911; width: 55px; text-align: center;">Equipped</th>
                                        <th style="padding: 6px; border: 1px solid #231911;">Name / Description</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 55px; text-align: center;">Enc</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 140px;">Locations / AP</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 35px; text-align: center;"></th>
                                    </tr>
                                </thead>
                                <tbody id="m-trappings-table-body">
                                    <!-- Dynamic trapping rows inserted here -->
                                </tbody>
                            </table>
                            <div style="margin-top: 8px;">
                                <button type="button" onclick="addTrappingRow()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 10px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD TRAPPING ROW</button>
                            </div>
                        </fieldset>

                        <!-- Left: Hirelings Detailed Table -->
                        <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                            <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">🤝 HIRELINGS & RETAINERS</legend>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #1c130b;">
                                <thead>
                                    <tr style="background: #3d2f23; color: #f7efe2; font-family: var(--font-title); font-size: 12px; text-align: left;">
                                        <th style="padding: 6px; border: 1px solid #231911;">Name / Role</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 65px; text-align: center;">Daily Cost</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 140px;">Notes</th>
                                        <th style="padding: 6px; border: 1px solid #231911; width: 35px; text-align: center;"></th>
                                    </tr>
                                </thead>
                                <tbody id="m-hirelings-table-body">
                                    <!-- Dynamic hirelings rows inserted here -->
                                </tbody>
                            </table>
                            <div style="margin-top: 8px;">
                                <button type="button" onclick="addHirelingRow()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 4px 10px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">➕ ADD HIRELING</button>
                            </div>
                        </fieldset>

                    </div>

                    <!-- Right: Encumbrance Summary & Wealth Tables -->
                    <div style="display: flex; flex-direction: column; gap: 16px;">
                        
                        <!-- Encumbrance Summary Box (Page 345) -->
                        <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                            <legend style="font-family: var(--font-title); font-weight: bold; font-size: 14px; color: #7a1717; padding: 0 8px;">ENCUMBRANCE</legend>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px; color: #1c130b;">
                                <tr><td style="padding: 4px; font-weight: bold;">Weapons:</td><td style="text-align: right;"><input type="number" id="m-enc-weapons" oninput="calcEncSummary()" style="width: 55px; text-align: center; border: 1px solid #8b7961; font-weight: bold;" value="0"></td></tr>
                                <tr><td style="padding: 4px; font-weight: bold;">Armour:</td><td style="text-align: right;"><input type="number" id="m-enc-armour" oninput="calcEncSummary()" style="width: 55px; text-align: center; border: 1px solid #8b7961; font-weight: bold;" value="0"></td></tr>
                                <tr><td style="padding: 4px; font-weight: bold;">Trappings:</td><td style="text-align: right;"><input type="number" id="m-enc-trappings" oninput="calcEncSummary()" style="width: 55px; text-align: center; border: 1px solid #8b7961; font-weight: bold;" value="0"></td></tr>
                                <tr style="border-top: 1px solid #8b7961;"><td style="padding: 4px; font-weight: bold; color: #7a1717;">Max Enc.:</td><td style="text-align: right;"><input type="number" id="m-enc-max" style="width: 55px; text-align: center; border: 1.5px solid #7a1717; font-weight: bold; color: #7a1717; background: #fff;" value="6"></td></tr>
                                <tr><td style="padding: 4px; font-weight: bold; color: #7a1717;">Total:</td><td style="text-align: right;"><input type="number" id="m-enc-curr" readonly style="width: 55px; text-align: center; border: 1.5px solid #7a1717; font-weight: bold; color: #7a1717; background: #fcefdc;" value="0"></td></tr>
                            </table>
                        </fieldset>

                        <!-- Wealth & Money Box -->
                        <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 14px; background: #faf4e8;">
                            <legend style="font-family: var(--font-title); font-weight: bold; font-size: 14px; color: #7a1717; padding: 0 8px;">💰 WEALTH & MONEY</legend>
                            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; text-align: center; font-size: 12px; font-weight: bold;">
                                <div><span style="color: #b8860b;">GC (Gold)</span><input type="number" id="m-money-gc" style="width: 100%; text-align: center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 3px 0;" value="0"></div>
                                <div><span style="color: #708090;">ss (Silver)</span><input type="number" id="m-money-ss" style="width: 100%; text-align: center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 3px 0;" value="0"></div>
                                <div><span style="color: #8b4513;">d (Brass)</span><input type="number" id="m-money-bp" style="width: 100%; text-align: center; border: 1.5px solid #8b7961; font-size: 14px; font-weight: bold; color: #1c130b; padding: 3px 0;" value="0"></div>
                            </div>
                        </fieldset>

                        <!-- Corruption & Psychology -->
                        <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 10px; background: #faf4e8;">
                            <legend style="font-family: var(--font-title); font-weight: bold; font-size: 13px; color: #7a1717; padding: 0 6px;">CORRUPTION & MUTATIONS</legend>
                            <div style="display: flex; gap: 8px; align-items: center; font-size: 12px; margin-bottom: 6px;">
                                <span>Corruption: <input type="number" id="m-char-corr-curr" style="width:35px; text-align:center; border:1px solid #8b7961; font-weight:bold;" value="0"> / <input type="number" id="m-char-corr-max" style="width:35px; text-align:center; border:1px solid #8b7961; font-weight:bold;" value="6"></span>
                            </div>
                            <textarea id="m-char-psychology" rows="2" placeholder="Psychology & Mutations..." style="width: 100%; border: 1.5px solid #8b7961; background: #fff8ee; font-size: 12px; color: #1c130b; padding: 4px; box-sizing: border-box; border-radius: 3px;"></textarea>
                        </fieldset>

                    </div>

                </div>

            </div>

<!-- TAB 3: AMBITIONS -->
            <div id="modal-tab-ambitions" style="display: none;">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; background: #faf4e8; font-size: 13px;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">PARTY & PERSONAL AMBITIONS</legend>
                    <div style="margin-bottom: 12px;">
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Short-Term Ambition:</label>
                        <input type="text" id="m-amb-short" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:6px; box-sizing:border-box;">
                    </div>
                    <div style="margin-bottom: 12px;">
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Long-Term Ambition:</label>
                        <input type="text" id="m-amb-long" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:6px; box-sizing:border-box;">
                    </div>
                    <div>
                        <label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:4px;">Party Ambition:</label>
                        <input type="text" id="m-amb-party" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:13px; color:#1c130b; padding:6px; box-sizing:border-box;">
                    </div>
                </fieldset>
            </div>

            <!-- TAB 4: TEN QUESTIONS -->
            <div id="modal-tab-questions" style="display: none;">
                <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 16px; background: #faf4e8; font-size: 13px;">
                    <legend style="font-family: var(--font-title); font-weight: bold; font-size: 15px; color: #7a1717; padding: 0 8px;">TEN QUESTIONS</legend>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">1. Where are you from?</label><input type="text" id="m-q-origin" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">2. What is your family like?</label><input type="text" id="m-q-family" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">3. What was your childhood like?</label><input type="text" id="m-q-childhood" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">4. Why did you leave your home?</label><input type="text" id="m-q-why_leave" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">5. Who are your best friends?</label><input type="text" id="m-q-friends" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">6. What is your greatest desire?</label><input type="text" id="m-q-desire" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">7. What is your best/worst memory?</label><input type="text" id="m-q-memories" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">8. What is your religion?</label><input type="text" id="m-q-religion" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">9. To whom are you loyal?</label><input type="text" id="m-q-loyalty" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                        <div><label style="font-weight:bold; color:#4a1212; display:block; margin-bottom:2px;">10. What is your deepest secret?</label><input type="text" id="m-q-secret" style="width:100%; border:1.5px solid #8b7961; background:#fff8ee; font-size:12px; color:#1c130b; padding:4px;"></div>
                    </div>
                </fieldset>
            </div>

            <!-- Modal Footer Action Bar -->
            <div style="border-top: 3px double #7a1717; padding-top: 14px; margin-top: 22px; display: flex; justify-content: flex-end; gap: 12px;">
                <button onclick="openDeleteConfirmModal()" style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 18px; font-family: var(--font-title); font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px; transition: background 0.2s;">🗑️ DELETE CHARACTER</button>
                <button onclick="closeCharSheetModal()" style="background: #3d2f23; color: #f7efe2; border: 1.5px solid #231911; padding: 8px 18px; font-weight: bold; font-size: 13px; cursor: pointer; border-radius: 4px;">CANCEL</button>
                <button id="save-char-sheet-modal-btn" onclick="saveModalCharSheet()" style="background: #7a1717; color: #f5ebd9; border: 2px solid #d4af37; padding: 8px 24px; font-family: var(--font-title); font-weight: bold; font-size: 14px; cursor: pointer; border-radius: 4px; box-shadow: 0 0 12px rgba(122,23,23,0.6);">💾 SAVE CHARACTER SHEET</button>
            </div>
        </div>
    </div>

    <!-- Onboarding Setup Wizard Overlay Modal -->
    <div id="wizard-modal" class="o7-modal" style="display: none;" role="dialog" aria-modal="true" aria-label="Appliance initialization wizard">
        <div class="o7-modal-panel">
            <div class="o7-modal-head">
                <div>
                    <h2 style="font-size:14px; letter-spacing:0.12em; color:var(--ink);">Appliance Initialization</h2>
                    <div id="wizard-step-label" class="o7-label" style="margin-top:4px;">Step 1 of 4</div>
                </div>
                <div style="display:flex; align-items:center; gap:12px;">
                    <div class="o7-steps" id="wizard-dots" aria-hidden="true">
                        <span class="active"></span><span></span><span></span><span></span>
                    </div>
                    <button type="button" class="o7-btn o7-btn-ghost o7-btn-sm" onclick="o7CloseWizard()" aria-label="Close the wizard">Close</button>
                </div>
            </div>

            <!-- Step 1: Wi-Fi -->
            <div class="wizard-step o7-wizard-body" id="w-step-1">
                <p class="o7-lede">Connect the servo-skull to your home Wi-Fi so it can be reached remotely and receive machine-spirit updates.</p>
                <div class="o7-field">
                    <label for="w-wifi-ssid">Wi-Fi network (SSID)</label>
                    <div class="o7-aux-row">
                        <input type="text" id="w-wifi-ssid" placeholder="Home Wi-Fi name">
                        <button type="button" class="o7-btn" onclick="scanWizardWifi()">📶 Scan</button>
                    </div>
                </div>
                <div class="o7-field">
                    <label for="w-wifi-pass">Wi-Fi password</label>
                    <input type="password" id="w-wifi-pass" placeholder="Network password">
                </div>
                <div id="w-wifi-result" class="o7-field-note"></div>
                <div class="o7-wizard-actions">
                    <span></span>
                    <button type="button" class="o7-btn o7-btn-primary" onclick="o7WizardStep(2)">Next: identity &gt;</button>
                </div>
            </div>

            <!-- Step 2: Identity -->
            <div class="wizard-step o7-wizard-body" id="w-step-2" style="display: none;">
                <p class="o7-lede">Designate the unit's name and its primary vocal personality archetype.</p>
                <div class="o7-field">
                    <label for="w-skull-name">Skull name / designation</label>
                    <input type="text" id="w-skull-name" value="Omega-7">
                </div>
                <div class="o7-field">
                    <label for="w-personality">Personality archetype</label>
                    <select id="w-personality">
                        <option value="Imperial Servo Skull">Imperial Servo Skull (Adeptus Mechanicus / Warhammer 40k)</option>
                        <option value="Golden Retriever">Golden Retriever (upbeat, loyal, enthusiastic)</option>
                        <option value="Custom Archetype">Custom archetype</option>
                    </select>
                </div>
                <div class="o7-wizard-actions">
                    <button type="button" class="o7-btn o7-btn-ghost" onclick="o7WizardStep(1)">&lt; Back</button>
                    <button type="button" class="o7-btn o7-btn-primary" onclick="o7WizardStep(3)">Next: master profile &gt;</button>
                </div>
            </div>

            <!-- Step 3: Master profile -->
            <div class="wizard-step o7-wizard-body" id="w-step-3" style="display: none;">
                <p class="o7-lede">Tell the skull who it serves, so it can address you properly and localise what it reports.</p>
                <div class="o7-field">
                    <label for="w-master-name">Your name</label>
                    <input type="text" id="w-master-name" placeholder="e.g. Sean, Sarah">
                </div>
                <div class="o7-field">
                    <label for="w-master-honorific">Preferred honorific / title</label>
                    <input type="text" id="w-master-honorific" placeholder="e.g. Master, Mistress, Lord, Captain, Magos">
                </div>
                <div class="o7-field">
                    <label for="w-master-city">City / location (for weather)</label>
                    <input type="text" id="w-master-city" placeholder="e.g. Seattle, WA">
                </div>
                <div class="o7-field">
                    <label for="w-master-interests">Primary interests / hobbies</label>
                    <input type="text" id="w-master-interests" placeholder="e.g. 3D printing, Warhammer 40k">
                </div>
                <div class="o7-wizard-actions">
                    <button type="button" class="o7-btn o7-btn-ghost" onclick="o7WizardStep(2)">&lt; Back</button>
                    <button type="button" class="o7-btn o7-btn-primary" onclick="o7WizardStep(4)">Next: API credentials &gt;</button>
                </div>
            </div>

            <!-- Step 4: API credentials -->
            <div class="wizard-step o7-wizard-body" id="w-step-4" style="display: none;">
                <p class="o7-lede">Enter your cloud API keys. Test each one to verify it before finishing initialization. Keys stay on the unit.</p>

                <div class="o7-field">
                    <label for="w-key-anthropic">Anthropic API key &mdash; required for the Claude brain</label>
                    <div class="o7-aux-row">
                        <input type="password" id="w-key-anthropic" placeholder="sk-ant-api03-...">
                        <button type="button" class="o7-btn" onclick="testWizardKey('anthropic')">Test key</button>
                    </div>
                    <div id="w-res-anthropic" class="o7-field-note"></div>
                </div>

                <div class="o7-field">
                    <label for="w-key-elevenlabs">ElevenLabs API key &mdash; optional cloud voice</label>
                    <div class="o7-aux-row">
                        <input type="password" id="w-key-elevenlabs" placeholder="Optional ElevenLabs API key">
                        <button type="button" class="o7-btn" onclick="testWizardKey('elevenlabs')">Test key</button>
                    </div>
                    <div id="w-res-elevenlabs" class="o7-field-note"></div>
                </div>

                <div class="o7-field">
                    <label for="w-key-openai">OpenAI API key &mdash; optional transcription</label>
                    <div class="o7-aux-row">
                        <input type="password" id="w-key-openai" placeholder="Optional OpenAI API key">
                        <button type="button" class="o7-btn" onclick="testWizardKey('openai')">Test key</button>
                    </div>
                    <div id="w-res-openai" class="o7-field-note"></div>
                </div>

                <div class="o7-wizard-actions">
                    <button type="button" class="o7-btn o7-btn-ghost" onclick="o7WizardStep(3)">&lt; Back</button>
                    <button type="button" class="o7-btn o7-btn-primary" onclick="finishWizard()">⚙ Initialize machine spirit</button>
                </div>
            </div>
        </div>
    </div>


<!-- WFRP 4E SPELL & PRAYER SELECTION MODAL -->
<div id="spell-select-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 30000; justify-content: center; align-items: center; padding: 20px;">
    <div style="background: #f7efe2; border: 3px solid #7a1717; box-shadow: 0 10px 30px rgba(0,0,0,0.8); width: 850px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column; border-radius: 6px; overflow: hidden;">
        
        <!-- Header -->
        <div style="background: #7a1717; color: #f7efe2; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #4a0e0e;">
            <div style="font-family: var(--font-title); font-size: 18px; font-weight: bold; letter-spacing: 1px;">✨ SELECT SPELL OR PRAYER (WFRP 4E)</div>
            <button type="button" onclick="closeSpellSelectModal()" style="background: transparent; border: none; color: #f7efe2; font-size: 20px; cursor: pointer; font-weight: bold;">✖</button>
        </div>

        <!-- Sub-Navigation Category Tabs -->
        <div style="display: flex; gap: 4px; background: #e3d3bd; padding: 8px 14px; border-bottom: 1.5px solid #8b7961; overflow-x: auto;">
            <button type="button" class="spell-cat-tab active" id="sp-tab-petty" onclick="switchSpellCategory('petty')" style="background: #7a1717; color: #fff; border: 1px solid #4a0e0e; padding: 6px 12px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">✨ PETTY SPELLS</button>
            <button type="button" class="spell-cat-tab" id="sp-tab-arcane" onclick="switchSpellCategory('arcane')" style="background: #faf4e8; color: #1c130b; border: 1px solid #8b7961; padding: 6px 12px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">⚡ ARCANE SPELLS</button>
            <button type="button" class="spell-cat-tab" id="sp-tab-blessings" onclick="switchSpellCategory('blessings')" style="background: #faf4e8; color: #1c130b; border: 1px solid #8b7961; padding: 6px 12px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">🙏 BLESSINGS</button>
            <button type="button" class="spell-cat-tab" id="sp-tab-miracles" onclick="switchSpellCategory('miracles')" style="background: #faf4e8; color: #1c130b; border: 1px solid #8b7961; padding: 6px 12px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px;">⚔️ MIRACLES</button>
            <button type="button" onclick="selectBlankSpell()" style="background: #3d2f23; color: #f7efe2; border: 1px solid #1c130b; padding: 6px 12px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px; margin-left: auto;">✏️ ADD BLANK ROW</button>
        </div>

        <!-- Filter & Search Bar -->
        <div style="padding: 10px 18px; background: #faf4e8; border-bottom: 1px solid #d4c4ad; display: flex; gap: 10px; align-items: center;">
            <input type="text" id="spell-search-inp" oninput="filterSpellList()" placeholder="🔍 Search spell name or effect..." style="flex: 1; padding: 6px 10px; border: 1.5px solid #8b7961; border-radius: 4px; font-size: 13px; background: #fff8ee;">
        </div>

        <!-- Spell List Viewport -->
        <div id="spell-list-container" style="flex: 1; overflow-y: auto; padding: 14px 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <!-- Spell cards dynamically rendered here -->
        </div>

        <!-- Footer -->
        <div style="background: #e3d3bd; padding: 10px 18px; border-top: 1.5px solid #8b7961; text-align: right;">
            <button type="button" onclick="closeSpellSelectModal()" style="background: #7a1717; color: #fff; border: 1px solid #4a0e0e; padding: 6px 16px; font-family: var(--font-title); font-weight: bold; cursor: pointer; border-radius: 3px;">CANCEL</button>
        </div>

    </div>
</div>



<!-- WFRP 4E WEAPON QUALITIES & FLAWS MODAL -->
<div id="qualities-select-modal" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75); z-index: 30000; justify-content: center; align-items: center; padding: 20px;">
    <div style="background: #f7efe2; border: 3px solid #7a1717; box-shadow: 0 10px 30px rgba(0,0,0,0.8); width: 750px; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column; border-radius: 6px; overflow: hidden;">
        
        <!-- Header -->
        <div style="background: #7a1717; color: #f7efe2; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #4a0e0e;">
            <div style="font-family: var(--font-title); font-size: 17px; font-weight: bold;">🛡️ WEAPON QUALITIES & FLAWS SELECTION</div>
            <button type="button" onclick="closeQualitiesModal()" style="background: transparent; border: none; color: #f7efe2; font-size: 20px; cursor: pointer; font-weight: bold;">✖</button>
        </div>

        <!-- Body -->
        <div style="flex: 1; overflow-y: auto; padding: 16px 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
            
            <!-- Qualities Column -->
            <fieldset style="border: 2px solid #1c521c; border-radius: 4px; padding: 12px; background: #f2fbf2;">
                <legend style="font-family: var(--font-title); font-weight: bold; font-size: 14px; color: #1c521c; padding: 0 6px;">🟢 QUALITIES (BENEFITS)</legend>
                <div id="qualities-checkbox-list" style="display: flex; flex-direction: column; gap: 8px; font-size: 12px;">
                    <!-- Checkboxes rendered dynamically -->
                </div>
            </fieldset>

            <!-- Flaws Column -->
            <fieldset style="border: 2px solid #7a1717; border-radius: 4px; padding: 12px; background: #fff4f4;">
                <legend style="font-family: var(--font-title); font-weight: bold; font-size: 14px; color: #7a1717; padding: 0 6px;">🔴 FLAWS (DRAWBACKS)</legend>
                <div id="flaws-checkbox-list" style="display: flex; flex-direction: column; gap: 8px; font-size: 12px;">
                    <!-- Checkboxes rendered dynamically -->
                </div>
            </fieldset>

        </div>

        <!-- Footer -->
        <div style="background: #e3d3bd; padding: 12px 18px; border-top: 1.5px solid #8b7961; display: flex; justify-content: space-between; align-items: center;">
            <input type="text" id="custom-quality-input" placeholder="Or type custom quality/flaw..." style="flex: 1; margin-right: 12px; padding: 6px; border: 1.5px solid #8b7961; border-radius: 3px; font-size: 12px; background: #fff;">
            <button type="button" onclick="applySelectedQualities()" style="background: #7a1717; color: #fff; border: 1px solid #4a0e0e; padding: 8px 18px; font-family: var(--font-title); font-weight: bold; cursor: pointer; border-radius: 3px;">APPLY QUALITIES</button>
        </div>

    </div>
</div>


    <!-- LONG-TERM MEMORY BANK VIEW -->
    <div id="view-memory" class="o7" style="display: none;">
        <div class="o7-crt" aria-hidden="true"></div>

        <div class="o7-shell">
            <header class="o7-topbar">
                <div class="o7-brand">
                    <svg class="cog-logo" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
                        <path d="M50 20c-16.5 0-30 13.5-30 30s13.5 30 30 30 30-13.5 30-30-13.5-30-30-30zm0 10c11 0 20 9 20 20s-9 20-20 20-20-9-20-20 9-20 20-20z"/>
                        <path d="M50 0l6 14h-12zM50 100l6-14h-12zM0 50l14-6v12zM100 50l-14-6v12zM15 15l10 10-8 8zM85 85l-10-10 8-8zM15 85l10-10-8-8zM85 15l-10 10 8 8z"/>
                    </svg>
                    <h1>
                        Long-term Memory Bank
                        <span class="o7-brand-sub">What the machine spirit keeps</span>
                    </h1>
                </div>

                <nav class="o7-nav" aria-label="Terminal sections">
                    <a href="/" onclick="event.preventDefault(); navigateToView('/');" title="Cogitator terminal">
                        <span class="o7-nav-icon" aria-hidden="true">▣</span><span class="o7-nav-text">Terminal</span><span class="o7-nav-short" aria-hidden="true">Term</span>
                    </a>
                    <a href="/memory" aria-current="page" onclick="event.preventDefault(); navigateToView('/memory');" title="Long-term memory bank">
                        <span class="o7-nav-icon" aria-hidden="true">🧠</span><span class="o7-nav-text">Memory</span><span class="o7-nav-short" aria-hidden="true">Mem</span>
                    </a>
                    <a href="/campaign" title="Roleplaying campaign">
                        <span class="o7-nav-icon" aria-hidden="true">🎲</span><span class="o7-nav-text">Campaign</span><span class="o7-nav-short" aria-hidden="true">Camp</span>
                    </a>
                    <button type="button" id="skin-btn-mem" onclick="o7ToggleSkin()" title="Toggle the CRT scanline overlay">
                        <span class="o7-nav-icon" aria-hidden="true">◐</span><span class="o7-nav-text">CRT</span><span class="o7-nav-short" aria-hidden="true">CRT</span>
                    </button>
                </nav>
            </header>

            <section class="o7-card" aria-label="Commit a new memory">
                <div class="o7-card-head">
                    <h2>Commit New Explicit Memory</h2>
                </div>
                <div class="o7-aux-row">
                    <label class="o7-sr" for="new-memory-input">New memory</label>
                    <input type="text" id="new-memory-input" style="flex: 1 1 260px;" placeholder="e.g. Master Sean prefers black coffee..." onkeydown="if(event.key==='Enter') addMemoryFact()">
                    <button type="button" class="o7-btn o7-btn-primary" onclick="addMemoryFact()">Commit fact</button>
                </div>
                <p class="o7-label" style="color:var(--ink-3)">Explicit facts are remembered verbatim. Auto-extracted facts are what the skull inferred on its own.</p>
            </section>

            <div class="o7-mem-grid">
                <section class="o7-card" aria-label="Explicit long-term memories">
                    <div class="o7-card-head">
                        <h2>🧠 Explicit Long-term</h2>
                        <span id="longterm-count" class="o7-count">[ 0 ]</span>
                    </div>
                    <div id="longterm-memory-list" class="o7-mem-list"></div>
                </section>

                <section class="o7-card" aria-label="Auto-extracted world facts">
                    <div class="o7-card-head">
                        <h2>🔍 Auto-extracted Facts</h2>
                        <span id="shortterm-count" class="o7-count">[ 0 ]</span>
                    </div>
                    <div id="shortterm-memory-list" class="o7-mem-list"></div>
                </section>
            </div>
        </div>
    </div>


<datalist id="trappings-list"></datalist>
<datalist id="weapons-list"></datalist>
<datalist id="armour-list"></datalist>
<script src="/api/app.js?v=2"></script>
</body>
</html>
"""

