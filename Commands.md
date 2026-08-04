# 💀 Omega-7 / Servo Skull — Standard Voice & Remote Command Reference

This document provides a comprehensive sitemap and reference of all standard voice commands, system controls, and web remote capabilities supported by the **Omega-7 AI Servo Skull** (Adeptus Mechanicus Cogitator Appliance).

---

## ⚡ Wake Words & Activation
You can activate the Servo Skull by speaking any of the supported wake words:
- **`"Servitor"`** *(Default wake word)*
- **`"Hey Jarvis"`**
- **`"Omega 7"`** / **`"Omega 8"`**

> 💡 *Note: You can also trigger a wake sequence directly from the Cogitator Web Terminal (`https://<skull-name>.local:8080`) by clicking the **`🎙 VEX VOX`** button.*

---

## 🔊 System & Volume Controls

| Command Category | Example Spoken Commands | Action |
| :--- | :--- | :--- |
| **Volume Level** | *"Set volume to 50%"* / *"Set volume to 80"* | Sets hardware output volume to an absolute percentage across PipeWire/PulseAudio/ALSA. |
| **Relative Volume** | *"Volume up"* / *"Volume down"* / *"Louder"* / *"Quieter"* | Increases or decreases output volume by 15%. |
| **Quiet Mode** | *"Enable quiet mode"* / *"Disable quiet mode"* | Suppresses non-essential spoken notifications and canned responses. |
| **Sleep Schedule** | *"Set sleep schedule from 22:00 to 07:00"* | Sets automatic quiet/dormancy hours. |
| **Mic Sensitivity** | *"Increase microphone sensitivity"* / *"Make mic less sensitive"* | Adjusts noise rejection & input threshold. |
| **Wake Sensitivity** | *"Set wake word threshold to 0.70"* / *"Make wake word more sensitive"* | Tunes openWakeWord detection threshold (0.40 - 0.85). |

---

## ⚙️ Voice & Personality Management

| Spoken Command | Function |
| :--- | :--- |
| **`"Rebuild your sounds"`** / **`"Rebuild speech phrases"`** | Clears the voice phrase cache (`models/phrase_cache/`) and re-synthesizes all boot, wake, and cogitation phrases using the active ElevenLabs voice ID (`ELEVENLABS_VOICE_ID`). |
| **`"Switch personality to Imperial Servo Skull"`** | Activates the default Adeptus Mechanicus Tech-Priest persona. |
| **`"Switch personality to Golden Retriever"`** | Switches to an upbeat, enthusiastic companion persona. |
| **`"Switch personality to Custom Archetype"`** | Switches to user-defined archetype in `owner.json`. |

---

## 🎲 Warhammer 40k, Necromunda & Wargaming Rules

The Servo Skull includes built-in rules reference engines and random dice generators for tabletop gaming:

### Rules Lookups
- **Warhammer 40k:** *"Look up Space Marine Armor Saves in 40k"* / *"Explain Oath of Moment"*
- **Necromunda:** *"What are the Gang Tactics for House Escher in Necromunda?"* / *"Look up Plasma Gun weapon stats in Necromunda"*
- **NetEpic / Epic 40k:** *"Look up Warlord Titan weapon stats in NetEpic"*
- **NetEA:** *"Explain assault phase rules in NetEA"*
- **Lore & Mechanicus:** *"Recite the Litany of Ignition"* / *"Who is Belisarius Cawl?"*

### Dice Generators & Auspex Scan
- **Dice Rolls:** *"Roll 3d6"* / *"Roll 2d20+5"* / *"Roll 5 D6"*
- **Tabletop Combat Rolls:** *"Roll 5 40k armor saves with 3+ threshold and AP -2"*
- **Necromunda Dice:** *"Roll a Necromunda ammo die"* / *"Roll a injury die"*
- **Auspex Tactical Scan:** *"Run an Auspex scan"* *(Triggers sensor sweep SFX and visual telemetry)*

---

## 🎵 Music & Audio (Spotify Connect & Ambient Hymns)

| Spoken Command | Action |
| :--- | :--- |
| **`"Play [Song / Artist / Album] on Spotify"`** | Searches and streams music via Spotify Connect (Raspotify). |
| **`"Pause music"`** / **`"Resume music"`** | Controls active playback. |
| **`"Next track"`** / **`"Previous track"`** | Skips songs in playback queue. |
| **`"What song is playing?"`** | Reports active track, artist, and album details. |
| **`"Set Spotify volume to 75%"`** | Adjusts Spotify Connect daemon volume level. |
| **`"Play Mechanicus ambient hymns"`** | Streams grimdark background ambient soundscapes. |

---

## 👁️ Ocular & Camera Sensor Commands

| Spoken Command | Action |
| :--- | :--- |
| **`"What do you see?"`** / **`"Describe surroundings"`** | Captures a high-resolution camera frame and uses Claude Vision to describe the scene. |
| **`"Register face as [Name]"`** | Captures face embedding and saves identity to local face registry (`camera.py`). |
| **`"Who do you see?"`** | Runs real-time face detection against registered identities. |
| **`"Register voice as [Name]"`** | Samples current speaker audio and registers speaker voice profile (`speaker_id.py`). |
| **`"Purge identity [Name]"`** | Deletes registered face/voice profiles from storage. |

---

## 🖥️ Face Display & Visual Telemetry (GC9A01 Round Panel)

| Command / Option | Action |
| :--- | :--- |
| **`"Play cogitator animation [aquila / noosphere / matrix / eye]"`** | Plays specific screensaver animation on the round face display for 60 seconds. |
| **`"Rotate display 180 degrees"`** | Rotates panel orientation (`0`, `90`, `180`, `270`). |
| **`"Show display alignment grid"`** | Displays alignment crosshairs for physical bezel adjustment. |
| **`"Display artwork of [subject]"`** | Generates or fetches visual art to show on the round panel. |

---

## ⛅ Information, Weather, News & Proximity

| Spoken Command | Function |
| :--- | :--- |
| **`"What is the weather today?"`** | Fetches live weather forecast using Open-Meteo API. |
| **`"Set weather location to Seattle, WA"`** | Updates city / latitude / longitude in config. |
| **`"Search the web for [topic]"`** | Searches web using DuckDuckGo search engine. |
| **`"What's in the news today?"`** | Summarizes current global / tech headlines. |
| **`"Give me the daily briefing"`** | Provides weather, news, reminders, and daily Mechanicus litany. |
| **`"How far is the wall?"`** / **`"Get proximity reading"`** | Queries the VL53L1X laser rangefinder (0 - 8 meters). |

---

## 📝 Reminders, Timers & Memory Storage

| Spoken Command | Action |
| :--- | :--- |
| **`"Remind me to [task] in [X] minutes"`** | Schedules a background timer with audio notification. |
| **`"List reminders"`** | Reads out active pending reminders. |
| **`"Cancel reminder [ID]"`** | Removes a scheduled reminder. |
| **`"Remember that [fact]"`** | Stores long-term memory fact in `memory.json`. |
| **`"What do you remember?"`** | Lists stored facts and owner profile information. |
| **`"Forget [fact]"`** | Removes entry from long-term memory. |

---

## 🕯️ Hardware Peripherals (Candles & 3D Printer)

| Spoken Command | Function |
| :--- | :--- |
| **`"Turn on candles"`** / **`"Turn off candles"`** | Controls GPIO transistor flicker candles (`CANDLE_PIN`). |
| **`"Check 3D printer status"`** | Queries Bambu Lab 3D printer status (print % / temp / ETA). |
| **`"Connect to Bambu printer at [IP]"`** | Configures Bambu MQTT connection. |
| **`"Cancel printer alerts"`** | Mutes recurring print completion notifications. |

---

## 🛠️ System Maintenance Commands

| Spoken Command | Action |
| :--- | :--- |
| **`"Self update"`** | Pulls latest code from GitHub, installs Python dependencies, and restarts `omega7.service` / `omega8.service`. |
| **`"Reboot system"`** | Executes `sudo reboot` on the Raspberry Pi. |
| **`"Shutdown system"`** | Executes `sudo poweroff` on the Raspberry Pi. |

---

## 🌐 Useful SSH Terminal Commands

For administrators managing the skull via SSH (`ssh pat@omega8.local`):

```bash
# Check service status
sudo systemctl status omega8

# View live system logs
journalctl -u omega8 -f

# Restart service cleanly
sudo systemctl restart omega8

# Force rebuild voice phrase cache
python3 -c "import shutil, os; shutil.rmtree(os.path.expanduser('~/skull/models/phrase_cache'))"
