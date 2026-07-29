from __future__ import annotations
import subprocess
import json
import re
import time
import threading

_wifi_lock = threading.Lock()


def get_status() -> dict:
    """Return current Wi-Fi interface status, SSID, IP address, and AP mode state."""
    res = {
        "connected": False,
        "ssid": None,
        "ip": None,
        "is_ap": False,
        "interface": "wlan0"
    }
    try:
        # Query device status via nmcli
        p = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"],
            capture_output=True, text=True, timeout=5
        )
        if p.returncode == 0:
            for line in p.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 4 and parts[0] == "wlan0":
                    state = parts[2]
                    conn = parts[3]
                    if state == "connected":
                        res["connected"] = True
                        res["ssid"] = conn
                        if conn == "Omega-7-Setup":
                            res["is_ap"] = True
                    break

        # Query IP address for wlan0
        p_ip = subprocess.run(
            ["ip", "-4", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=5
        )
        if p_ip.returncode == 0:
            m = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', p_ip.stdout)
            if m:
                res["ip"] = m.group(1)

    except Exception as e:
        print(f"[wifi] Error fetching status: {e}")

    return res


def has_ap_client() -> bool:
    """Check if any client device is currently associated or active on wlan0 AP."""
    try:
        p = subprocess.run(["ip", "neighbor", "show", "dev", "wlan0"], capture_output=True, text=True, timeout=3)
        if p.returncode == 0:
            for line in p.stdout.splitlines():
                if "REACHABLE" in line or "DELAY" in line:
                    return True
    except Exception as e:
        print(f"[wifi] Error checking AP client association: {e}")
    return False



def scan_networks() -> list[dict]:
    """Scan for available Wi-Fi access points and return sorted list by signal strength."""
    networks: list[dict] = []
    seen_ssids = set()
    try:
        with _wifi_lock:
            # Rescan nearby Wi-Fi networks
            subprocess.run(["nmcli", "device", "wifi", "rescan"], capture_output=True, timeout=10)
            time.sleep(1.0)
            p = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                capture_output=True, text=True, timeout=10
            )

        if p.returncode == 0:
            for line in p.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 3:
                    ssid = parts[0].strip()
                    signal_str = parts[1].strip()
                    security = parts[2].strip()

                    # Skip empty SSIDs (hidden networks) and current setup AP
                    if not ssid or ssid == "Omega-7-Setup" or ssid in seen_ssids:
                        continue
                    
                    try:
                        signal = int(signal_str)
                    except ValueError:
                        signal = 0

                    seen_ssids.add(ssid)
                    networks.append({
                        "ssid": ssid,
                        "signal": signal,
                        "security": security if security else "Open"
                    })

        # Sort by signal strength descending
        networks.sort(key=lambda x: x["signal"], reverse=True)
    except Exception as e:
        print(f"[wifi] Scan error: {e}")

    return networks


def connect_network(ssid: str, password: str | None = None) -> tuple[bool, str]:
    """Attempt to connect wlan0 to the specified Wi-Fi network using NetworkManager."""
    if not ssid or not ssid.strip():
        return False, "SSID cannot be empty."

    ssid = ssid.strip()
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password and password.strip():
        cmd.extend(["password", password.strip()])

    try:
        with _wifi_lock:
            print(f"[wifi] Connecting to '{ssid}'...")
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if p.returncode == 0:
            print(f"[wifi] Successfully connected to '{ssid}'")
            return True, f"Successfully connected to '{ssid}'."
        else:
            err = p.stderr.strip() or p.stdout.strip() or "Connection failed."
            print(f"[wifi] Connection error for '{ssid}': {err}")
            return False, f"Failed to connect to '{ssid}': {err}"
    except subprocess.TimeoutExpired:
        return False, f"Connection to '{ssid}' timed out."
    except Exception as e:
        return False, f"Connection error: {e}"


def start_hotspot(ssid: str = "Omega-7-Setup", password: str = "servoskull") -> tuple[bool, str]:
    """Start an Access Point hotspot on wlan0 for out-of-box provisioning."""
    cmd = ["nmcli", "device", "wifi", "hotspot", "ifname", "wlan0", "ssid", ssid]
    if password and len(password) >= 8:
        cmd.extend(["password", password])

    try:
        with _wifi_lock:
            print(f"[wifi] Starting hotspot AP '{ssid}'...")
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)

        if p.returncode == 0:
            print(f"[wifi] Hotspot AP '{ssid}' active.")
            return True, f"Hotspot '{ssid}' started successfully."
        else:
            err = p.stderr.strip() or p.stdout.strip() or "Hotspot creation failed."
            return False, f"Failed to start hotspot: {err}"
    except Exception as e:
        return False, f"Hotspot error: {e}"


def stop_hotspot() -> tuple[bool, str]:
    """Disconnect the setup hotspot if active."""
    try:
        with _wifi_lock:
            p = subprocess.run(["nmcli", "connection", "down", "Hotspot"], capture_output=True, text=True, timeout=10)
        return True, "Hotspot stopped."
    except Exception as e:
        return False, f"Error stopping hotspot: {e}"
