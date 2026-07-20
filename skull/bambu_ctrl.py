"""
Bambu Lab 3D Printer print monitoring and notifications.
Connects via local MQTT over SSL/TLS port 8883.
"""
from __future__ import annotations
import json
import ssl
import threading
import time
import paho.mqtt.client as mqtt

from skull import config

# Thread-safe telemetry store
_status_lock = threading.Lock()
_current_status: dict | None = None
_monitor_instance: BambuMonitor | None = None


class BambuMonitor:
    def __init__(self, on_status_change_cb=None):
        self.ip = config.BAMBU_PRINTER_IP
        self.serial = config.BAMBU_PRINTER_SERIAL
        self.access_code = config.BAMBU_PRINTER_ACCESS_CODE
        self.on_status_change_cb = on_status_change_cb

        self.client = None
        self.last_state = "IDLE"
        self.last_percent = 0
        self.last_hms: list[str] = []
        self.connected = False
        self.thread = None
        self.running = False
        self.last_start_time = 0.0
        self.last_completion_time = 0.0
        self.repeater_thread = None
        self.repeater_cancel = None

    def is_configured(self) -> bool:
        return bool(self.ip and self.serial and self.access_code)

    def start(self):
        if not self.is_configured():
            print("[bambu] Monitor not started: BAMBU_PRINTER_IP, SERIAL, or ACCESS_CODE missing.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[bambu] Background monitor thread launched.")

    def stop(self):
        self.running = False
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        print("[bambu] Background monitor stopped.")

    def _run_loop(self):
        global _current_status
        while self.running:
            if not self.connected:
                if self.client:
                    try:
                        self.client.loop_stop()
                        self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None

                try:
                    # paho-mqtt v2.0+ compatibility
                    try:
                        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
                    except AttributeError:
                        self.client = mqtt.Client()

                    self.client.username_pw_set("bblp", self.access_code)

                    # Set self-signed TLS context (disable verify/check)
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    self.client.tls_set_context(ssl_context)

                    self.client.on_connect = self.on_connect
                    self.client.on_disconnect = self.on_disconnect
                    self.client.on_message = self.on_message

                    print(f"[bambu] Connecting to printer at {self.ip}:8883...")
                    self.client.connect(self.ip, 8883, keepalive=60)
                    self.client.loop_start()

                    # Wait up to 10 seconds for connection to succeed
                    for _ in range(10):
                        if self.connected or not self.running:
                            break
                        time.sleep(1)

                    if not self.connected:
                        print("[bambu] Connection timed out. Retrying in 30 seconds...")
                        time.sleep(30)
                        continue

                    # Keep checking connection health
                    while self.running and self.connected:
                        time.sleep(1)

                except Exception as e:
                    print(f"[bambu] Connection failed: {e}. Retrying in 30 seconds...")
                    with _status_lock:
                        _current_status = None
                    time.sleep(30)
            else:
                time.sleep(1)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        # Support both paho-mqtt v1.x (int) and v2.x (ReasonCode)
        is_success = False
        if hasattr(rc, "is_failure"):
            is_success = not rc.is_failure
        else:
            is_success = (rc == 0)

        if is_success:
            print("[bambu] Connected to printer MQTT broker successfully.")
            self.connected = True
            topic = f"device/{self.serial}/report"
            client.subscribe(topic)
            print(f"[bambu] Subscribed to {topic}")
            self.request_status()
        else:
            print(f"[bambu] Connection failed with code {rc}")
            self.connected = False

    def on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        print(f"[bambu] Disconnected from printer (rc: {rc})")
        self.connected = False
        with _status_lock:
            global _current_status
            _current_status = None

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "print" in payload:
                self.parse_print_status(payload["print"])
        except Exception as e:
            print(f"[bambu] Error processing message: {e}")

    def request_status(self):
        if self.client and self.connected:
            try:
                # Request full report push
                payload = {"pushing": {"pushall": {}}}
                topic = f"device/{self.serial}/request"
                self.client.publish(topic, json.dumps(payload))
                print(f"[bambu] Requested status push on {topic}")
            except Exception as e:
                print(f"[bambu] Error requesting status: {e}")

    def parse_print_status(self, print_data: dict):
        global _current_status

        # Retrieve keys
        gcode_state = print_data.get("gcode_state", "").upper()
        mc_percent = print_data.get("mc_percent", 0)
        mc_remaining_time = print_data.get("mc_remaining_time", 0)
        hms_list = print_data.get("hms", [])

        # Update global status dict (thread-safe)
        with _status_lock:
            # Keep previous values if not present in partial updates
            prev = _current_status or {}
            _current_status = {
                "gcode_state": gcode_state or prev.get("gcode_state", "UNKNOWN"),
                "percent": mc_percent if "mc_percent" in print_data else prev.get("percent", 0),
                "remaining_minutes": mc_remaining_time if "mc_remaining_time" in print_data else prev.get("remaining_minutes", 0),
                "nozzle_temp": print_data.get("nozzle_temper", prev.get("nozzle_temp", 0.0)),
                "bed_temp": print_data.get("bed_temper", prev.get("bed_temp", 0.0)),
                "subtask_name": print_data.get("subtask_name", prev.get("subtask_name", "unknown")),
                "gcode_file": print_data.get("gcode_file", prev.get("gcode_file", "")),
                "hms": [item.get("detail", "") for item in hms_list if "detail" in item] if "hms" in print_data else prev.get("hms", [])
            }

        if not gcode_state:
            return

        # ── Detect print start ───────────────────────────────────────────────────
        if gcode_state in ("RUNNING", "PREPARE") and self.last_state not in ("RUNNING", "PREPARE", "PAUSE"):
            now = time.time()
            if now - self.last_start_time > 120.0:
                print(f"[bambu] Print started: {gcode_state} (notification suppressed by request)")
                self.last_start_time = now
                self.cancel_repeater()

        # ── Detect print completion ──────────────────────────────────────────────
        elif gcode_state in ("FINISH", "SUCCESS") or (gcode_state == "IDLE" and self.last_state in ("RUNNING", "FINISH") and self.last_percent >= 98):
            now = time.time()
            if now - self.last_completion_time > 120.0:
                print("[bambu] Print finished!")
                self.notify_completion()
                self.last_completion_time = now

        # ── Detect HMS errors ────────────────────────────────────────────────────
        new_errors = []
        for item in hms_list:
            code_str = item.get("detail", "")
            if code_str and code_str not in self.last_hms:
                # Format: XXXX-XXXX-XXXX-XXXX. 3rd segment (idx 2) is severity: 0001=Error, 0002=Warning
                segments = code_str.split("-")
                severity = "unknown"
                if len(segments) >= 3:
                    level = segments[2]
                    if level == "0001":
                        severity = "error"
                    elif level == "0002":
                        severity = "warning"
                    elif level == "0003":
                        severity = "notification"

                if severity in ("error", "warning"):
                    new_errors.append((code_str, severity))

        if new_errors:
            for code_str, severity in new_errors:
                print(f"[bambu] Alert detected: {code_str} ({severity})")
                self.notify_error(code_str, severity)
            self.last_hms = [item.get("detail", "") for item in hms_list if "detail" in item]
        elif not hms_list:
            if self.last_hms:
                print("[bambu] Errors cleared. Canceling repeating notifications.")
                self.cancel_repeater()
            self.last_hms = []

        self.last_state = gcode_state
        self.last_percent = mc_percent

    def cancel_repeater(self):
        if self.repeater_cancel:
            self.repeater_cancel.set()
        if self.repeater_thread:
            self.repeater_thread.join(timeout=0.1)
        self.repeater_thread = None
        self.repeater_cancel = None

    def start_repeating_notification(self, event_type: str, text: str):
        self.cancel_repeater()
        self.repeater_cancel = threading.Event()
        self.repeater_thread = threading.Thread(
            target=self._run_repeater,
            args=(event_type, text, self.repeater_cancel),
            daemon=True
        )
        self.repeater_thread.start()

    def _run_repeater(self, event_type: str, text: str, cancel_event: threading.Event):
        for i in range(3):
            if cancel_event.is_set():
                break
            print(f"[bambu] Triggering repeating notification {i+1}/3 ({event_type}): {text}")
            if self.on_status_change_cb:
                try:
                    self.on_status_change_cb(event_type, text)
                except Exception as e:
                    print(f"[bambu] Repeating notification callback error: {e}")
            if i == 2:
                break
            for _ in range(300):
                if cancel_event.is_set():
                    break
                time.sleep(1.0)

    def notify_start(self):
        if self.on_status_change_cb:
            self.on_status_change_cb("start", "The machine spirit has initiated a new 3D printing fabrication task.")

    def notify_completion(self):
        text = "Praise the Omnissiah! The 3D printing task is complete. Your physical artifact is ready for extraction."
        self.start_repeating_notification("finish", text)

    def notify_error(self, code_str: str, severity: str):
        msg = f"Alert: The Bambu printer reports a {severity} status code {code_str}. Fabrication is halted."
        self.start_repeating_notification("error", msg)


def init(on_status_change_cb=None) -> BambuMonitor:
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = BambuMonitor(on_status_change_cb)
    return _monitor_instance


def get_monitor() -> BambuMonitor | None:
    return _monitor_instance


def get_status_report() -> dict | None:
    with _status_lock:
        return _current_status
