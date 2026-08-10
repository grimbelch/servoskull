
        window.addEventListener('error', function(e) {
            const errDiv = document.createElement('div');
            errDiv.style.cssText = 'position:fixed; top:0; left:0; width:100%; background:red; color:white; z-index:9999; padding:20px; font-size:24px; font-weight:bold; word-wrap:break-word;';
            errDiv.innerText = 'JS FATAL ERROR: ' + e.message + ' at line ' + e.lineno;
            document.body.appendChild(errDiv);
        });
        window.addEventListener('unhandledrejection', function(e) {
            const errDiv = document.createElement('div');
            errDiv.style.cssText = 'position:fixed; top:80px; left:0; width:100%; background:darkred; color:white; z-index:9999; padding:20px; font-size:24px; font-weight:bold; word-wrap:break-word;';
            errDiv.innerText = 'PROMISE ERROR: ' + (e.reason ? e.reason.message : e.reason);
            document.body.appendChild(errDiv);
        });

        const alertTitle = document.getElementById('alert-title');
        const alertValue = document.getElementById('alert-value');
        const alertBanner = document.getElementById('alert-banner');
        if (alertTitle) alertTitle.innerText = "V3 DIAGNOSTICS ACTIVE";
        
        const tempVal = document.getElementById('temp-val');
        const cpuVal = document.getElementById('cpu-val');
        const ramVal = document.getElementById('ram-val');
        const storageVal = document.getElementById('storage-val');
        const fabricatorVal = document.getElementById('fabricator-val');
        const masterVal = document.getElementById('master-val');
        const silentVal = document.getElementById('silent-val');
        const moodVal = document.getElementById('mood-val');
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

        const _savedWebAudio = (function() {
            try { return localStorage.getItem('servoskull_web_audio_enabled'); } catch(e) { return null; }
        })();
        let webAudioEnabled = _savedWebAudio !== null ? (_savedWebAudio === 'true') : true;
        let lastAudioId = 0;
        let currentAudioObj = null;

        function updateWebAudioUI() {
            const btn = document.getElementById('web-audio-btn');
            if (!btn) return;
            if (webAudioEnabled) {
                btn.innerText = '🔊 WEB AUDIO: ENABLED';
                btn.style.color = 'var(--bright-green)';
            } else {
                btn.innerText = '🔇 WEB AUDIO: DISABLED';
                btn.style.color = 'var(--dim-green)';
                if (currentAudioObj) {
                    currentAudioObj.pause();
                }
            }
        }

        function toggleWebAudio() {
            webAudioEnabled = !webAudioEnabled;
            try {
                localStorage.setItem('servoskull_web_audio_enabled', webAudioEnabled ? 'true' : 'false');
            } catch(e) {}
            updateWebAudioUI();
            if (webAudioEnabled) {
                const silentAudio = new Audio();
                silentAudio.play().catch(() => {});
            }
        }

        // Initialize Web Audio button UI state on load
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', updateWebAudioUI);
        } else {
            updateWebAudioUI();
        }

        document.addEventListener('click', function unlockAudio() {
            const dummy = new Audio();
            dummy.play().catch(() => {});
        }, { once: true });

        // Fetch State loop
        async function fetchState() {

            try {
                const res = await fetch('/api/state?t=' + Date.now());
                if (!res.ok) {
                    console.error("fetchState HTTP error:", res.status);
                    return;
                }
                const data = await res.json();
                if (!data) return;
                
                // Stream Web Vox Audio if new speech generated
                if (data.audio_id && data.audio_id > lastAudioId) {
                    if (lastAudioId === 0) {
                        lastAudioId = data.audio_id;
                    } else {
                        lastAudioId = data.audio_id;
                        if (webAudioEnabled) {
                            if (currentAudioObj) {
                                currentAudioObj.pause();
                            }
                            currentAudioObj = new Audio('/api/last_speech.wav?id=' + data.audio_id);
                            currentAudioObj.play().catch(e => console.log('Web audio playback:', e));
                        }
                    }
                }
                
                // Dynamic DOM element queries
                const elMaster = document.getElementById('master-val');
                if (elMaster && data.master) elMaster.innerText = String(data.master).toUpperCase();

                const elSilent = document.getElementById('silent-val');
                if (elSilent && data.silent_mode) elSilent.innerText = String(data.silent_mode).toUpperCase();

                const elMood = document.getElementById('mood-val');
                if (elMood && data.mood) elMood.innerText = String(data.mood).toUpperCase();

                const elGame = document.getElementById('game-val');
                if (elGame) {
                    const gameName = data.active_game ? String(data.active_game).toUpperCase() : 'WFRP 4E CAMPAIGN';
                    if (gameName !== 'NONE' && gameName !== 'INACTIVE') {
                        elGame.innerHTML = `<a href="/campaign" style="color: var(--bright-green); font-weight: bold; text-decoration: underline; cursor: pointer;" title="Open Roleplaying Campaign Page">${gameName} 🎲</a>`;
                    } else {
                        elGame.innerHTML = `<a href="/campaign" style="color: var(--bright-green); font-weight: bold; text-decoration: underline; cursor: pointer;" title="Open Roleplaying Campaign Page">OPEN CAMPAIGN 🎲</a>`;
                    }
                }

                // Update Wi-Fi Status text
                const wifiText = document.getElementById('wifi-status-text');
                if (wifiText && data.wifi) {
                    if (data.wifi.is_ap) {
                        wifiText.innerText = `[ AP HOTSPOT: ${data.wifi.ssid || 'Omega-7-Setup'} ]`;
                        wifiText.style.color = '#ff9900';
                    } else if (data.wifi.connected) {
                        wifiText.innerText = `[ ${data.wifi.ssid} (${data.wifi.ip || 'Connected'}) ]`;
                        wifiText.style.color = 'var(--bright-green)';
                    } else {
                        wifiText.innerText = '[ DISCONNECTED ]';
                        wifiText.style.color = '#ff3838';
                    }
                }

                // Auto-trigger Onboarding Wizard if unconfigured or AP mode
                if (data.is_configured === false || (data.wifi && data.wifi.is_ap)) {
                    const wiz = document.getElementById('wizard-modal');
                    if (wiz && wiz.style.display === 'none' && !window.wizardClosedManually) {
                        wiz.style.display = 'block';
                    }
                }

                // Update CPU pie
                const cpuFloat = parseFloat(data.cpu) || 0;
                const cpuPie = document.getElementById('cpu-pie');
                const cpuValEl = document.getElementById('cpu-val');
                if (cpuValEl && data.cpu) cpuValEl.innerText = String(data.cpu);
                if (cpuPie) cpuPie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, cpuFloat))}, 100`);

                // Update CORE TEMP pie
                const tempFloat = parseFloat(data.temperature) || 0;
                const tempPie = document.getElementById('temp-pie');
                const tempValEl = document.getElementById('temp-val');
                if (tempValEl && data.temperature) tempValEl.innerText = String(data.temperature);
                if (tempPie) tempPie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, tempFloat))}, 100`);

                // Update RAM pie & label
                const ramFloat = parseFloat(data.ram) || 0;
                const ramPie = document.getElementById('ram-pie');
                const ramValEl = document.getElementById('ram-val');
                const ramLabelEl = document.getElementById('ram-label');
                if (ramValEl && data.ram) ramValEl.innerText = String(data.ram);
                if (ramLabelEl && data.ram_total) ramLabelEl.innerText = `RAM: ${data.ram_total}`;
                if (ramPie) ramPie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, ramFloat))}, 100`);

                // Update STORAGE pie & label
                const storageFloat = parseFloat(data.storage) || 0;
                const storagePie = document.getElementById('storage-pie');
                const storageValEl = document.getElementById('storage-val');
                const storageLabelEl = document.getElementById('storage-label');
                if (storageValEl && data.storage) storageValEl.innerText = String(data.storage);
                if (storageLabelEl && data.storage_total) storageLabelEl.innerText = `STORAGE: ${data.storage_total}`;
                if (storagePie) storagePie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, storageFloat))}, 100`);

                // Update FABRICATOR pie
                let fabPercent = 0;
                if (data.fabricator && typeof data.fabricator.percent === 'number') {
                    fabPercent = data.fabricator.percent;
                }
                const fabPie = document.getElementById('fabricator-pie');
                const fabValEl = document.getElementById('fabricator-val');
                if (fabValEl) {
                    if (fabPercent > 0) {
                        fabValEl.innerText = fabPercent.toFixed(0) + '%';
                    } else if (data.fabricator && data.fabricator.text) {
                        let txt = data.fabricator.text.replace(/^(RUNNING|PREPARE)\\s*/i, '').trim();

                        fabValEl.innerText = txt.toUpperCase() || '0%';
                    } else {
                        fabValEl.innerText = '0%';
                    }
                }
                if (fabPie) fabPie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, fabPercent))}, 100`);

                // Update Rangefinder Gauge & Bar Graph (8m limit)
                const rangeVal = document.getElementById('range-val');
                const rangeBar = document.getElementById('range-bar');
                if (data.proximity) {
                    if (!data.proximity.enabled) {
                        if (rangeVal) rangeVal.innerText = "DISABLED";
                        if (rangeBar) rangeBar.style.width = "0%";
                    } else if (!data.proximity.available) {
                        if (rangeVal) rangeVal.innerText = "UNAVAILABLE";
                        if (rangeBar) rangeBar.style.width = "0%";
                    } else if (data.proximity.distance_cm !== null && data.proximity.distance_cm !== undefined) {
                        const cm = parseFloat(data.proximity.distance_cm);
                        const meters = (cm / 100.0).toFixed(2);
                        if (rangeVal) rangeVal.innerText = `${cm.toFixed(1)} cm (${meters} m)`;
                        const pct = Math.min(100, Math.max(0, (cm / 800.0) * 100.0));
                        if (rangeBar) rangeBar.style.width = `${pct.toFixed(1)}%`;
                    } else {
                        if (rangeVal) rangeVal.innerText = "OUT OF RANGE (> 8.0 m)";
                        if (rangeBar) rangeBar.style.width = "0%";
                    }
                }
                
                // Update screensaver options if not already filled
                const scSelect = document.getElementById('screensaver-select');
                if (scSelect && data.screensavers && data.screensavers.length > 0) {
                    const currentStr = Array.from(scSelect.options).map(o => o.value).filter(v => v !== "").join(",");
                    const newStr = data.screensavers.join(",");
                    if (currentStr !== newStr) {
                        const selectedValue = scSelect.value;
                        scSelect.innerHTML = '<option value="">-- SELECT SCREENSAVER --</option>';
                        data.screensavers.forEach(s => {
                            const opt = document.createElement('option');
                            opt.value = s;
                            opt.innerText = String(s).replace(/_/g, ' ').toUpperCase();
                            scSelect.appendChild(opt);
                        });
                        scSelect.value = data.screensavers.includes(selectedValue) ? selectedValue : "";
                    }
                }

                // Update Logs Console (Telemetry Console Feed)
                const elConsoleBox = document.getElementById('console-box');
                if (elConsoleBox && data.logs) {
                    elConsoleBox.innerHTML = '';
                    data.logs.forEach(line => {
                        const div = document.createElement('div');
                        div.className = 'console-line';
                        div.innerText = line;
                        elConsoleBox.appendChild(div);
                    });
                    elConsoleBox.scrollTop = elConsoleBox.scrollHeight;
                }

                // Update Vox Channel Logs
                const elChatContainer = document.getElementById('chat-container');
                if (elChatContainer && data.vox_logs && data.vox_logs.length > 0) {
                    const voxHash = JSON.stringify(data.vox_logs);
                    if (window._lastVoxHash !== voxHash) {
                        window._lastVoxHash = voxHash;
                        elChatContainer.innerHTML = '';
                        data.vox_logs.forEach(msg => {
                            const bubble = document.createElement('div');
                            const isSkull = (msg.speaker === data.skull_name || msg.speaker === 'Omega-7' || msg.speaker === 'Servo-Skull');
                            bubble.className = `chat-bubble ${isSkull ? 'chat-skull' : 'chat-user'}`;
                            const timeTag = msg.time ? `[${msg.time}] ` : '';
                            bubble.innerText = `${timeTag}${msg.speaker}: ${msg.text}`;
                            elChatContainer.appendChild(bubble);
                        });
                        elChatContainer.scrollTop = elChatContainer.scrollHeight;
                    }
                }

                // Update Camera Feed status
                const camActive = data.camera_active;
                const camStream = document.getElementById('camera-stream');
                const camStandby = document.getElementById('camera-standby');
                const camMode = document.getElementById('cam-bezel-bl');
                const camFps = document.getElementById('cam-bezel-tr');

                if (camStream && camStandby) {
                    if (camActive) {
                        if (!camStream.src || !camStream.src.includes('/api/camera_stream.mjpeg')) {
                            camStream.src = '/api/camera_stream.mjpeg';
                        }
                        camStream.style.display = 'block';
                        camStandby.style.display = 'none';
                        if (camMode) camMode.innerText = 'MODE: LIVE';
                        if (camFps) camFps.innerText = 'FPS: LIVE';
                    } else {
                        camStream.style.display = 'none';
                        camStream.removeAttribute('src');
                        camStandby.style.display = 'block';
                        if (camMode) camMode.innerText = 'MODE: STANDBY';
                        if (camFps) camFps.innerText = 'FPS: --';
                    }
                }

                // Check state transitions
                if (data.display) currentState = data.display;

                // Update Warning/Status Banner (Secret Level Style)
                let headerTitle = "SYSTEM STATUS";
                let headerValue = "SYSTEM OPTIMAL";
                let bannerBg = "rgba(56, 255, 88, 0.07)";
                let bannerBorder = "2px solid var(--bright-green)";

                if (currentState && currentState.thinking) {
                    headerTitle = "COGITATION PROTOCOL";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.15)";
                } else if (currentState && currentState.speaking) {
                    headerTitle = "VOCAL TRANSMISSION";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.25)";
                    bannerBorder = "3px double var(--bright-green)";
                } else if (currentState && currentState.searching_web) {
                    headerTitle = "NOOSPHERE SEARCH";
                    headerValue = "QUERYING NETWORK";
                    bannerBg = "rgba(56, 255, 88, 0.2)";
                } else if (currentState && currentState.looking_up_rules) {
                    headerTitle = "LIBRARIUM CODEX";
                    headerValue = "RULES DATABASE";
                    bannerBg = "rgba(56, 255, 88, 0.2)";
                } else if (currentState && currentState.fetching_news) {
                    headerTitle = "VOX TRANSMISSION";
                    headerValue = "SCANNING BROADCASTS";
                    bannerBg = "rgba(56, 255, 88, 0.2)";
                } else if (currentState && currentState.retrieving_image) {
                    headerTitle = "PICT-FEED RASTER";
                    headerValue = "FETCHING ARTWORK";
                    bannerBg = "rgba(56, 255, 88, 0.2)";
                } else if (currentState && (currentState.scanning_auspex || currentState.scanning_noosphere)) {
                    headerTitle = "AUSPEX SCANNING MODE";
                    headerValue = "ACTIVE";
                    bannerBg = "rgba(56, 255, 88, 0.15)";
                } else if (currentState && currentState.active_idle_anim) {
                    headerTitle = "VISUAL EMULATION";
                    headerValue = currentState.active_idle_anim.toUpperCase().replace(/_/g, ' ');
                }
                
                const elAlertTitle = document.getElementById('alert-title');
                const elAlertValue = document.getElementById('alert-value');
                const elAlertBanner = document.getElementById('alert-banner');
                if (elAlertTitle) elAlertTitle.innerText = headerTitle;
                if (elAlertValue) elAlertValue.innerText = headerValue;
                if (elAlertBanner) elAlertBanner.style.background = bannerBg;
                if (elAlertBanner) elAlertBanner.style.border = bannerBorder;

                // Adjust glows/shadows based on speech amplitude
                const amp = (currentState && currentState.amplitude) || 0;
                let brightness = 15;
                if (currentState && currentState.speaking) {
                    brightness = 30 + amp * 70;
                } else if (currentState && currentState.thinking) {
                    brightness = 40 + Math.sin(Date.now() / 150) * 20;
                }
                
                // Pulsate eye ring glow matching the speaker amplitude
                const elEyeRing = document.getElementById('eye-ring');
                if (elEyeRing) elEyeRing.style.boxShadow = `0 0 ${15 + (brightness/100)*25}px var(--glow-color)`;

                // Update ocular eye display stream
                const eyeStream = document.getElementById('eye-stream');
                if (eyeStream && (!eyeStream.src || !eyeStream.src.includes('/api/ocular_stream.mjpeg'))) {
                    eyeStream.src = '/api/ocular_stream.mjpeg';
                }


            } catch (err) {
                console.warn("State fetch failed. Backend may be offline or sleeping.", err);
            }
        }

        // Trigger immediately on load and on interval
        fetchState();
        document.addEventListener('DOMContentLoaded', fetchState);
        window.addEventListener('load', fetchState);
        setInterval(fetchState, 500);


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
            
            addChatBubble(`Executing cogitator visual emulation (${anim})...`, 'chat-user');
            
            try {
                const res = await fetch('/api/screensaver', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ animation: anim })
                });
                const data = await res.json();
                if (data.status !== 'ok') {
                    addChatBubble(`Screensaver error: ${data.message}`, 'chat-skull');
                }
            } catch (err) {
                addChatBubble(`Failed to run screensaver: ${err}`, 'chat-skull');
            }
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
        let isToggleRecording = false;

        async function toggleMicRecording() {
            const micBtn = document.getElementById('mic-btn');
            const micLabel = document.getElementById('mic-btn-label');
            if (!isToggleRecording) {
                isToggleRecording = true;
                if (micBtn) {
                    micBtn.classList.add('recording');
                    micBtn.title = "Click to stop & transmit web mic audio";
                }
                if (micLabel) micLabel.innerText = '● REC...';
                await startMicRecording();
            } else {
                isToggleRecording = false;
                if (micBtn) {
                    micBtn.classList.remove('recording');
                    micBtn.title = "Click to record web mic audio";
                }
                if (micLabel) micLabel.innerText = 'REC';
                await stopMicRecording();
            }
        }

        async function startMicRecording() {
            const micBtn = document.getElementById('mic-btn');
            if (micBtn) {
                micBtn.classList.add('recording');
                micBtn.title = "Recording audio...";
            }
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
                addChatBubble("Browser mic blocked or unavailable. Please grant microphone permissions or type your command directly.", 'chat-skull');
                stopMicRecording();
            }
        }

        async function stopMicRecording() {
            isToggleRecording = false;
            const micBtn = document.getElementById('mic-btn');
            const micLabel = document.getElementById('mic-btn-label');
            if (micBtn) {
                micBtn.classList.remove('recording');
                micBtn.title = "Click to Record Web Mic Audio";
            }
            if (micLabel) micLabel.innerText = 'REC';
            
            if (micBtn && micBtn.audioProcessor) {
                micBtn.audioProcessor.disconnect();
                micBtn.audioSource.disconnect();
            }
            if (mediaStream) {
                mediaStream.getTracks().forEach(track => track.stop());
            }

            if (audioChunks.length === 0) return;
            
            addChatBubble("[Vox input transmitted]", 'chat-user');
            const wavBlob = encodeWAV(audioChunks, 16000);
            audioChunks = [];
            
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

        async function scanWifiNetworks() {
            const wifiText = document.getElementById('wifi-status-text');
            if (wifiText) wifiText.innerText = '[ SCANNING... ]';
            try {
                const res = await fetch('/api/wifi/scan');
                const data = await res.json();
                if (!data.networks || data.networks.length === 0) {
                    alert("No Wi-Fi networks found nearby.");
                    return;
                }
                let choice = prompt(
                    "AVAILABLE WI-FI NETWORKS:\n" +
                    data.networks.map((n, i) => `${i + 1}. ${n.ssid} (Signal: ${n.signal}%, Security: ${n.security})`).join("\n") +
                    "\n\nEnter number or SSID to connect:"
                );
                if (!choice) return;
                let targetSsid = choice.trim();
                let idx = parseInt(targetSsid) - 1;
                if (!isNaN(idx) && data.networks[idx]) {
                    targetSsid = data.networks[idx].ssid;
                }
                let password = prompt(`Enter password for Wi-Fi network '${targetSsid}':`);
                if (password === null) return;
                await connectWifi(targetSsid, password);
            } catch (err) {
                alert("Wi-Fi scan failed: " + err);
            }
        }

        async function connectWifi(ssid, password) {
            const wifiText = document.getElementById('wifi-status-text');
            if (wifiText) wifiText.innerText = `[ CONNECTING TO ${ssid}... ]`;
            try {
                const res = await fetch('/api/wifi/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ssid, password })
                });
                const data = await res.json();
                alert(data.message);
            } catch (err) {
                alert("Connection failed: " + err);
            }
        }

        async function toggleHotspot() {
            if (!confirm("Start AP Hotspot 'Omega-7-Setup'?")) return;
            try {
                const res = await fetch('/api/wifi/hotspot', { method: 'POST' });
                const data = await res.json();
                alert(data.message);
            } catch (err) {
                alert("Hotspot trigger failed: " + err);
            }
        }

        // Onboarding Setup Wizard Functions
        let wizardCurrentStep = 1;

        function nextWizardStep(step) {
            wizardCurrentStep = step;
            document.querySelectorAll('.wizard-step').forEach(el => el.style.display = 'none');
            const target = document.getElementById(`w-step-${step}`);
            if (target) target.style.display = 'block';
            const label = document.getElementById('wizard-step-label');
            const stepNames = ["WI-FI PROVISIONING", "IDENTITY & ARCHETYPE", "MASTER PROFILE", "API CREDENTIALS"];
            if (label && stepNames[step - 1]) {
                label.innerText = `STEP ${step} OF 4: ${stepNames[step - 1]}`;
            }
        }

        async function scanWizardWifi() {
            const resBox = document.getElementById('w-wifi-result');
            if (resBox) {
                resBox.innerText = 'Scanning for nearby Wi-Fi access points...';
                resBox.style.color = 'var(--bright-green)';
            }
            try {
                const res = await fetch('/api/wifi/scan');
                const data = await res.json();
                if (!data.networks || data.networks.length === 0) {
                    if (resBox) {
                        resBox.innerText = 'No Wi-Fi networks found. Enter SSID manually.';
                        resBox.style.color = '#ff3838';
                    }
                    return;
                }
                let choice = prompt(
                    "AVAILABLE WI-FI NETWORKS:\n" +
                    data.networks.map((n, i) => `${i + 1}. ${n.ssid} (${n.signal}% signal)`).join("\n") +
                    "\n\nEnter number or SSID:"
                );
                if (choice) {
                    let targetSsid = choice.trim();
                    let idx = parseInt(targetSsid) - 1;
                    if (!isNaN(idx) && data.networks[idx]) {
                        targetSsid = data.networks[idx].ssid;
                    }
                    document.getElementById('w-wifi-ssid').value = targetSsid;
                    if (resBox) {
                        resBox.innerText = `Selected SSID: '${targetSsid}'. Enter password and proceed.`;
                        resBox.style.color = 'var(--bright-green)';
                    }
                }
            } catch (err) {
                if (resBox) {
                    resBox.innerText = 'Scan error: ' + err;
                    resBox.style.color = '#ff3838';
                }
            }
        }

        async function testWizardKey(provider) {
            const input = document.getElementById(`w-key-${provider}`);
            const badge = document.getElementById(`w-res-${provider}`);
            if (!input || !badge) return;
            const key = input.value.trim();
            if (!key) {
                badge.innerText = '⚠️ Please enter an API key first.';
                badge.style.color = '#ff9900';
                return;
            }
            badge.innerText = 'Testing key...';
            badge.style.color = 'var(--bright-green)';
            try {
                const res = await fetch('/api/setup/test_key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider, key })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    badge.innerText = '✅ ' + data.message;
                    badge.style.color = 'var(--bright-green)';
                } else {
                    badge.innerText = '❌ ' + data.message;
                    badge.style.color = '#ff3838';
                }
            } catch (err) {
                badge.innerText = '❌ Verification error: ' + err;
                badge.style.color = '#ff3838';
            }
        }

        async function finishWizard() {
            const anthropicKey = document.getElementById('w-key-anthropic').value.trim();
            if (!anthropicKey) {
                alert("Anthropic API key is required to power the Claude brain. Please enter and test your Anthropic API key.");
                return;
            }

            const payload = {
                skull_name: document.getElementById('w-skull-name').value.trim() || 'Omega-7',
                personality: document.getElementById('w-personality').value,
                owner: {
                    name: document.getElementById('w-master-name').value.trim() || 'Master',
                    city: document.getElementById('w-master-city').value.trim() || 'Local',
                    interests: document.getElementById('w-master-interests').value.trim() || ''
                },
                wifi: {
                    ssid: document.getElementById('w-wifi-ssid').value.trim(),
                    password: document.getElementById('w-wifi-pass').value.trim()
                },
                keys: {
                    anthropic: anthropicKey,
                    elevenlabs: document.getElementById('w-key-elevenlabs').value.trim(),
                    openai: document.getElementById('w-key-openai').value.trim()
                }
            };

            try {
                const res = await fetch('/api/setup/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    alert("Initialization Complete! Connecting to your Wi-Fi network...");
                    window.wizardClosedManually = true;
                    document.getElementById('wizard-modal').style.display = 'none';
                    setTimeout(() => window.location.reload(), 3000);
                } else {
                    alert("Save failed: " + data.message);
                }
            } catch (err) {
                alert("Setup failed: " + err);
            }
        }
    

// ── WFRP 4E CHARACTER SHEET MODAL ENGINE (Pages 344 & 345) ───────────────────
let editingCharIndex = -1;
let currentCampaign = null;

const BASIC_SKILLS_DEF = [
    { name: "Art", stat: "Dex" },
    { name: "Athletics", stat: "Ag" },
    { name: "Bribery", stat: "Fel" },
    { name: "Charm", stat: "Fel" },
    { name: "Charm Animal", stat: "WP" },
    { name: "Climb", stat: "S" },
    { name: "Cool", stat: "WP" },
    { name: "Consume Alcohol", stat: "T" },
    { name: "Dodge", stat: "Ag" },
    { name: "Drive", stat: "Ag" },
    { name: "Endurance", stat: "T" },
    { name: "Entertain", stat: "Fel" },
    { name: "Gamble", stat: "Int" },
    { name: "Gossip", stat: "Fel" },
    { name: "Haggle", stat: "Fel" },
    { name: "Intimidate", stat: "S" },
    { name: "Intuition", stat: "I" },
    { name: "Leadership", stat: "Fel" },
    { name: "Melee (Basic)", stat: "WS" },
    { name: "Navigation", stat: "I" },
    { name: "Outdoor Survival", stat: "Int" },
    { name: "Perception", stat: "I" },
    { name: "Ride", stat: "Ag" },
    { name: "Row", stat: "S" },
    { name: "Stealth", stat: "Ag" }
];

function renderBasicSkillsGrid(c) {
    const grid = document.getElementById('m-basic-skills-grid');
    if (!grid) return;
    grid.innerHTML = '';

    const skAdvMap = c.basic_skill_advances || {};

    BASIC_SKILLS_DEF.forEach((sk, idx) => {
        const adv = skAdvMap[sk.name] !== undefined ? skAdvMap[sk.name] : 0;
        const statTot = parseInt(document.getElementById(`m-stat-${sk.stat}-tot`)?.value, 10) || 30;
        const totSkill = statTot + adv;

        const item = document.createElement('div');
        item.style.cssText = 'display: flex; justify-content: space-between; align-items: center; background: #fff8ee; border: 1.5px solid #8b7961; padding: 5px 8px; font-size: 12px; border-radius: 3px;';
        item.innerHTML = `
            <div style="font-weight: bold; color: #1c130b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px;" title="${sk.name}">${sk.name} <span style="font-weight:normal; color:#7a1717;">(${sk.stat})</span></div>
            <div style="display: flex; align-items: center; gap: 5px;">
                <span style="color:#4a1212; font-weight:bold; font-size:11px;">Adv:</span>
                <input type="number" id="m-bsk-adv-${idx}" value="${adv}" oninput="updateBasicSkillTotal(${idx}, '${sk.stat}')" style="width: 32px; text-align: center; border: 1.5px solid #8b7961; background: #fff; font-size: 12px; font-weight: bold; color: #1c130b; padding: 2px;">
                <span style="font-weight: bold; color: #7a1717; min-width: 24px; text-align: right; font-size: 14px;" id="m-bsk-tot-${idx}">${totSkill}</span>
            </div>
        `;
        grid.appendChild(item);
    });
}

function updateBasicSkillTotal(idx, stat) {
    const adv = parseInt(document.getElementById(`m-bsk-adv-${idx}`).value, 10) || 0;
    const statTot = parseInt(document.getElementById(`m-stat-${stat}-tot`)?.value, 10) || 30;
    const totEl = document.getElementById(`m-bsk-tot-${idx}`);
    if (totEl) totEl.innerText = statTot + adv;
}

function calcMovement() {
    const baseM = parseInt(document.getElementById('m-char-move-base').value, 10) || 4;
    document.getElementById('m-char-move-walk').value = baseM * 2;
    document.getElementById('m-char-move-run').value = baseM * 4;
}

function calcWoundsFormula() {
    const s = parseInt(document.getElementById('m-stat-S-tot').value, 10) || 30;
    const t = parseInt(document.getElementById('m-stat-T-tot').value, 10) || 30;
    const wp = parseInt(document.getElementById('m-stat-WP-tot').value, 10) || 30;
    const hardy = parseInt(document.getElementById('m-wnd-hardy').value, 10) || 0;

    const sb = Math.floor(s / 10);
    const tb = Math.floor(t / 10);
    const wpb = Math.floor(wp / 10);

    document.getElementById('m-wnd-sb').value = sb;
    document.getElementById('m-wnd-tb2').value = tb * 2;
    document.getElementById('m-wnd-wpb').value = wpb;

    const maxWounds = sb + (tb * 2) + wpb + hardy;
    document.getElementById('m-char-wounds-max').value = maxWounds;

    const maxEnc = sb + tb;
    const encMaxEl = document.getElementById('m-enc-max');
    if (encMaxEl) encMaxEl.value = maxEnc;

    const maxCorr = tb + wpb;
    const corrMaxEl = document.getElementById('m-char-corr-max');
    if (corrMaxEl) corrMaxEl.value = maxCorr;
}

function calcStatTotal(stat) {
    const init = parseInt(document.getElementById(`m-stat-${stat}-init`).value, 10) || 0;
    const adv = parseInt(document.getElementById(`m-stat-${stat}-adv`).value, 10) || 0;
    const totEl = document.getElementById(`m-stat-${stat}-tot`);
    if (totEl) totEl.value = init + adv;

    calcWoundsFormula();
    BASIC_SKILLS_DEF.forEach((sk, idx) => {
        if (sk.stat === stat) updateBasicSkillTotal(idx, stat);
    });
}

let editingCharOriginalName = '';

function openCharSheetModal(idx) {
    if (!currentCampaign || !currentCampaign.characters || !currentCampaign.characters[idx]) return;
    editingCharIndex = idx;
    const c = currentCampaign.characters[idx];
    editingCharOriginalName = c.name || '';

    document.getElementById('modal-char-title').innerText = `⚜ CHARACTER SHEET — ${(c.name || 'UNNAMED').toUpperCase()} ⚜`;
    
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = (val !== undefined && val !== null) ? val : '';
    };

    setVal('m-char-name', c.name);
    setVal('m-char-race', c.species || c.race || 'Human');
    setVal('m-char-species', c.species || c.race || 'Human');
    setVal('m-char-class', c.class);
    setVal('m-char-career', c.career);
    setVal('m-char-level', c.career_level);
    setVal('m-char-path', c.career_path);
    setVal('m-char-status', c.status);
    setVal('m-char-age', c.age);
    setVal('m-char-height', c.height);
    setVal('m-char-hair', c.hair || c.hair_color);
    setVal('m-char-eyes', c.eyes || c.eye_color);
    setVal('m-char-doomed', c.doomed);
    setVal('m-char-starsign', c.starsign || c.star_sign);
    setVal('m-char-motivation', c.motivation);

    // Characteristics (Initial, Advances, Total)
    const chars = c.characteristics || {};
    ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].forEach(stat => {
        const valObj = chars[stat];
        let init = 30, adv = 0, tot = 30;
        if (typeof valObj === 'object' && valObj !== null) {
            init = valObj.initial !== undefined ? valObj.initial : 30;
            adv = valObj.advances !== undefined ? valObj.advances : 0;
            tot = valObj.total !== undefined ? valObj.total : (init + adv);
        } else if (typeof valObj === 'number') {
            init = valObj; adv = 0; tot = valObj;
        }
        setVal(`m-stat-${stat}-init`, init);
        setVal(`m-stat-${stat}-adv`, adv);
        setVal(`m-stat-${stat}-tot`, tot);
    });

    // Pools & derived 
    const w = c.wounds || {};
    setVal('m-char-wounds-max', w.max || 10);
    setVal('m-char-wounds-curr', (w.current !== undefined) ? w.current : (w.max || 10));
    setVal('m-wnd-hardy', c.hardy_advances || 0);

    const ft = c.fate || {};
    setVal('m-char-fate-total', (typeof ft === 'object') ? (ft.total || c.fate || 3) : (c.fate || 3));
    setVal('m-char-fortune-curr', (c.fortune && c.fortune.current !== undefined) ? c.fortune.current : ((typeof ft === 'object') ? (ft.total || 3) : 3));

    const res = c.resilience || {};
    setVal('m-char-resilience-tot', (typeof res === 'object') ? (res.total || c.resilience || 0) : (c.resilience || 0));
    const rsl = c.resolve || {};
    setVal('m-char-resolve-curr', (typeof rsl === 'object') ? (rsl.current || c.resolve || 0) : (c.resolve || 0));

    const mv = c.move || {};
    const baseM = (typeof mv === 'object') ? (mv.base || c.move || 4) : (c.move || 4);
    setVal('m-char-move-base', baseM);
    setVal('m-char-move-walk', (typeof mv === 'object') ? (mv.walk || baseM * 2) : (baseM * 2));
    setVal('m-char-move-run', (typeof mv === 'object') ? (mv.run || baseM * 4) : (baseM * 4));

    const xp = c.xp || {};
    setVal('m-char-xp-tot', (typeof xp === 'object') ? (xp.total || 0) : (c.xp || 0));
    setVal('m-char-xp-spent', (typeof xp === 'object') ? (xp.spent || 0) : (c.xp_spent || 0));
    setVal('m-char-xp-curr', (typeof xp === 'object') ? (xp.current || 0) : Math.max(0, (c.xp || 0) - (c.xp_spent || 0)));

    // Render 25 Basic Skills
    renderBasicSkillsGrid(c);
    calcWoundsFormula();

    // Grouped Skills, Talents, Trappings 
    const formatSkills = (skList) => (skList || []).map(s => typeof s === 'object' ? `${s.name} (+${s.advances || 0})` : s).join(', ');
    const formatTalents = (tList) => (tList || []).map(t => typeof t === 'object' ? `${t.name} ${t.rank || 1}` : t).join(', ');

    setVal('m-char-skills', formatSkills(c.skills));
    setVal('m-char-talents', formatTalents(c.talents));

    const arm = c.armour || {};
    setVal('m-arm-head', arm.head || 0);
    setVal('m-arm-body', arm.body || 0);
    setVal('m-arm-larm', arm.l_arm || 0);
    setVal('m-arm-rarm', arm.r_arm || 0);
    setVal('m-arm-lleg', arm.l_leg || 0);
    setVal('m-arm-rleg', arm.r_leg || 0);
    setVal('m-arm-shield', arm.shield || 0);

    const enc = c.encumbrance || {};
    setVal('m-enc-curr', enc.current || 0);
    setVal('m-enc-max', enc.max || 6);

    // Money 
    const mon = c.money || {};
    setVal('m-money-gc', mon.gc || 0);
    setVal('m-money-ss', mon.ss || 0);
    setVal('m-money-bp', mon.bp || 0);

    // Sin, Corruption & Psychology 
    setVal('m-char-sin', c.sin || 0);
    const corr = c.corruption || {};
    setVal('m-char-corr-curr', (typeof corr === 'object') ? (corr.current || 0) : (c.corruption || 0));
    setVal('m-char-corr-max', (typeof corr === 'object') ? (corr.max || 6) : 6);

    const psych = c.psychology || {};
    setVal('m-char-psychology', typeof psych === 'object' ? (psych.notes || psych.mutations || '') : psych);
    // Clear and populate Page 345 Weapons, Spells & Trappings tables
    const wBody = document.getElementById('m-weapons-table-body');
    if (wBody) {
        wBody.innerHTML = '';
        const wList = c.weapons || [];
        if (wList.length === 0) {
            addWeaponRow({name: 'Hand Weapon', group: 'Basic', enc: 1, range: 'Melee', damage: '+SB+4', qualities: ''});
        } else {
            wList.forEach(wItem => {
                if (typeof wItem === 'object' && wItem !== null) addWeaponRow(wItem);
                else addWeaponRow({name: String(wItem)});
            });
        }
    }

    const sBody = document.getElementById('m-spells-table-body');
    if (sBody) {
        sBody.innerHTML = '';
        const sList = c.spells || [];
        if (sList.length === 0) {
            addSpellRow({});
        } else {
            sList.forEach(sItem => {
                if (typeof sItem === 'object' && sItem !== null) addSpellRow(sItem);
                else addSpellRow({name: String(sItem)});
            });
        }
    }

    const tBody = document.getElementById('m-trappings-table-body');
    if (tBody) {
        tBody.innerHTML = '';
        const tList = c.trappings || [];
        if (tList.length === 0) {
            addTrappingRow({name: 'Clothing', enc: 0});
            addTrappingRow({name: 'Dagger', enc: 0});
            addTrappingRow({name: 'Pouch', enc: 0});
        } else {
            tList.forEach(tItem => {
                if (typeof tItem === 'object' && tItem !== null) addTrappingRow(tItem);
                else addTrappingRow({name: String(tItem), enc: 0});
            });
        }
    }
    calcArmourAndEncSummary();

    const hBody = document.getElementById('m-hirelings-table-body');
    if (hBody) {
        hBody.innerHTML = '';
        const hList = c.hirelings || [];
        if (hList.length === 0) {
            // Optional: don't auto add a row for hirelings if they have none
        } else {
            hList.forEach(hItem => {
                if (typeof hItem === 'object' && hItem !== null) addHirelingRow(hItem);
                else addHirelingRow({name: String(hItem)});
            });
        }
    }


    // Ambitions 
    const amb = c.ambitions || {};
    setVal('m-amb-short', amb.short);
    setVal('m-amb-long', amb.long);
    setVal('m-amb-party', amb.party);

    // Ten Questions 
    const tq = c.ten_questions || {};
    setVal('m-q-origin', tq.origin);
    setVal('m-q-family', tq.family);
    setVal('m-q-childhood', tq.childhood);
    setVal('m-q-why_leave', tq.why_leave);
    setVal('m-q-friends', tq.friends);
    setVal('m-q-desire', tq.desire);
    setVal('m-q-memories', tq.memories);
    setVal('m-q-religion', tq.religion);
    setVal('m-q-loyalty', tq.loyalty);
    setVal('m-q-secret', tq.secret);

    switchModalTab('p344');
    const modalEl = document.getElementById('char-sheet-modal');
    if (modalEl) modalEl.style.display = 'block';
}

function closeCharSheetModal() {
    document.getElementById('char-sheet-modal').style.display = 'none';
    editingCharIndex = -1;
}

function switchModalTab(tabName) {
    ['p344', 'p345', 'ambitions', 'questions'].forEach(t => {
        const sec = document.getElementById(`modal-tab-${t}`);
        if (sec) sec.style.display = t === tabName ? 'block' : 'none';
        const btn = document.getElementById(`tab-btn-${t}`);
        if (btn) {
            if (t === tabName) {
                btn.style.background = '#8b1e1e';
                btn.style.borderColor = '#d4af37';
                btn.style.color = '#f2e6ce';
                btn.style.fontWeight = 'bold';
            } else {
                btn.style.background = '#3a2a1a';
                btn.style.borderColor = '#5c4732';
                btn.style.color = '#c9b897';
                btn.style.fontWeight = 'normal';
            }
        }
    });
}

async function saveModalCharSheet() {
    if (editingCharIndex < 0 || !currentCampaign) return;

    const getVal = (id, def = '') => {
        const el = document.getElementById(id);
        return el ? (el.value !== undefined ? el.value.trim() : def) : def;
    };

    const getNum = (id, def = 0) => {
        const el = document.getElementById(id);
        if (!el || el.value === undefined || el.value === '') return def;
        const n = parseInt(el.value, 10);
        return isNaN(n) ? def : n;
    };

    const parseList = (str) => str.split(',').map(s => s.trim()).filter(Boolean);

    const chars = {};
    ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].forEach(stat => {
        const init = getNum(`m-stat-${stat}-init`, 30);
        const adv = getNum(`m-stat-${stat}-adv`, 0);
        const tot = getNum(`m-stat-${stat}-tot`, init + adv);
        chars[stat] = {initial: init, advances: adv, total: tot};
    });

    const basicSkillAdvances = {};
    BASIC_SKILLS_DEF.forEach((sk, idx) => {
        const advEl = document.getElementById(`m-bsk-adv-${idx}`);
        if (advEl) basicSkillAdvances[sk.name] = parseInt(advEl.value, 10) || 0;
    });

    const ageVal = getVal('m-char-age', '');

    // Extract Page 345 Table Rows
    const weaponsList = [];
    document.querySelectorAll('#m-weapons-table-body tr').forEach(tr => {
        const name = tr.querySelector('.w-name')?.value.trim();
        if (name) {
            weaponsList.push({
                name,
                type: tr.querySelector('.w-type')?.value.trim() || '',
                group: tr.querySelector('.w-group')?.value.trim() || 'Basic',
                enc: parseFloat(tr.querySelector('.w-enc')?.value) || 0,
                range: tr.querySelector('.w-range')?.value.trim() || 'Melee',
                damage: tr.querySelector('.w-damage')?.value.trim() || '+SB+4',
                qualities: tr.querySelector('.w-qualities')?.value.trim() || ''
            });
        }
    });

    const spellsList = [];
    document.querySelectorAll('#m-spells-table-body tr').forEach(tr => {
        const name = tr.querySelector('.s-name')?.value.trim();
        if (name) {
            spellsList.push({
                name,
                tn: tr.querySelector('.s-tn')?.value.trim() || '0',
                range: tr.querySelector('.s-range')?.value.trim() || 'Touch',
                target: tr.querySelector('.s-target')?.value.trim() || '1',
                duration: tr.querySelector('.s-duration')?.value.trim() || 'Instant',
                effect: tr.querySelector('.s-effect')?.value.trim() || ''
            });
        }
    });

    const trappingsList = [];
    document.querySelectorAll('#m-trappings-table-body tr').forEach(tr => {
        const name = tr.querySelector('.t-name')?.value.trim();
        if (name) {
            trappingsList.push({
                name,
                enc: parseFloat(tr.querySelector('.t-enc')?.value) || 0,
                equipped: tr.querySelector('.t-eq')?.checked || false
            });
        }
    });

    const hirelingsList = [];
    document.querySelectorAll('#m-hirelings-table-body tr').forEach(tr => {
        const name = tr.querySelector('.h-name')?.value.trim();
        if (name) {
            hirelingsList.push({
                name,
                daily_cost: tr.querySelector('.h-daily')?.value.trim() || '',
                notes: tr.querySelector('.h-notes')?.value.trim() || ''
            });
        }
    });

    const updatedChar = {
        name: getVal('m-char-name', 'Unnamed Agent'),
        original_name: editingCharOriginalName || getVal('m-char-name', 'Unnamed Agent'),
        race: getVal('m-char-species', getVal('m-char-race', '')),
        species: getVal('m-char-species', getVal('m-char-race', '')),
        class: getVal('m-char-class', ''),
        career: getVal('m-char-career', ''),
        career_level: getVal('m-char-level', ''),
        career_path: getVal('m-char-path', ''),
        status: getVal('m-char-status', ''),
        age: ageVal ? parseInt(ageVal, 10) : null,
        height: getVal('m-char-height', ''),
        hair: getVal('m-char-hair', ''),
        hair_color: getVal('m-char-hair', ''),
        eyes: getVal('m-char-eyes', ''),
        eye_color: getVal('m-char-eyes', ''),
        doomed: getVal('m-char-doomed', ''),
        starsign: getVal('m-char-starsign', ''),
        star_sign: getVal('m-char-starsign', ''),
        motivation: getVal('m-char-motivation', ''),
        characteristics: chars,
        basic_skill_advances: basicSkillAdvances,
        hardy_advances: getNum('m-wnd-hardy', 0),
        wounds: {
            max: getNum('m-char-wounds-max', 10),
            current: getNum('m-char-wounds-curr', 10),
        },
        fate: {
            total: getNum('m-char-fate-total', 3),
            current: getNum('m-char-fate-total', 3),
        },
        fortune: {
            total: getNum('m-char-fate-total', 3),
            current: getNum('m-char-fortune-curr', 3),
        },
        resilience: {
            total: getNum('m-char-resilience-tot', 0),
            current: getNum('m-char-resilience-tot', 0),
        },
        resolve: {
            total: getNum('m-char-resolve-curr', 0),
            current: getNum('m-char-resolve-curr', 0),
        },
        move: {
            base: getNum('m-char-move-base', 4),
            walk: getNum('m-char-move-walk', 8),
            run: getNum('m-char-move-run', 16),
        },
        xp: {
            total: getNum('m-char-xp-tot', 0),
            spent: getNum('m-char-xp-spent', 0),
            current: getNum('m-char-xp-curr', 0),
        },
        skills: parseList(getVal('m-char-skills', '')),
        talents: parseList(getVal('m-char-talents', '')),
        trappings: trappingsList,
        weapons: weaponsList,
        hirelings: hirelingsList,
        armour: {
            head: getNum('m-arm-head', 0),
            body: getNum('m-arm-body', 0),
            l_arm: getNum('m-arm-larm', 0),
            r_arm: getNum('m-arm-rarm', 0),
            l_leg: getNum('m-arm-lleg', 0),
            r_leg: getNum('m-arm-rleg', 0),
            shield: getNum('m-arm-shield', 0),
            items: []
        },
        encumbrance: {
            current: getNum('m-enc-curr', 0),
            max: getNum('m-enc-max', 6),
        },
        money: {
            gc: getNum('m-money-gc', 0),
            ss: getNum('m-money-ss', 0),
            bp: getNum('m-money-bp', 0),
        },
        sin: getNum('m-char-sin', 0),
        corruption: {
            current: getNum('m-char-corr-curr', 0),
            max: getNum('m-char-corr-max', 6),
        },
        psychology: {
            notes: getVal('m-char-psychology', '')
        },
        spells: spellsList,
        ambitions: {
            short: getVal('m-amb-short', ''),
            long: getVal('m-amb-long', ''),
            party: getVal('m-amb-party', ''),
        },
        ten_questions: {
            origin: getVal('m-q-origin', ''),
            family: getVal('m-q-family', ''),
            childhood: getVal('m-q-childhood', ''),
            why_leave: getVal('m-q-why_leave', ''),
            friends: getVal('m-q-friends', ''),
            desire: getVal('m-q-desire', ''),
            memories: getVal('m-q-memories', ''),
            religion: getVal('m-q-religion', ''),
            loyalty: getVal('m-q-loyalty', ''),
            secret: getVal('m-q-secret', ''),
        }
    };

    try {
        await executeWithSaveFeedback('save-char-sheet-modal-btn', async () => {
            const res = await fetch('/api/campaign/character/upsert', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(updatedChar)
            });
            const data = await res.json();
            if (data.ok) {
                currentCampaign = data.active_campaign;
                if (typeof renderCampaignDashboard === 'function') renderCampaignDashboard(currentCampaign);
                if (typeof fetchCampaign === 'function') fetchCampaign();
                setTimeout(() => { closeCharSheetModal(); }, 600);
                return true;
            } else {
                alert("Save failed: " + (data.error || "Unknown server error"));
                return false;
            }
        }, '💾 SAVE CHARACTER SHEET');
    } catch(e) {
        console.error("saveModalCharSheet error:", e);
        alert("Character save error: " + e.message);
    }
}


// ── CLIENT ROUTER & CAMPAIGN ROSTER RENDERER ─────────────────────────────────
function navigateToView(path) {
    window.history.pushState({}, '', path);
    handleRouting();
}

function handleRouting() {
    const p = window.location.pathname;
    const termView = document.getElementById('view-terminal');
    const campView = document.getElementById('view-campaign');
    const memView = document.getElementById('view-memory');

    if (p === '/campaign' || window.location.hash === '#campaign') {
        if (termView) termView.style.display = 'none';
        if (memView) memView.style.display = 'none';
        if (campView) campView.style.display = 'block';
        document.body.style.background = '#160e08';
        fetchCampaign();
    } else if (p === '/memory' || window.location.hash === '#memory') {
        if (termView) termView.style.display = 'none';
        if (campView) campView.style.display = 'none';
        if (memView) memView.style.display = 'block';
        document.body.style.background = 'var(--bg-color, #020803)';
        fetchMemories();
    } else {
        if (termView) termView.style.display = 'block';
        if (campView) campView.style.display = 'none';
        if (memView) memView.style.display = 'none';
        document.body.style.background = 'var(--bg-color, #020803)';
    }
}

window.addEventListener('popstate', handleRouting);
document.addEventListener('DOMContentLoaded', handleRouting);
// Run handleRouting immediately in case DOM is already loaded
setTimeout(handleRouting, 50);

async function fetchCampaign() {
    try {
        const res = await fetch('/api/campaign');
        const data = await res.json();
        if (!data.ok) return;

        currentCampaign = data.active_campaign;
        populateCampaignSelect(data.campaigns, currentCampaign);
        renderCampaignDashboard(currentCampaign);
        fetchCatalogs();
    } catch(e) { console.error('fetchCampaign error:', e); }
}

let serverArmourCatalog = [];
let serverWeaponsCatalog = [];
let serverTrappingsCatalog = [];
let serverHirelingsCatalog = [];

async function fetchCatalogs() {
    try {
        const [aRes, wRes, tRes, hRes] = await Promise.all([
            fetch('/api/campaign/armour_catalog'),
            fetch('/api/campaign/weapons_catalog'),
            fetch('/api/campaign/trappings_catalog'),
            fetch('/api/campaign/hirelings_catalog')
        ]);
        
        if (aRes.ok) {
            const data = await aRes.json();
            serverArmourCatalog = data.armour_catalog || [];
            populateDatalist('armour-list', serverArmourCatalog);
        }
        if (wRes.ok) {
            const data = await wRes.json();
            serverWeaponsCatalog = data.weapons_catalog || [];
            populateDatalist('weapons-list', serverWeaponsCatalog);
        }
        if (tRes.ok) {
            const data = await tRes.json();
            serverTrappingsCatalog = data.trappings_catalog || [];
        }
        if (hRes.ok) {
            const data = await hRes.json();
            serverHirelingsCatalog = data.hirelings_catalog || [];
            populateDatalist('hirelings-list', serverHirelingsCatalog);
        }

        // Combine Trappings, Weapons, and Armour into a master trappings-list
        const combinedMap = new Map();
        serverTrappingsCatalog.forEach(item => {
            if (item.name) combinedMap.set(item.name.toLowerCase(), item);
        });
        serverWeaponsCatalog.forEach(w => {
            if (w.name && !combinedMap.has(w.name.toLowerCase())) {
                combinedMap.set(w.name.toLowerCase(), {
                    name: w.name,
                    category: w.group_name ? `Weapon (${w.group_name})` : 'Weapon',
                    encumbrance: w.encumbrance !== undefined ? w.encumbrance : 1
                });
            }
        });
        serverArmourCatalog.forEach(a => {
            if (a.name && !combinedMap.has(a.name.toLowerCase())) {
                combinedMap.set(a.name.toLowerCase(), {
                    name: a.name,
                    category: a.category ? `Armour (${a.category})` : 'Armour',
                    encumbrance: a.encumbrance !== undefined ? a.encumbrance : 1
                });
            }
        });

        const combinedTrappingsCatalog = Array.from(combinedMap.values());
        populateDatalist('trappings-list', combinedTrappingsCatalog);

    } catch (e) {
        console.error('Error fetching catalogs:', e);
    }
}

function populateDatalist(listId, catalog) {
    const dlist = document.getElementById(listId);
    if (!dlist) return;
    dlist.innerHTML = '';
    catalog.forEach(item => {
        if (!item || !item.name) return;
        const opt = document.createElement('option');
        opt.value = item.name;
        
        let extra = '';
        if (item.category) {
            extra = item.category;
        } else if (item.group_name) {
            extra = item.group_name;
        } else if (item.ap !== undefined) {
            extra = `${item.locations} (${item.ap} AP)`;
        } else if (item.daily_cost !== undefined) {
            extra = item.daily_cost;
        }
        
        if (extra) {
            opt.setAttribute('label', extra);
        }
        opt.textContent = item.name;
        dlist.appendChild(opt);
    });
}

function populateCampaignSelect(campaignList, active) {
    const sel = document.getElementById('campaign-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- Select Campaign --</option>';
    (campaignList || []).forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.innerText = c.name + (c.adventure ? ` (${c.adventure})` : '');
        if (active && active.name === c.name) opt.selected = true;
        sel.appendChild(opt);
    });
}

async function switchCampaign(name) {
    if (!name) return;
    try {
        const res = await fetch('/api/campaign/load', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            renderCampaignDashboard(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

async function createNewCampaignPrompt() {
    const name = prompt("Enter new campaign name (e.g. 'The Enemy Within'):");
    if (!name || !name.trim()) return;
    const adventure = prompt("Enter adventure title (optional):", "Shadows Over Bögenhafen") || "";

    try {
        const res = await fetch('/api/campaign/new', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name.trim(), adventure: adventure.trim()})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            fetchCampaign();
        }
    } catch(e) { console.error(e); }
}

function formatCareerLevel(levelStr) {
    if (!levelStr) return 'Level 1';
    let clean = String(levelStr).trim();
    clean = clean.replace(/\s*\((?:Brass|Silver|Gold)\s*\d+\)/i, '').trim();
    if (clean.toLowerCase().startsWith('lvl')) clean = clean.substring(3).trim();
    if (clean.toLowerCase().startsWith('level')) clean = clean.substring(5).trim();
    return `Level ${clean}`;
}

function renderCampaignDashboard(c) {
    const setInner = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.innerText = text;
    };
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val;
    };

    if (!c) {
        setInner('c-tab-badge', 'NO CAMPAIGN');
        setInner('c-location', 'The Reikland');
        setInner('c-adventure', 'None');
        const g = document.getElementById('character-roster-grid');
        if (g) g.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 30px; color: #5c4732; font-size: 15px;">No active campaign selected. Select or create a campaign above.</div>';
        return;
    }

    setInner('c-tab-badge', (c.name || 'UNNAMED CAMPAIGN').toUpperCase());
    setInner('c-location', c.current_location || 'The Reikland');
    setInner('c-adventure', c.adventure || 'Standard Campaign');
    setVal('c-amb-short-inp', c.party_ambition_short || '');
    setVal('c-amb-long-inp', c.party_ambition_long || '');
    setVal('c-notes-input', c.notes || (c.session_notes ? c.session_notes.join('\n') : ''));

    const chars = c.characters || [];
    setInner('roster-count-badge', `${chars.length} CHARACTER${chars.length === 1 ? '' : 'S'}`);

    const grid = document.getElementById('character-roster-grid');
    if (!grid) return;
    grid.innerHTML = '';

    if (chars.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732; font-size: 15px;">No characters in party roster yet. Click "Roll New Character" or "Add Blank Character Sheet" to add your first hero!</div>';
        return;
    }

    chars.forEach((char, idx) => {
        const card = document.createElement('div');
        card.style.cssText = 'background: #e9e0d0; border: 2px solid #4a3c30; border-radius: 4px; padding: 18px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: flex; flex-direction: column; justify-content: space-between; color: #1c130b;';

        const w = char.wounds || {};
        const currW = (typeof w === 'object' && w.current !== undefined) ? w.current : ((typeof w === 'number') ? w : 10);
        const maxW = (typeof w === 'object' && w.max !== undefined) ? w.max : 10;
        const wPct = Math.min(100, Math.max(0, (currW / maxW) * 100));

        const charStats = char.characteristics || {};
        const statSummary = ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].map(st => {
            let val = 30;
            if (charStats[st] !== undefined) {
                if (typeof charStats[st] === 'object' && charStats[st] !== null) {
                    val = charStats[st].total !== undefined ? charStats[st].total : (charStats[st].initial || 30);
                } else if (typeof charStats[st] === 'number') {
                    val = charStats[st];
                }
            }
            return `<div style="text-align:center; border-right:1px solid #b8ab97;"><div style="font-size:11px; font-weight:bold; color:#f7efe2; background:#7a1717; padding:2px 0;">${st}</div><div style="font-size:15px; font-weight:bold; color:#1c130b; background:#fffbf4; padding:4px 0;">${val}</div></div>`;
        }).join('');

        const fateVal = typeof char.fate === 'object' ? (char.fate.total || 3) : (char.fate || 3);
        const fortuneVal = typeof char.fortune === 'object' ? (char.fortune.current || 3) : (char.fortune || 3);

        card.innerHTML = `
            <div>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; border-bottom: 2px solid #7a1717; padding-bottom: 8px;">
                    <div>
                        <h3 style="font-family: var(--font-title); font-size: 20px; font-weight: bold; color: #7a1717; margin: 0 0 2px 0;">${char.name || 'Unnamed Agent'}</h3>
                        <div style="font-size: 13px; color: #4a3c30; font-weight: bold;">${char.race || 'Human'} ${char.career || 'Career'} • ${formatCareerLevel(char.career_level)}</div>
                    </div>
                    <span style="font-size: 11px; background: #7a1717; color: #f7efe2; padding: 3px 8px; border-radius: 3px; font-weight: bold; font-family: var(--font-title);">${char.status || 'Tier I'}</span>
                </div>

                <!-- Wounds Bar -->
                <div style="margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: bold; color: #4a3c30; margin-bottom: 4px;">
                        <span style="font-family: var(--font-title); color: #7a1717;">WOUNDS:</span>
                        <span>${currW} / ${maxW}</span>
                    </div>
                    <div style="height: 10px; background: #dcd0bc; border: 1.5px solid #6c5d4f; border-radius: 3px; overflow: hidden;">
                        <div style="width: ${wPct}%; height: 100%; background: ${wPct < 30 ? '#c62828' : '#2e7d32'};"></div>
                    </div>
                </div>

                <!-- 10 Characteristics Strip (XP Table Style) -->
                <div style="display: grid; grid-template-columns: repeat(10, 1fr); border: 1.5px solid #6c5d4f; border-radius: 3px; overflow: hidden; margin-bottom: 14px;">
                    ${statSummary}
                </div>

                <div style="font-size: 13px; line-height: 1.5; color: #1c130b; margin-bottom: 14px; background: #fffbf4; border: 1px solid #b8ab97; padding: 10px; border-radius: 3px;">
                    <div><strong style="color: #7a1717; font-family: var(--font-title);">Fate / Fortune:</strong> ${fateVal} / ${fortuneVal}</div>
                    <div><strong style="color: #7a1717; font-family: var(--font-title);">Trappings:</strong> ${(char.trappings || []).slice(0, 5).map(t => typeof t === 'object' && t !== null ? t.name : String(t)).filter(Boolean).join(', ') || 'Basic gear'}</div>
                </div>
            </div>

            <div style="display: flex; gap: 8px; margin-top: 12px; border-top: 1.5px solid #8b7961; padding-top: 10px;">
                <button onclick="openCharSheetModal(${idx})" style="flex-grow: 1; background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 8px 14px; font-family: var(--font-title); font-size: 12px; font-weight: bold; cursor: pointer; border-radius: 3px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">📜 FULL CHARACTER SHEET</button>
            </div>
        `;
        grid.appendChild(card);
    });
    if (typeof renderCompendiumData === 'function') renderCompendiumData(c);
}

async function saveCampaignNotes() {
    if (!currentCampaign) return;
    const notes = document.getElementById('c-notes-input').value;
    await executeWithSaveFeedback('save-session-notes-btn', async () => {
        const res = await fetch('/api/campaign/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({notes})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            return true;
        }
        return false;
    }, '💾 SAVE NOTES');
}

function rollNewPartyCharacterPrompt() {
    openCharCreationWizard();
}

// ── WFRP 4E WEB CHARACTER CREATION WIZARD ENGINE ────────────────────────────
let wizardRollData = null;

const WIZARD_RACIAL_BASES = {
    human:    { WS: 20, BS: 20, S: 20, T: 20, I: 20, Ag: 20, Dex: 20, Int: 20, WP: 20, Fel: 20, woundsBonus: 0, fate: 2, fortune: 2, resilience: 1, resolve: 1, extraPoints: 3, move: 4, xpBonus: 20 },
    dwarf:    { WS: 30, BS: 20, S: 20, T: 30, I: 20, Ag: 10, Dex: 30, Int: 20, WP: 40, Fel: 10, woundsBonus: 0, fate: 0, fortune: 0, resilience: 2, resolve: 2, extraPoints: 2, move: 3, xpBonus: 0 },
    halfling: { WS: 10, BS: 30, S: 10, T: 20, I: 20, Ag: 20, Dex: 30, Int: 20, WP: 30, Fel: 30, woundsBonus: 0, fate: 0, fortune: 0, resilience: 2, resolve: 2, extraPoints: 3, move: 3, xpBonus: 0 },
    high_elf: { WS: 30, BS: 30, S: 20, T: 20, I: 40, Ag: 30, Dex: 30, Int: 30, WP: 30, Fel: 20, woundsBonus: 0, fate: 0, fortune: 0, resilience: 0, resolve: 0, extraPoints: 2, move: 5, xpBonus: 0 },
    wood_elf: { WS: 30, BS: 30, S: 20, T: 20, I: 50, Ag: 40, Dex: 30, Int: 30, WP: 30, Fel: 10, woundsBonus: 0, fate: 0, fortune: 0, resilience: 0, resolve: 0, extraPoints: 2, move: 5, xpBonus: 0 }
};

// ── WFRP 4E PHYSICAL DETAILS RANDOM TABLES ──────────────────────────────────
const WIZARD_EYE_COLOUR_TABLE = {
    2: ["Free Choice", "Coal", "Light Grey", "Jet", "Ivory"],
    3: ["Green", "Lead", "Grey", "Amethyst", "Charcoal"],
    4: ["Pale Blue", "Steel", "Pale Blue", "Aquamarine", "Ivy Green"],
    5: ["Blue", "Blue", "Blue", "Sapphire", "Mossy Green"],
    6: ["Blue", "Blue", "Blue", "Sapphire", "Mossy Green"],
    7: ["Blue", "Blue", "Blue", "Sapphire", "Mossy Green"],
    8: ["Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"],
    9: ["Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"],
    10: ["Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"],
    11: ["Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"],
    12: ["Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"],
    13: ["Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"],
    14: ["Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"],
    15: ["Brown", "Hazel", "Brown", "Amber", "Dark Brown"],
    16: ["Brown", "Hazel", "Brown", "Amber", "Dark Brown"],
    17: ["Brown", "Hazel", "Brown", "Amber", "Dark Brown"],
    18: ["Hazel", "Green", "Copper", "Copper", "Tan"],
    19: ["Dark Brown", "Copper", "Dark Brown", "Citrine", "Sandy Brown"],
    20: ["Black", "Gold", "Dark Brown", "Gold", "Violet"]
};

const WIZARD_HAIR_COLOUR_TABLE = {
    2: ["White Blond", "White", "Grey", "Silver", "Birch Silver"],
    3: ["Golden Blond", "Grey", "Flaxen", "White", "Ash Blond"],
    4: ["Red Blond", "Pale Blond", "Russet", "Pale Blond", "Rose Gold"],
    5: ["Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"],
    6: ["Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"],
    7: ["Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"],
    8: ["Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"],
    9: ["Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"],
    10: ["Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"],
    11: ["Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"],
    12: ["Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"],
    13: ["Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"],
    14: ["Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"],
    15: ["Black", "Brown", "Mustard", "Red Blond", "Dark Brown"],
    16: ["Black", "Brown", "Mustard", "Red Blond", "Dark Brown"],
    17: ["Black", "Brown", "Mustard", "Red Blond", "Dark Brown"],
    18: ["Auburn", "Dark Brown", "Almond", "Auburn", "Sienna"],
    19: ["Red", "Reddish Brown", "Chocolate", "Red", "Ebony"],
    20: ["Grey", "Black", "Liquorice", "Black", "Blue-Black"]
};

const WIZARD_STAR_SIGN_TABLE = [
    { min: 1, max: 5, name: "Wymund the Hermit (Sign of Endurance)" },
    { min: 6, max: 10, name: "Big Moebius (Sign of Grasping)" },
    { min: 11, max: 15, name: "The Limner's Line (Sign of Precision)" },
    { min: 16, max: 20, name: "Gnuthus the Ox (Sign of Dutifulness)" },
    { min: 21, max: 25, name: "Dragund the Drake (Sign of Courage)" },
    { min: 26, max: 30, name: "The Glorious Call (Sign of Fall)" },
    { min: 31, max: 35, name: "The Piper (Sign of the Trickster)" },
    { min: 36, max: 40, name: "Vobist the Goat (Sign of Impatience)" },
    { min: 41, max: 45, name: "The Cauldron (Sign of Creation)" },
    { min: 46, max: 50, name: "Caelora the Dove (Sign of Peace)" },
    { min: 51, max: 55, name: "The Two Bullocks (Sign of Fertility)" },
    { min: 56, max: 60, name: "The Dancer (Sign of Passion)" },
    { min: 61, max: 65, name: "The Drummer (Sign of Excess)" },
    { min: 66, max: 70, name: "The Piper's Song (Sign of Music)" },
    { min: 71, max: 75, name: "The Broken Cart (Sign of Pride)" },
    { min: 76, max: 80, name: "The Greed (Sign of Avarice)" },
    { min: 81, max: 85, name: "Rhya's Cauldron (Sign of Mercy)" },
    { min: 86, max: 90, name: "The Bones (Sign of Death)" },
    { min: 91, max: 95, name: "The Witchling Star (Sign of Magic)" },
    { min: 96, max: 100, name: "The Fool (Sign of Folly)" }
];

function getWizardSpeciesIndex(species) {
    const map = { human: 0, dwarf: 1, halfling: 2, high_elf: 3, wood_elf: 4 };
    return map[species] !== undefined ? map[species] : 0;
}

function wizardRollD(sides) {
    return Math.floor(Math.random() * sides) + 1;
}

function wizardRollSumD(count, sides) {
    let sum = 0;
    for (let i = 0; i < count; i++) sum += wizardRollD(sides);
    return sum;
}

function rollWizardAge(species) {
    const s = species || 'human';
    if (s === 'human') return 15 + wizardRollD(10);
    if (s === 'dwarf') return 15 + wizardRollSumD(10, 10);
    if (s === 'halfling') return 15 + wizardRollSumD(5, 10);
    if (s === 'high_elf' || s === 'wood_elf') return 30 + wizardRollSumD(10, 10);
    return 15 + wizardRollD(10);
}

function rollWizardHeight(species) {
    const s = species || 'human';
    let baseInches = 57;
    let extraInches = 0;
    if (s === 'human') {
        const d1 = wizardRollD(10), d2 = wizardRollD(10);
        extraInches = d1 + d2;
        if (d1 === 10 || d2 === 10) extraInches += wizardRollD(10);
        baseInches = 57;
    } else if (s === 'dwarf') {
        baseInches = 51;
        extraInches = wizardRollD(10);
    } else if (s === 'halfling') {
        baseInches = 37;
        extraInches = wizardRollD(10);
    } else if (s === 'high_elf' || s === 'wood_elf') {
        baseInches = 71;
        extraInches = wizardRollD(10);
    } else {
        baseInches = 57;
        extraInches = wizardRollD(10);
    }
    const tot = baseInches + extraInches;
    const feet = Math.floor(tot / 12);
    const inches = tot % 12;
    return `${feet}'${inches}"`;
}

function rollWizardEyeColor(species) {
    const idx = getWizardSpeciesIndex(species);
    const roll = wizardRollD(10) + wizardRollD(10);
    const row = WIZARD_EYE_COLOUR_TABLE[roll] || WIZARD_EYE_COLOUR_TABLE[10];
    return row[idx] || row[0];
}

function rollWizardHairColor(species) {
    const idx = getWizardSpeciesIndex(species);
    const roll = wizardRollD(10) + wizardRollD(10);
    const row = WIZARD_HAIR_COLOUR_TABLE[roll] || WIZARD_HAIR_COLOUR_TABLE[10];
    return row[idx] || row[0];
}

function rollWizardStarSign() {
    const roll = wizardRollD(100);
    const found = WIZARD_STAR_SIGN_TABLE.find(item => roll >= item.min && roll <= item.max);
    return found ? found.name : "The Two Bullocks (Sign of Fertility)";
}

function rollWizardDetail(field) {
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value : 'human';

    if (!field || field === 'age') {
        const el = document.getElementById('cc-age');
        if (el) el.value = rollWizardAge(species);
    }
    if (!field || field === 'height') {
        const el = document.getElementById('cc-height');
        if (el) el.value = rollWizardHeight(species);
    }
    if (!field || field === 'hair') {
        const el = document.getElementById('cc-hair');
        if (el) el.value = rollWizardHairColor(species);
    }
    if (!field || field === 'eyes') {
        const el = document.getElementById('cc-eyes');
        if (el) el.value = rollWizardEyeColor(species);
    }
    if (!field || field === 'starsign') {
        const el = document.getElementById('cc-starsign');
        if (el) el.value = rollWizardStarSign();
    }
}

let wizardAllocState = { WS: 10, BS: 10, S: 10, T: 10, I: 10, Ag: 10, Dex: 10, Int: 10, WP: 10, Fel: 10 };
let wizardExtraPointsAlloc = { fate: 0, resilience: 0 };

function openCharCreationWizard() {
    const modal = document.getElementById('char-creation-wizard-modal');
    if (modal) modal.style.display = 'block';
    switchWizardStep(1);
    onWizardSpeciesOrGenModeChange();
    rollWizardDetail();
}

function closeCharCreationWizard() {
    const modal = document.getElementById('char-creation-wizard-modal');
    if (modal) modal.style.display = 'none';
}

function switchWizardStep(stepNum) {
    [1, 2, 3, 4].forEach(s => {
        const stepDiv = document.getElementById(`cc-step-${s}`);
        if (stepDiv) stepDiv.style.display = (s === stepNum) ? 'block' : 'none';
        
        const badge = document.getElementById(`cc-step-badge-${s}`);
        if (badge) {
            if (s === stepNum) {
                badge.style.background = '#7a1717';
                badge.style.color = '#f5ebd9';
                badge.style.borderColor = '#d4af37';
            } else {
                badge.style.background = '#3a2a1a';
                badge.style.color = '#c9b897';
                badge.style.borderColor = '#5c4732';
            }
        }
    });

    if (stepNum === 4) {
        renderWizardSummary();
    }
}

function onWizardSpeciesOrGenModeChange() {
    const modeEl = document.querySelector('input[name="cc-gen-mode"]:checked');
    const genMode = modeEl ? modeEl.value : 'random';
    
    wizardExtraPointsAlloc = { fate: 0, resilience: 0 };
    
    if (genMode === 'random') {
        rollWizardCharacteristics();
    } else {
        resetWizardAllocations();
    }
    rollWizardDetail();
}

function adjustWizardExtraPoints(statKey, delta) {
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value : 'human';
    const racial = WIZARD_RACIAL_BASES[species] || WIZARD_RACIAL_BASES.human;
    
    const extraPointsTotal = racial.extraPoints || 0;
    
    const currentAlloc = wizardExtraPointsAlloc[statKey] || 0;
    const newAlloc = currentAlloc + delta;
    
    if (newAlloc < 0) return;
    
    const totalSpent = (statKey === 'fate' ? newAlloc : wizardExtraPointsAlloc.fate) + 
                       (statKey === 'resilience' ? newAlloc : wizardExtraPointsAlloc.resilience);
                       
    if (totalSpent > extraPointsTotal) return;
    
    wizardExtraPointsAlloc[statKey] = newAlloc;
    recalcWizardDerivedStats();
}

function toggleWizardGenMode() {
    const modeEl = document.querySelector('input[name="cc-gen-mode"]:checked');
    const genMode = modeEl ? modeEl.value : 'random';

    const randomControls = document.getElementById('cc-random-controls');
    const poolTracker = document.getElementById('cc-pool-tracker');
    const statsList = ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'];

    if (genMode === 'random') {
        if (randomControls) randomControls.style.display = 'flex';
        if (poolTracker) poolTracker.style.display = 'none';
        statsList.forEach(s => {
            const ctrl = document.getElementById(`cc-assign-ctrl-${s}`);
            if (ctrl) ctrl.style.display = 'none';
        });
        rollWizardCharacteristics();
    } else {
        if (randomControls) randomControls.style.display = 'none';
        if (poolTracker) poolTracker.style.display = 'block';
        statsList.forEach(s => {
            const ctrl = document.getElementById(`cc-assign-ctrl-${s}`);
            if (ctrl) ctrl.style.display = 'block';
        });
        resetWizardAllocations();
    }
}

function resetWizardAllocations() {
    wizardAllocState = { WS: 10, BS: 10, S: 10, T: 10, I: 10, Ag: 10, Dex: 10, Int: 10, WP: 10, Fel: 10 };
    wizardExtraPointsAlloc = { fate: 0, resilience: 0 };
    updateWizardAllocUI();
}

function adjustStatAlloc(statKey, delta) {
    const currentAlloc = wizardAllocState[statKey] || 0;
    const newAlloc = currentAlloc + delta;

    // WFRP 4E Core Rules: Allocation per stat between +4 and +20
    if (newAlloc < 4 || newAlloc > 20) return;

    // Check pool
    const currentTotalSpent = Object.values(wizardAllocState).reduce((a, b) => a + b, 0);
    const poolRemaining = 100 - currentTotalSpent;
    if (delta > 0 && poolRemaining < delta) return;

    wizardAllocState[statKey] = newAlloc;
    updateWizardAllocUI();
}

function updateWizardAllocUI() {
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value : 'human';
    const racial = WIZARD_RACIAL_BASES[species] || WIZARD_RACIAL_BASES.human;

    const statsList = ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'];
    let totalSpent = 0;

    statsList.forEach(s => {
        const alloc = wizardAllocState[s] !== undefined ? wizardAllocState[s] : 10;
        totalSpent += alloc;

        const allocSpan = document.getElementById(`cc-alloc-${s}`);
        if (allocSpan) allocSpan.innerText = `${alloc}`;

        const baseVal = racial[s] || 20;
        const totalVal = baseVal + alloc;
        const statInput = document.getElementById(`cc-stat-${s}`);
        if (statInput) statInput.value = totalVal;
    });

    const poolRemaining = 100 - totalSpent;
    const poolSpan = document.getElementById('cc-pool-remaining');
    if (poolSpan) {
        poolSpan.innerText = `${poolRemaining}`;
        poolSpan.style.color = poolRemaining === 0 ? '#2e7d32' : (poolRemaining < 0 ? '#7a1717' : '#d4af37');
    }

    recalcWizardDerivedStats();
    
    // Points Allocation gives +0 XP starting bonus
    const xpEl = document.getElementById('cc-derived-xp');
    if (xpEl) xpEl.innerText = '+0 XP';
}

function recalcWizardDerivedStats() {
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value : 'human';
    const racial = WIZARD_RACIAL_BASES[species] || WIZARD_RACIAL_BASES.human;

    const getVal = s => parseInt(document.getElementById(`cc-stat-${s}`)?.value, 10) || 30;
    const sVal = getVal('S');
    const tVal = getVal('T');
    const wpVal = getVal('WP');

    const sb = Math.floor(sVal / 10);
    const tb = Math.floor(tVal / 10);
    const wpb = Math.floor(wpVal / 10);

    const wounds = sb + (2 * tb) + wpb + (racial.woundsBonus || 0);

    const moveEl = document.getElementById('cc-derived-move');
    if (moveEl) moveEl.innerText = racial.move || 4;

    const woundsEl = document.getElementById('cc-derived-wounds');
    if (woundsEl) woundsEl.innerText = wounds;

    const f = (racial.fate || 0) + wizardExtraPointsAlloc.fate;
    const fateEl = document.getElementById('cc-derived-fate');
    if (fateEl) fateEl.innerText = `${f} / ${f}`;

    const r = (racial.resilience || 0) + wizardExtraPointsAlloc.resilience;
    const resEl = document.getElementById('cc-derived-resilience');
    if (resEl) resEl.innerText = `${r} / ${r}`;

    const spent = wizardExtraPointsAlloc.fate + wizardExtraPointsAlloc.resilience;
    const rem = (racial.extraPoints || 0) - spent;
    const remEl = document.getElementById('cc-extra-points-remaining');
    if (remEl) remEl.innerText = rem;
}

async function rollWizardCharacteristics() {
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value : 'human';
    const statusEl = document.getElementById('cc-roll-status');
    if (statusEl) statusEl.innerText = 'Rolling 2d10...';

    try {
        const res = await fetch('/api/campaign/roll_char', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({race: species})
        });
        const data = await res.json();
        if (data.ok && (data.characteristics || data.character_block)) {
            wizardRollData = data.characteristics || data.character_block;
            const chars = wizardRollData.characteristics || {};
            
            ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].forEach(stat => {
                const el = document.getElementById(`cc-stat-${stat}`);
                if (el) el.value = chars[stat] !== undefined ? chars[stat] : 30;
            });

            recalcWizardDerivedStats();

            const xpEl = document.getElementById('cc-derived-xp');
            if (xpEl) xpEl.innerText = `+${wizardRollData.xp_bonus || 20} XP`;

            if (statusEl) statusEl.innerText = `✓ Rolled 2d10 Stats for ${wizardRollData.race_display || species.toUpperCase()}!`;
        }
    } catch(e) {
        console.error('Wizard roll error:', e);
        if (statusEl) statusEl.innerText = 'Error rolling stats.';
    }
}

// ── WFRP 4E CAREER CATALOG & STEP 2 LOGIC ──────────────────────────────────
const WFRP_CAREER_CATALOG = {
    // Academics
    "Apothecary":   { class: "Academics", status: "Brass 3", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit & Parchment, Pestle & Mortar, Apothecary Trade Tools" },
    "Engineer":     { class: "Academics", status: "Brass 3", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit & Parchment, Trade Tools (Engineer)" },
    "Lawyer":       { class: "Academics", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit, Legal Documents" },
    "Physician":    { class: "Academics", status: "Silver 3", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit, Physician Trade Tools, Bandages" },
    "Scholar":      { class: "Academics", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit, 2 Books, Almanac" },
    "Wizard":       { class: "Academics", status: "Brass 3", trappings: "Clothing, Dagger, Pouch, Sling Bag with Writing Kit, Grimoire, Staff" },

    // Burghers
    "Agitator":     { class: "Burghers", status: "Brass 1", trappings: "Cloak, Clothing, Dagger, Hat, Pouch, Sling Bag with Pamphlets and Charcoal" },
    "Artisan":      { class: "Burghers", status: "Brass 2", trappings: "Cloak, Clothing, Dagger, Hat, Pouch, Trade Tools" },
    "Beggar":       { class: "Burghers", status: "Brass 1", trappings: "Ragged Clothes, Dagger, Bowl, Pouch" },
    "Investigator": { class: "Burghers", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Hat, Pouch, Magnifying Glass, Journal" },
    "Merchant":     { class: "Burghers", status: "Silver 2", trappings: "Fine Clothes, Dagger, Hat, Pouch, Abacus, Trade Tools (Merchant)" },
    "Watchman":     { class: "Burghers", status: "Brass 3", trappings: "Cloak, Clothing, Dagger, Hat, Pouch, Uniform, Lantern, Lamp Oil, Leather Jack" },

    // Courtiers
    "Advisor":      { class: "Courtiers", status: "Silver 2", trappings: "Courtly Garb, Dagger, Pouch, Writing Kit, Quill & Ink" },
    "Artist":       { class: "Courtiers", status: "Silver 1", trappings: "Courtly Garb, Dagger, Pouch, Trade Tools (Artist)" },
    "Duellist":     { class: "Courtiers", status: "Silver 3", trappings: "Courtly Garb, Dagger, Rapier, Main-Gauche, Pouch" },
    "Envoy":        { class: "Courtiers", status: "Silver 2", trappings: "Courtly Garb, Dagger, Pouch, Official Livery, Seal" },
    "Noble":        { class: "Courtiers", status: "Gold 1", trappings: "Courtly Garb, Fine Dagger, Jewelry worth 3d10 GC, Servant, Pouch" },
    "Servant":      { class: "Courtiers", status: "Brass 1", trappings: "Livery Clothing, Dagger, Pouch" },

    // Peasants
    "Bailiff":      { class: "Peasants", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Hand Weapon, Whip, Ledger" },
    "Hedge Witch":  { class: "Peasants", status: "Brass 1", trappings: "Cloak, Clothing, Dagger, Pouch, Healing Herbs, Charm" },
    "Herbalist":    { class: "Peasants", status: "Brass 2", trappings: "Cloak, Clothing, Dagger, Pouch, Herb Sickle, Leather Bag with Herbs" },
    "Hunter":       { class: "Peasants", status: "Brass 1", trappings: "Cloak, Clothing, Dagger, Pouch, Longbow, 20 Arrows, Hunting Trap" },
    "Miner":        { class: "Peasants", status: "Brass 2", trappings: "Cloak, Clothing, Dagger, Pouch, Pickaxe, Davi Lamp" },
    "Villager":     { class: "Peasants", status: "Brass 1", trappings: "Cloak, Clothing, Dagger, Pouch, Pitchfork or Staff" },

    // Rangers
    "Bounty Hunter":{ class: "Rangers", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Crossbow, 10 Bolts, Manacles, Rope" },
    "Coachman":     { class: "Rangers", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Whip, Blunderbuss, Powder & Shots" },
    "Entertainer":  { class: "Rangers", status: "Brass 2", trappings: "Cloak, Clothing, Dagger, Pouch, Musical Instrument or Juggling Balls" },
    "Flagellant":   { class: "Rangers", status: "Brass 1", trappings: "Tattered Robes, Flail, Scourge, Pouch, Holy Symbol" },
    "Road Warden":  { class: "Rangers", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Pistol with 10 Shots, Leather Jack, Shield" },

    // Riverfolk
    "Boatman":      { class: "Riverfolk", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Boat Hook, 10yd Rope" },
    "Huffer":       { class: "Riverfolk", status: "Brass 4", trappings: "Cloak, Clothing, Dagger, Pouch, Storm Lantern & Oil" },
    "Riverwarden":  { class: "Riverfolk", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Hand Weapon, Leather Jack, Riverwarden Badge" },
    "Seaman":       { class: "Riverfolk", status: "Silver 1", trappings: "Cloak, Clothing, Dagger, Pouch, Bucket, Tar, Rope" },
    "Smuggler":     { class: "Riverfolk", status: "Brass 2", trappings: "Cloak, Clothing, Dagger, Pouch, Rowboat or Hidden Compartment Bag" },
    "Stevedore":    { class: "Riverfolk", status: "Brass 3", trappings: "Cloak, Clothing, Dagger, Pouch, Cargo Hook" },

    // Rogues
    "Baiter":       { class: "Rogues", status: "Brass 2", trappings: "Clothing, Dagger, Pouch, Fighting Dog or Bear, Muzzle" },
    "Charlatan":    { class: "Rogues", status: "Brass 3", trappings: "Fine Clothing, Dagger, Pouch, Fake Elixirs, Playing Cards" },
    "Fence":        { class: "Rogues", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Scales, Hidden Safe or Pouch" },
    "Grave Robber": { class: "Rogues", status: "Brass 2", trappings: "Clothing, Dagger, Pouch, Shovel, Crowbar, Sack" },
    "Outlaw":       { class: "Rogues", status: "Brass 1", trappings: "Clothing, Dagger, Pouch, Bow or Hand Weapon, Leather Jack" },
    "Racketeer":    { class: "Rogues", status: "Silver 1", trappings: "Fine Clothing, Dagger, Knuckledusters, Pouch" },
    "Thief":        { class: "Rogues", status: "Brass 1", trappings: "Clothing, Dagger, Pouch, Lockpicks, Sack, Mask" },

    // Warriors
    "Cavalryman":   { class: "Warriors", status: "Silver 2", trappings: "Clothing, Dagger, Pouch, Cavalry Sabre, Saddle & Harness" },
    "Guard":        { class: "Warriors", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Halberd or Hand Weapon, Leather Jack" },
    "Knight":       { class: "Warriors", status: "Silver 3", trappings: "Clothing, Dagger, Pouch, Lance, Sword, Shield, Chainmail & Plate Armor" },
    "Pit Fighter":  { class: "Warriors", status: "Brass 4", trappings: "Clothing, Dagger, Pouch, Hand Weapon, Flail or Net, Bandages" },
    "Protagonist":  { class: "Warriors", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Zweihander or Great Weapon, Leather Jack" },
    "Soldier":      { class: "Warriors", status: "Silver 1", trappings: "Clothing, Dagger, Pouch, Hand Weapon, Shield, Leather Jack, Uniform" },
    "Slayer":       { class: "Warriors", status: "Brass 1", trappings: "Tattoos, Great Axe, Hand Axe, Dagger, Pouch" }
};

function populateWizardCareerSelect(className) {
    const careerSelect = document.getElementById('cc-career-select');
    if (!careerSelect) return;
    careerSelect.innerHTML = '';

    const careersInClass = Object.keys(WFRP_CAREER_CATALOG).filter(c => WFRP_CAREER_CATALOG[c].class === className);
    careersInClass.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c;
        opt.innerText = `${c} (${WFRP_CAREER_CATALOG[c].status})`;
        careerSelect.appendChild(opt);
    });

    if (careersInClass.length > 0) {
        careerSelect.value = careersInClass[0];
        onWizardCareerSelectChange();
    }
}

function onWizardClassSelectChange() {
    const classSelect = document.getElementById('cc-class-select');
    const className = classSelect ? classSelect.value : 'Warriors';
    populateWizardCareerSelect(className);
}

function onWizardCareerSelectChange() {
    const careerSelect = document.getElementById('cc-career-select');
    const career = careerSelect ? careerSelect.value : 'Soldier';
    
    const careerInput = document.getElementById('cc-career-input');
    if (careerInput) careerInput.value = career;

    const data = WFRP_CAREER_CATALOG[career] || { status: 'Silver 1', trappings: 'Clothing, Dagger, Pouch, Hand Weapon' };

    const statusInput = document.getElementById('cc-status');
    if (statusInput) statusInput.value = data.status;

    const trappingsArea = document.getElementById('cc-starter-kit');
    if (trappingsArea) trappingsArea.value = data.trappings;

    checkWizardOrTrappingChoices();
}

function checkWizardOrTrappingChoices() {
    const area = document.getElementById('cc-starter-kit');
    const container = document.getElementById('cc-or-choices-container');
    const listDiv = document.getElementById('cc-or-choices-list');
    if (!area || !container || !listDiv) return true;

    const rawItems = area.value.split(',').map(s => s.trim()).filter(Boolean);
    const choices = rawItems.filter(item => /\s+or\s+/i.test(item));

    if (choices.length === 0) {
        container.style.display = 'none';
        listDiv.innerHTML = '';
        return true;
    }

    container.style.display = 'block';
    listDiv.innerHTML = '';

    choices.forEach(choiceStr => {
        const options = choiceStr.split(/\s+or\s+/i).map(s => s.trim());
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; background:#fff; padding:6px 10px; border:1px solid #856404; border-radius:3px; font-size:12px;';

        const safeStr = choiceStr.replace(/'/g, "\\'");
        let optsHtml = `<option value="">-- Choose Trapping --</option>`;
        options.forEach(opt => {
            optsHtml += `<option value="${opt.replace(/"/g, '&quot;')}">${opt}</option>`;
        });

        row.innerHTML = `
            <span style="font-weight:bold; color:#7a1717;">Option for '${choiceStr}':</span>
            <select onchange="resolveWizardOrChoice('${safeStr}', this.value)" style="border:1.5px solid #8b7961; padding:4px 8px; font-weight:bold; font-size:12px; background:#fff8ee; border-radius:3px;">
                ${optsHtml}
            </select>
        `;
        listDiv.appendChild(row);
    });

    return false;
}

function resolveWizardOrChoice(rawChoiceStr, chosenVal) {
    if (!chosenVal) return;
    const area = document.getElementById('cc-starter-kit');
    if (!area) return;

    const items = area.value.split(',').map(s => s.trim()).filter(Boolean);
    const updatedItems = items.map(item => item === rawChoiceStr ? chosenVal : item);

    area.value = updatedItems.join(', ');
    checkWizardOrTrappingChoices();
}

function toggleWizardCareerMode() {
    const modeEl = document.querySelector('input[name="cc-career-mode"]:checked');
    const careerMode = modeEl ? modeEl.value : 'random';

    const randomBar = document.getElementById('cc-career-random-bar');
    const xpBadge = document.getElementById('cc-career-xp-badge');

    if (careerMode === 'random') {
        if (randomBar) randomBar.style.display = 'flex';
        if (xpBadge) xpBadge.innerText = '+50 XP (Random Roll)';
        rollWizardRandomCareer();
    } else {
        if (randomBar) randomBar.style.display = 'none';
        if (xpBadge) xpBadge.innerText = '+0 XP (Manual Select)';
        onWizardClassSelectChange();
    }
}

function rollWizardRandomCareer() {
    const careers = Object.keys(WFRP_CAREER_CATALOG);
    const rolled = careers[Math.floor(Math.random() * careers.length)];
    const data = WFRP_CAREER_CATALOG[rolled];

    const classSelect = document.getElementById('cc-class-select');
    if (classSelect) {
        classSelect.value = data.class;
        populateWizardCareerSelect(data.class);
    }

    const careerSelect = document.getElementById('cc-career-select');
    if (careerSelect) {
        careerSelect.value = rolled;
        onWizardCareerSelectChange();
    }

    const statusEl = document.getElementById('cc-career-roll-status');
    if (statusEl) statusEl.innerText = `✓ Rolled Career: ${rolled} (${data.class}) — Status: ${data.status} [+50 XP]`;
}

function renderWizardSummary() {
    const summaryDiv = document.getElementById('cc-review-summary');
    if (!summaryDiv) return;

    const getVal = (id, def = '') => {
        const el = document.getElementById(id);
        return el ? (el.value ? el.value.trim() : def) : def;
    };

    const name = getVal('cc-name', 'New Hero');
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const species = speciesEl ? speciesEl.value.replace('_', ' ').toUpperCase() : 'HUMAN';
    const className = getVal('cc-class-select', 'Warriors');
    const career = getVal('cc-career-input', 'Soldier');
    const statusTier = getVal('cc-status', 'Silver 1');
    
    const genModeEl = document.querySelector('input[name="cc-gen-mode"]:checked');
    const genMode = genModeEl ? genModeEl.value : 'random';
    const step1XP = (genMode === 'random') ? (wizardRollData ? (wizardRollData.xp_bonus || 20) : 20) : 0;

    const careerModeEl = document.querySelector('input[name="cc-career-mode"]:checked');
    const careerMode = careerModeEl ? careerModeEl.value : 'random';
    const step2XP = (careerMode === 'random') ? 50 : 0;

    const totalXP = step1XP + step2XP;

    const statsList = ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].map(s => {
        const val = getVal(`cc-stat-${s}`, '30');
        return `<strong>${s}:</strong> ${val}`;
    }).join(' | ');

    summaryDiv.innerHTML = `
        <div style="font-size: 16px; font-weight: bold; color: #7a1717; margin-bottom: 6px;">⚜ ${name} (${species} ${career})</div>
        <div style="margin-bottom: 10px;"><strong>Class:</strong> ${className} | <strong>Status:</strong> ${statusTier} | <strong>Starting XP Bonus:</strong> <span style="color:#2e7d32; font-weight:bold;">+${totalXP} XP</span></div>
        <div style="background: #fff; border: 1.5px solid #8b7961; padding: 10px; border-radius: 4px; font-size: 12px; margin-bottom: 12px;">
            ${statsList}
        </div>
        <div style="font-size: 12px; color: #4a1212;">
            Ready to create character and add to your active party roster!
        </div>
    `;
}

async function finishCharacterCreationWizard() {
    if (!checkWizardOrTrappingChoices()) {
        alert("Please resolve all required Trapping choices ('X or Y') in Step 2 before finalizing your character!");
        switchWizardStep(2);
        return;
    }

    const getVal = (id, def = '') => {
        const el = document.getElementById(id);
        return el ? (el.value ? el.value.trim() : def) : def;
    };

    const name = getVal('cc-name', 'New Hero');
    const speciesEl = document.querySelector('input[name="cc-species"]:checked');
    const raceKey = speciesEl ? speciesEl.value : 'human';
    const SPECIES_DISPLAYS = {
        human: "Human (Reiklander)",
        dwarf: "Dwarf",
        halfling: "Halfling",
        high_elf: "High Elf (Asur)",
        wood_elf: "Wood Elf (Asrai)"
    };
    const raceDisplay = (wizardRollData && wizardRollData.race_display) ? wizardRollData.race_display : (SPECIES_DISPLAYS[raceKey] || 'Human');
    const className = getVal('cc-class-select', 'Warriors');
    const career = getVal('cc-career-input', 'Soldier');
    const careerLevel = getVal('cc-career-level', '1');
    const statusTier = getVal('cc-status', 'Silver 1');

    const genModeEl = document.querySelector('input[name="cc-gen-mode"]:checked');
    const genMode = genModeEl ? genModeEl.value : 'random';
    const step1XP = (genMode === 'random') ? (wizardRollData ? (wizardRollData.xp_bonus || 20) : 20) : 0;

    const careerModeEl = document.querySelector('input[name="cc-career-mode"]:checked');
    const careerMode = careerModeEl ? careerModeEl.value : 'random';
    const step2XP = (careerMode === 'random') ? 50 : 0;

    const startingXP = step1XP + step2XP;

    const characteristics = {};
    ['WS','BS','S','T','I','Ag','Dex','Int','WP','Fel'].forEach(s => {
        const val = parseInt(getVal(`cc-stat-${s}`, '30'), 10) || 30;
        characteristics[s] = { initial: val, advances: 0, total: val };
    });

    const woundsMax = parseInt(document.getElementById('cc-derived-wounds')?.innerText, 10) || (wizardRollData ? (wizardRollData.wounds_max || 12) : 12);

    const starterKitStr = getVal('cc-starter-kit', 'Clothing, Dagger, Pouch, Hand Weapon, Leather Jack');
    const trappings = starterKitStr.split(',').map(s => s.trim()).filter(Boolean).map(item => {
        return { name: item, enc: 1, equipped: item.toLowerCase().includes('weapon') || item.toLowerCase().includes('jack') || item.toLowerCase().includes('clothing') };
    });

    const speciesKey = document.querySelector('input[name="cc-species"]:checked')?.value || 'human';
    const racial = WIZARD_RACIAL_BASES[speciesKey] || WIZARD_RACIAL_BASES.human;
    const finalFate = (racial.fate || 0) + wizardExtraPointsAlloc.fate;
    const finalRes = (racial.resilience || 0) + wizardExtraPointsAlloc.resilience;

    const newChar = {
        id: 'char_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
        name: name,
        race: raceDisplay,
        species: raceDisplay,
        class: className,
        career: career,
        career_level: careerLevel,
        status: statusTier,
        age: getVal('cc-age', '25'),
        height: getVal('cc-height', "5'10\""),
        hair: getVal('cc-hair', 'Brown'),
        hair_color: getVal('cc-hair', 'Brown'),
        eyes: getVal('cc-eyes', 'Blue'),
        eye_color: getVal('cc-eyes', 'Blue'),
        starsign: getVal('cc-starsign', 'The Two Bullocks'),
        star_sign: getVal('cc-starsign', 'The Two Bullocks'),
        characteristics: characteristics,
        wounds: { max: woundsMax, current: woundsMax },
        fate: finalFate,
        fortune: finalFate,
        resilience: finalRes,
        resolve: finalRes,
        move: wizardRollData ? wizardRollData.move : 4,
        xp: { current: startingXP, total: startingXP },
        ambitions: {
            short: getVal('cc-amb-short', ''),
            long: getVal('cc-amb-long', ''),
            party: ''
        },
        trappings: trappings,
        weapons: [],
        spells: [],
        hirelings: []
    };

    try {
        const res = await fetch('/api/campaign/character/upsert', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(newChar)
        });
        const data = await res.json();
        if (data.ok) {
            if (data.active_campaign) currentCampaign = data.active_campaign;
            else {
                if (!currentCampaign) currentCampaign = { characters: [] };
                if (!currentCampaign.characters) currentCampaign.characters = [];
                currentCampaign.characters.push(newChar);
            }
            closeCharCreationWizard();
            renderCampaignDashboard(currentCampaign);
            if (typeof fetchCampaign === 'function') fetchCampaign();
            const newIdx = currentCampaign.characters.length - 1;
            openCharSheetModal(newIdx);
        } else {
            alert("Save failed: " + (data.error || "Unknown server error"));
        }
    } catch(e) {
        console.error("finishCharacterCreationWizard error:", e);
        alert("Error saving character: " + e.message);
    }
}

function openCharSheetModalForNew() {
    openCharCreationWizard();
}

async function addNpcPrompt() {
    const name = prompt("Enter NPC Name:");
    if (!name || !name.trim()) return;
    const role = prompt("Enter NPC Role/Career (e.g. Boatmaster, Merchant):", "") || "";
    const disposition = prompt("Disposition (Friendly, Neutral, Hostile, Suspicious):", "Neutral") || "Neutral";
    const notes = prompt("Public Notes:", "") || "";

    try {
        const res = await fetch('/api/campaign/npc/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name.trim(), role_career: role.trim(), disposition, notes})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            renderCampaignDashboard(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

async function addTimelineEventPrompt() {
    const summary = prompt("Enter event summary:");
    if (!summary || !summary.trim()) return;
    const dateStr = prompt("In-game date (e.g. 2502 IC):", "2502 IC") || "2502 IC";

    try {
        const res = await fetch('/api/campaign/timeline/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event_summary: summary.trim(), in_game_date: dateStr.trim()})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            renderCampaignDashboard(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

let characterToDelete = "";

function openDeleteConfirmModal() {
    const nameEl = document.getElementById('m-char-name');
    characterToDelete = nameEl ? nameEl.value.trim() : "";
    if (!characterToDelete) {
        alert("No valid character selected for deletion.");
        return;
    }
    document.getElementById('delete-target-char-name').innerText = characterToDelete;
    const inputEl = document.getElementById('delete-confirm-input');
    inputEl.value = "";
    const btn = document.getElementById('delete-confirm-submit-btn');
    btn.disabled = true;
    btn.style.opacity = "0.5";
    document.getElementById('delete-confirm-modal').style.display = "flex";
}

function closeDeleteConfirmModal() {
    document.getElementById('delete-confirm-modal').style.display = "none";
}

function checkDeleteConfirmInput(val) {
    const btn = document.getElementById('delete-confirm-submit-btn');
    if (val.trim() === "DELETE") {
        btn.disabled = false;
        btn.style.opacity = "1";
    } else {
        btn.disabled = true;
        btn.style.opacity = "0.5";
    }
}

async function executeDeleteCharacter() {
    if (!characterToDelete) return;
    const charId = (editingCharIndex >= 0 && currentCampaign && currentCampaign.characters[editingCharIndex]) ? currentCampaign.characters[editingCharIndex].id : null;
    try {
        const res = await fetch('/api/campaign/character/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: charId, name: characterToDelete})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            closeDeleteConfirmModal();
            closeCharSheetModal();
            renderCampaignDashboard(currentCampaign);
        } else {
            alert("Delete failed: " + (data.error || "Unknown server error"));
        }
    } catch(e) {
        console.error("executeDeleteCharacter error:", e);
        alert("Error deleting character: " + e.message);
    }
}

// ── COMPENDIUM & GM SECRETS ENGINE ───────────────────────────────────────────
let activeCompendiumTab = 'roster';
let currentDetailEntity = null; // {type: 'npc'|'location'|'quest', item: dict}

function switchCompendiumTab(tabKey) {
    activeCompendiumTab = tabKey;
    ['roster', 'npcs', 'locations', 'quests', 'timeline'].forEach(t => {
        const btn = document.getElementById(`comp-tab-${t}`);
        const pane = document.getElementById(`comp-pane-${t}`);
        if (t === tabKey) {
            if (btn) { btn.style.background = '#7a1717'; btn.style.borderColor = '#4a0e0e'; }
            if (pane) pane.style.display = 'block';
        } else {
            if (btn) { btn.style.background = '#3d2f23'; btn.style.borderColor = '#231911'; }
            if (pane) pane.style.display = 'none';
        }
    });
    // Ensure roster grid is inside comp-pane-roster
    const grid = document.getElementById('character-roster-grid');
    const rosterPane = document.getElementById('comp-pane-roster');
    if (grid && rosterPane && grid.parentElement !== rosterPane) {
        rosterPane.appendChild(grid);
    }
}

async function loadAdventureModules() {
    try {
        const res = await fetch('/api/modules');
        const data = await res.json();
        if (data.ok) {
            renderModulesList(data.modules);
        }
    } catch (e) {
        console.error("Failed to load modules:", e);
    }
}

function renderModulesList(modules) {
    const list = document.getElementById('comp-modules-list');
    if (!list) return;
    list.innerHTML = '';
    if (!modules || modules.length === 0) {
        list.innerHTML = '<div style="text-align: center; color: #8b7961; font-style: italic; padding: 10px;">No modules available.</div>';
        return;
    }
    
    modules.forEach(mod => {
        const div = document.createElement('div');
        div.style.padding = '10px';
        div.style.background = '#fffbf4';
        div.style.border = '1px solid #c9bda5';
        div.style.borderRadius = '3px';
        div.style.cursor = 'pointer';
        div.innerHTML = `<div style="font-weight: bold; color: #5c4732;">${mod.title}</div>`;
        div.onclick = () => loadModuleDetails(mod.slug);
        list.appendChild(div);
    });
}

async function loadModuleDetails(slug) {
    try {
        const res = await fetch(`/api/modules/${slug}`);
        const data = await res.json();
        if (data.ok) {
            renderModuleDetails(data.module);
        }
    } catch (e) {
        console.error("Failed to load module details:", e);
    }
}

function renderModuleDetails(mod) {
    const detail = document.getElementById('comp-modules-detail');
    if (!detail) return;
    
    let html = `<h2 style="font-family: var(--font-title); color: #7a1717; margin-top: 0;">${mod.title}</h2>`;
    html += `<p style="color: #5c4732; font-size: 14px; margin-bottom: 20px;">${mod.description}</p>`;
    
    if (mod.cover_image_path) {
        html += `<img src="${mod.cover_image_path}" style="max-width: 100%; border: 1.5px solid #8b7961; border-radius: 4px; margin-bottom: 20px;">`;
    }
    
    html += `<button onclick="window.open('/module/${mod.slug}', '_blank')" style="background: #7a1717; color: #fffbf4; border: 1px solid #5c4732; padding: 8px 16px; font-family: var(--font-title); font-size: 16px; cursor: pointer; border-radius: 4px; margin-bottom: 20px;">View Full Module</button>`;
    
    html += `<h3 style="font-family: var(--font-title); color: #7a1717; margin-bottom: 10px; border-bottom: 1px solid #c9bda5; padding-bottom: 4px;">Chapters</h3>`;
    mod.chapters.forEach(chap => {
        html += `<div style="margin-bottom: 16px;">`;
        html += `<div style="font-weight: bold; color: #5c4732; font-size: 15px;">Chapter ${chap.chapter_number}: ${chap.title}</div>`;
        html += `<div style="font-size: 13px; color: #8b7961; margin-bottom: 8px;">Location: ${chap.location_name}</div>`;
        
        if (chap.events && chap.events.length > 0) {
            html += `<div style="margin-left: 15px;">`;
            chap.events.forEach(ev => {
                html += `<div style="font-size: 13px; color: #1c130b; margin-bottom: 4px;"><strong>${ev.time_label}:</strong> ${ev.description || ''}</div>`;
            });
            html += `</div>`;
        }
        html += `</div>`;
    });
    
    if (mod.npcs && mod.npcs.length > 0) {
        html += `<h3 style="font-family: var(--font-title); color: #7a1717; margin-bottom: 10px; border-bottom: 1px solid #c9bda5; padding-bottom: 4px;">NPCs</h3>`;
        html += `<div style="display: flex; flex-wrap: wrap; gap: 10px;">`;
        mod.npcs.forEach(npc => {
            html += `<div style="border: 1px solid #c9bda5; padding: 10px; border-radius: 4px; background: #e9e0d0; width: calc(50% - 5px); box-sizing: border-box;">`;
            if (npc.image_path) {
                html += `<img src="${npc.image_path}" style="width: 100%; height: auto; border: 1px solid #8b7961; border-radius: 2px; margin-bottom: 8px;">`;
            }
            html += `<div style="font-weight: bold; color: #5c4732;">${npc.name}</div>`;
            html += `</div>`;
        });
        html += `</div>`;
    }
    
    detail.innerHTML = html;
}


function renderCompendiumData(c) {
    if (!c) return;
    
    // Render NPCs
    const npcGrid = document.getElementById('comp-npc-grid');
    if (npcGrid) {
        npcGrid.innerHTML = '';
        const npcs = c.npcs || [];
        if (npcs.length === 0) {
            npcGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No NPCs recorded yet. Click "Add New NPC" above to track key characters.</div>';
        } else {
            npcs.forEach(n => {
                const card = document.createElement('div');
                card.style.cssText = 'background: #e9e0d0; border: 2px solid #4a3c30; border-radius: 4px; padding: 14px; color: #1c130b; box-shadow: 0 3px 8px rgba(0,0,0,0.15); display: flex; flex-direction: column; justify-content: space-between;';
                const dispColor = n.disposition === 'Friendly' ? '#2e7d32' : (n.disposition === 'Hostile' ? '#c62828' : '#e65100');
                card.innerHTML = `
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; border-bottom: 1.5px solid #7a1717; padding-bottom: 6px;">
                            <div>
                                <h3 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">${n.name}</h3>
                                <div style="font-size: 12px; color: #4a3c30; font-weight: bold;">${n.role_career || 'NPC'} (${n.species || 'Human'})</div>
                            </div>
                            <span style="font-size: 11px; background: ${dispColor}; color: #fff; padding: 2px 6px; border-radius: 3px; font-weight: bold;">${n.disposition || 'Neutral'}</span>
                        </div>
                        <div style="font-size: 13px; line-height: 1.4; color: #1c130b; margin-bottom: 10px;">
                            <div><strong>Notes:</strong> ${(n.notes || 'No public notes').slice(0, 90)}...</div>
                            ${n.secrets_lore ? '<div style="font-size: 11px; color: #7a1717; font-weight: bold; margin-top: 4px;">🔒 Includes Secret GM Lore</div>' : ''}
                        </div>
                    </div>
                    <button onclick='openCompendiumReadout("npc", ${JSON.stringify(n).replace(/'/g, "&#39;")})' style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">📜 FULL READOUT & GM SECRETS</button>
                `;
                npcGrid.appendChild(card);
            });
        }
    }

    // Render Locations
    const locGrid = document.getElementById('comp-location-grid');
    if (locGrid) {
        locGrid.innerHTML = '';
        const locs = c.locations || [];
        if (locs.length === 0) {
            locGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No locations recorded yet. Click "Add New Location" above.</div>';
        } else {
            locs.forEach(l => {
                const card = document.createElement('div');
                card.style.cssText = 'background: #e9e0d0; border: 2px solid #4a3c30; border-radius: 4px; padding: 14px; color: #1c130b; box-shadow: 0 3px 8px rgba(0,0,0,0.15); display: flex; flex-direction: column; justify-content: space-between;';
                card.innerHTML = `
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; border-bottom: 1.5px solid #7a1717; padding-bottom: 6px;">
                            <div>
                                <h3 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">${l.name}</h3>
                                <div style="font-size: 12px; color: #4a3c30; font-weight: bold;">${l.type || 'Site'} (${l.region || 'Reikland'})</div>
                            </div>
                            <span style="font-size: 11px; background: #3d2f23; color: #f7efe2; padding: 2px 6px; border-radius: 3px; font-weight: bold;">${l.danger_level || 'Low'} Danger</span>
                        </div>
                        <div style="font-size: 13px; line-height: 1.4; color: #1c130b; margin-bottom: 10px;">
                            <div>${(l.description || 'No description').slice(0, 90)}...</div>
                        </div>
                    </div>
                    <button onclick='openCompendiumReadout("location", ${JSON.stringify(l).replace(/'/g, "&#39;")})' style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">📜 FULL READOUT & GM SECRETS</button>
                `;
                locGrid.appendChild(card);
            });
        }
    }

    // Render Quests
    const questGrid = document.getElementById('comp-quest-grid');
    if (questGrid) {
        questGrid.innerHTML = '';
        const quests = c.quests || [];
        if (quests.length === 0) {
            questGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No active quests logged. Click "Add Quest" above.</div>';
        } else {
            quests.forEach(q => {
                const card = document.createElement('div');
                card.style.cssText = 'background: #e9e0d0; border: 2px solid #4a3c30; border-radius: 4px; padding: 14px; color: #1c130b; box-shadow: 0 3px 8px rgba(0,0,0,0.15); display: flex; flex-direction: column; justify-content: space-between;';
                card.innerHTML = `
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; border-bottom: 1.5px solid #7a1717; padding-bottom: 6px;">
                            <div>
                                <h3 style="font-family: var(--font-title); font-size: 18px; font-weight: bold; color: #7a1717; margin: 0;">${q.title}</h3>
                                <div style="font-size: 12px; color: #4a3c30; font-weight: bold;">${q.type || 'Main Quest'}</div>
                            </div>
                            <span style="font-size: 11px; background: #7a1717; color: #fff; padding: 2px 6px; border-radius: 3px; font-weight: bold;">${q.status || 'Active'}</span>
                        </div>
                        <div style="font-size: 13px; line-height: 1.4; color: #1c130b; margin-bottom: 10px;">
                            <div><strong>Objective:</strong> ${q.objective || 'No details'}</div>
                        </div>
                    </div>
                    <button onclick='openCompendiumReadout("quest", ${JSON.stringify(q).replace(/'/g, "&#39;")})' style="background: #7a1717; color: #f7efe2; border: 1.5px solid #4a0e0e; padding: 6px 12px; font-family: var(--font-title); font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">📜 FULL READOUT & GM SECRETS</button>
                `;
                questGrid.appendChild(card);
            });
        }
    }

    // Render Timeline
    const timeList = document.getElementById('comp-timeline-list');
    if (timeList) {
        timeList.innerHTML = '';
        const timeline = c.timeline || [];
        if (timeline.length === 0) {
            timeList.innerHTML = '<div style="text-align: center; padding: 30px; background: #e9e0d0; border: 1.5px dashed #8b7961; border-radius: 4px; color: #5c4732;">No timeline events logged.</div>';
        } else {
            timeline.forEach(t => {
                const item = document.createElement('div');
                item.style.cssText = 'background: #fffbf4; border: 1.5px solid #6c5d4f; border-left: 4px solid #7a1717; border-radius: 4px; padding: 12px; color: #1c130b;';
                item.innerHTML = `
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: bold; color: #7a1717; margin-bottom: 4px;">
                        <span>IMPERIAL DATE: ${t.in_game_date || '2502 IC'}</span>
                        <span>SESSION ${t.session_num || 1}</span>
                    </div>
                    <div style="font-size: 14px; line-height: 1.4; color: #1c130b;">${t.event_summary}</div>
                `;
                timeList.appendChild(item);
            });
        }
    }
}

function openCompendiumReadout(type, item) {
    currentDetailEntity = {type, item};
    document.getElementById('comp-detail-type-badge').innerText = type.toUpperCase();
    document.getElementById('comp-detail-title').innerText = item.name || item.title || 'Untitled Entry';
    document.getElementById('comp-detail-role').innerText = item.role_career || item.type || item.region || '--';
    
    // Public notes
    const pubText = item.notes || item.description || item.objective || 'No public details recorded.';
    document.getElementById('comp-detail-public-body').innerText = pubText;

    // GM secrets
    const secretText = item.secrets_lore || item.reward || item.gm_notes || 'No secret GM lore recorded for this entry.';
    document.getElementById('comp-detail-secret-body').innerText = secretText;

    // Reset secret toggle to collapsed
    const secCont = document.getElementById('comp-detail-secret-container');
    const secBtn = document.getElementById('toggle-gm-secret-btn');
    if (secCont) secCont.style.display = 'none';
    if (secBtn) { secBtn.innerText = '🔒 SHOW GM SECRETS'; secBtn.style.background = '#7a1717'; }

    document.getElementById('compendium-detail-modal').style.display = 'flex';
}

function closeCompendiumModal() {
    document.getElementById('compendium-detail-modal').style.display = 'none';
}

function toggleGmSecrets() {
    const secCont = document.getElementById('comp-detail-secret-container');
    const secBtn = document.getElementById('toggle-gm-secret-btn');
    if (!secCont || !secBtn) return;
    if (secCont.style.display === 'none') {
        secCont.style.display = 'block';
        secBtn.innerText = '🔓 HIDE GM SECRETS';
        secBtn.style.background = '#3d2f23';
    } else {
        secCont.style.display = 'none';
        secBtn.innerText = '🔒 SHOW GM SECRETS';
        secBtn.style.background = '#7a1717';
    }
}

async function addLocationPrompt() {
    const name = prompt("Enter Location Name:");
    if (!name || !name.trim()) return;
    const type = prompt("Type (City, Town, Inn, Dungeon, Region):", "Town") || "Town";
    const region = prompt("Region:", "Reikland") || "Reikland";
    const desc = prompt("Public Description:", "") || "";
    const secrets = prompt("🔒 Secret GM Lore / Hazards (Hidden from players):", "") || "";

    try {
        const res = await fetch('/api/campaign/location/upsert', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name.trim(), type, region, description: desc, secrets_lore: secrets, danger_level: 'Medium'})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            renderCampaignDashboard(currentCampaign);
            renderCompendiumData(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

async function addQuestPrompt() {
    const title = prompt("Enter Quest Title:");
    if (!title || !title.trim()) return;
    const type = prompt("Type (Main Quest, Side Quest, Investigation, Combat):", "Main Quest") || "Main Quest";
    const obj = prompt("Public Objective:", "") || "";
    const reward = prompt("🔒 Secret Reward / GM Plot Twist:", "") || "";

    try {
        const res = await fetch('/api/campaign/quest/upsert', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: title.trim(), type, objective: obj, reward, status: 'Active'})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            renderCampaignDashboard(currentCampaign);
            renderCompendiumData(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

async function deleteCurrentCompendiumEntity() {
    if (!currentDetailEntity || !currentDetailEntity.item) return;
    const {type, item} = currentDetailEntity;
    if (!confirm(`Are you sure you want to delete this ${type}?`)) return;

    let url = `/api/campaign/${type}/delete`;
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: item.id})
        });
        const data = await res.json();
        if (data.ok) {
            currentCampaign = data.active_campaign;
            closeCompendiumModal();
            renderCampaignDashboard(currentCampaign);
            renderCompendiumData(currentCampaign);
        }
    } catch(e) { console.error(e); }
}

// ── AUTHENTIC PAGE 345 TABLE ROW ENGINE ─────────────────────────────────────
function addWeaponRow(data = {}) {
    const tbody = document.getElementById('m-weapons-table-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    tr.style.background = '#fffbf4';

    const name = data.name || 'Hand Weapon';
    const specType = (data.type !== undefined && data.type !== null) ? data.type : ((data.spec_type !== undefined && data.spec_type !== null) ? data.spec_type : '');
    const group = data.group || 'Basic';
    const enc = data.enc !== undefined ? data.enc : 1;
    const range = data.range || 'Melee';
    const damage = data.damage || '+SB+4';
    const qualities = data.qualities || '';
    const srcKey = (data.source_key || name).toLowerCase();

    tr.setAttribute('data-source-key', srcKey);

    tr.innerHTML = `
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="w-name" value="${name}" readonly title="Derived Base Type (Read-Only)" style="width:100%; border:1px solid #c9b49a; background:#f5ebd9; font-size:12px; font-weight:bold; color:#7a1717; cursor:not-allowed; padding:2px;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="w-type" list="weapons-list" value="${specType}" placeholder="User Specific Name (e.g. Short Sword)" oninput="autoFillWeapon(this)" style="width:100%; border:1.5px solid #8b7961; background:#fff; font-size:12px; font-weight:bold; color:#1c130b; padding:2px;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="w-group" value="${group}" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <input type="number" class="w-enc" value="${enc}" oninput="calcArmourAndEncSummary()" style="width:38px; text-align:center; border:none; background:transparent; font-size:12px; font-weight:bold; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="w-range" value="${range}" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="w-damage" value="${damage}" style="width:100%; border:none; background:transparent; font-size:12px; font-weight:bold; color:#7a1717;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; display:flex; gap:4px; align-items:center;">
            <input type="text" class="w-qualities" value="${qualities}" placeholder="Qualities/Flaws" style="flex:1; border:none; background:transparent; font-size:11px; color:#1c130b;">
            <button type="button" onclick="openQualitiesModal(this.previousElementSibling)" style="background:#3d2f23; color:#f7efe2; border:none; font-size:10px; font-weight:bold; padding:2px 5px; cursor:pointer; border-radius:2px;">⚙️</button>
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <button type="button" onclick="this.closest('tr').remove(); calcArmourAndEncSummary();" style="background:#7a1717; color:#fff; border:none; font-size:10px; padding:2px 6px; cursor:pointer; border-radius:2px;">✖</button>
        </td>
    `;
    tbody.appendChild(tr);
}

function autoFillWeapon(input) {
    const tr = input.closest('tr');
    if (!tr) return;
    const name = input.value.trim().toLowerCase();
    const match = serverWeaponsCatalog.find(w => w.name.toLowerCase() === name);
    if (match) {
        const nameInput = tr.querySelector('.w-name');
        const groupInput = tr.querySelector('.w-group');
        const encInput = tr.querySelector('.w-enc');
        const rangeInput = tr.querySelector('.w-range');
        const dmgInput = tr.querySelector('.w-damage');
        const qualInput = tr.querySelector('.w-qualities');
        
        if (nameInput) nameInput.value = match.name;
        if (groupInput) groupInput.value = match.group_name || 'Basic';
        if (encInput) encInput.value = match.encumbrance !== undefined ? match.encumbrance : 1;
        if (rangeInput) rangeInput.value = match.reach_range || 'Melee';
        if (dmgInput) dmgInput.value = match.damage || '+SB+4';
        if (qualInput) qualInput.value = match.qualities || '';
        
        calcArmourAndEncSummary();
    }
}


function addSpellRow(data = {}) {
    const tbody = document.getElementById('m-spells-table-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    tr.style.background = '#fffbf4';
    tr.innerHTML = `
        <td style="padding: 4px; border: 1px solid #8b7961;"><input type="text" class="s-name" value="${data.name || ''}" placeholder="Spell / Prayer Name" style="width:100%; border:none; background:transparent; font-size:13px; font-weight:bold; color:#1c130b;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;"><input type="text" class="s-tn" value="${data.tn || '0'}" style="width:40px; text-align:center; border:none; background:transparent; font-size:13px; font-weight:bold; color:#7a1717;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961;"><input type="text" class="s-range" value="${data.range || 'Touch'}" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961;"><input type="text" class="s-target" value="${data.target || '1'}" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961;"><input type="text" class="s-duration" value="${data.duration || 'Instant'}" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961;"><input type="text" class="s-effect" value="${data.effect || ''}" placeholder="Spell Effect" style="width:100%; border:none; background:transparent; font-size:12px; color:#1c130b;"></td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;"><button type="button" onclick="this.closest('tr').remove();" style="background:#7a1717; color:#fff; border:none; font-size:10px; padding:2px 6px; cursor:pointer; border-radius:2px;">✖</button></td>
    `;
    tbody.appendChild(tr);
}

// ── AUTHENTIC ARMOUR & TRAPPINGS EQUIPPED AUTO-CALCULATOR ───────────────────
const WFRP_ARMOUR_CATALOG = [
    { name: "leather cap", enc: 0, ap: 1, locs: ["head"], desc: "Head (1 AP)" },
    { name: "leather skullcap", enc: 0, ap: 1, locs: ["head"], desc: "Head (1 AP)" },
    { name: "leather jerkin", enc: 1, ap: 1, locs: ["body"], desc: "Body (1 AP)" },
    { name: "leather jack", enc: 1, ap: 1, locs: ["body", "l_arm", "r_arm"], desc: "Body, Arms (1 AP)" },
    { name: "leather leggings", enc: 1, ap: 1, locs: ["l_leg", "r_leg"], desc: "Legs (1 AP)" },
    { name: "sleeved leather coat", enc: 2, ap: 1, locs: ["body", "l_arm", "r_arm"], desc: "Body, Arms (1 AP)" },
    { name: "mail coif", enc: 2, ap: 2, locs: ["head"], desc: "Head (2 AP)" },
    { name: "mail shirt", enc: 2, ap: 2, locs: ["body"], desc: "Body (2 AP)" },
    { name: "mail sleeves", enc: 1, ap: 2, locs: ["l_arm", "r_arm"], desc: "Arms (2 AP)" },
    { name: "mail chausses", enc: 3, ap: 2, locs: ["l_leg", "r_leg"], desc: "Legs (2 AP)" },
    { name: "mail coat", enc: 3, ap: 2, locs: ["body", "l_arm", "r_arm"], desc: "Body, Arms (2 AP)" },
    { name: "open helm", enc: 1, ap: 2, locs: ["head"], desc: "Head (2 AP)" },
    { name: "full helm", enc: 2, ap: 2, locs: ["head"], desc: "Head (2 AP)" },
    { name: "helm", enc: 2, ap: 2, locs: ["head"], desc: "Head (2 AP)" },
    { name: "breastplate", enc: 3, ap: 2, locs: ["body"], desc: "Body (2 AP)" },
    { name: "bracers", enc: 3, ap: 2, locs: ["l_arm", "r_arm"], desc: "Arms (2 AP)" },
    { name: "plate leggings", enc: 3, ap: 2, locs: ["l_leg", "r_leg"], desc: "Legs (2 AP)" },
    { name: "plate armour", enc: 6, ap: 2, locs: ["head", "body", "l_arm", "r_arm", "l_leg", "r_leg"], desc: "All (2 AP)" },
    { name: "buckler", enc: 0, ap: 1, locs: ["shield"], desc: "Shield (+1 AP)" },
    { name: "shield", enc: 1, ap: 2, locs: ["shield"], desc: "Shield (+2 AP)" },
    { name: "tower shield", enc: 3, ap: 3, locs: ["shield"], desc: "Shield (+3 AP)" }
];

const WFRP_TRAPPING_ENC_LOOKUP = {
    "hand weapon": 1, "sword": 1, "short sword": 1, "bastard sword": 3, "zweihänder": 3, "great axe": 3,
    "warhammer": 3, "halberd": 3, "spear": 2, "quarterstaff": 2, "dagger": 0, "knife": 0, "knuckledusters": 0,
    "bow": 2, "longbow": 3, "shortbow": 1, "crossbow": 2, "heavy crossbow": 3, "handgun": 2, "pistol": 0, "sling": 0,
    "leather jack": 1, "leather jerkin": 1, "leather leggings": 1, "leather skullcap": 0,
    "mail coat": 3, "mail shirt": 2, "mail coif": 2, "mail chausses": 3, "open helm": 1, "helm": 2, "bracers": 3, "plate leggings": 3, "breastplate": 3,
    "backpack": 2, "barrel": 6, "cask": 2, "flask": 0, "jug": 1, "pewter stein": 0, "pouch": 0,
    "sack": 2, "sack, large": 3, "saddlebags": 4, "sling bag": 1, "scroll case": 0, "waterskin": 1,
    "boots": 1, "sturdy boots": 1, "cloak": 1, "coat": 1, "clothing": 1, "uniform": 1, "robe": 1, "robes": 1,
    "amulet": 0, "gloves": 0, "shoes": 0, "jewellery": 0, "signet ring": 0, "hat": 0,
    "rope": 1, "animal trap": 1, "boat hook": 1, "broom": 2, "bucket": 1, "crowbar": 1, "crutch": 2,
    "hoe": 2, "pick": 1, "pole": 3, "rake": 2, "saw": 1, "sickle": 1, "spade": 2, "mop": 2,
    "antitoxin kit": 0, "disguise kit": 0, "lock picks": 0, "manacles": 0, "writing kit": 0, "reading lens": 0, "telescope": 0,
    "hammer": 0, "chisel": 0, "comb": 0, "ear pick": 0, "fish hooks": 0, "hand mirror": 0, "key": 0, "nails": 0, "quill pen": 0
};

function getTrueEncumbrance(name) {
    if (!name) return 0;
    const clean = name.toLowerCase().trim();
    let match = serverTrappingsCatalog.find(t => t.name.toLowerCase() === clean);
    if (match && match.encumbrance !== undefined) return parseFloat(match.encumbrance);
    
    match = serverArmourCatalog.find(a => a.name.toLowerCase() === clean);
    if (match && match.encumbrance !== undefined) return parseFloat(match.encumbrance);
    
    match = serverWeaponsCatalog.find(w => w.name.toLowerCase() === clean);
    if (match && match.encumbrance !== undefined) return parseFloat(match.encumbrance);

    if (WFRP_TRAPPING_ENC_LOOKUP[clean] !== undefined) return WFRP_TRAPPING_ENC_LOOKUP[clean];
    for (let k in WFRP_TRAPPING_ENC_LOOKUP) {
        if (clean.includes(k) || k.includes(clean)) return WFRP_TRAPPING_ENC_LOOKUP[k];
    }
    return 1;
}

function addTrappingRow(data = {}) {
    const tbody = document.getElementById('m-trappings-table-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    tr.style.background = '#fffbf4';

    const isEq = data.equipped !== undefined ? data.equipped : false;
    const name = data.name || (typeof data === 'string' ? data : '');
    let enc = data.enc !== undefined && data.enc !== null ? data.enc : getTrueEncumbrance(name);
    if (enc === 0 && name) enc = getTrueEncumbrance(name);
    const apDesc = data.ap_desc || getArmourDesc(name);

    tr.innerHTML = `
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <input type="checkbox" class="t-eq" ${isEq ? 'checked' : ''} onchange="autoDetectArmour(this)" style="width: 16px; height: 16px; cursor: pointer; accent-color: #7a1717;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="t-name" list="trappings-list" value="${name}" placeholder="Trapping Name" oninput="autoDetectArmour(this)" style="width:100%; border:none; background:transparent; font-size:13px; font-weight:bold; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <input type="number" class="t-enc" value="${enc}" oninput="calcArmourAndEncSummary()" style="width:45px; text-align:center; border:none; background:transparent; font-size:13px; font-weight:bold; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="t-ap-desc" value="${apDesc}" readonly placeholder="--" style="width:100%; border:none; background:transparent; font-size:11px; font-weight:bold; color:#7a1717;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <button type="button" onclick="this.closest('tr').remove(); calcArmourAndEncSummary();" style="background:#7a1717; color:#fff; border:none; font-size:10px; padding:2px 6px; cursor:pointer; border-radius:2px;">✖</button>
        </td>
    `;
    tbody.appendChild(tr);
    calcArmourAndEncSummary();
}

function addHirelingRow(data = {}) {
    const tbody = document.getElementById('m-hirelings-table-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    tr.style.background = '#fffbf4';

    const name = data.name || (typeof data === 'string' ? data : '');
    const dailyCost = data.daily_cost || '';
    const notes = data.notes || '';

    tr.innerHTML = `
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="h-name" list="hirelings-list" value="${name}" placeholder="Hireling Role" oninput="autoDetectHireling(this)" style="width:100%; border:none; background:transparent; font-size:13px; font-weight:bold; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <input type="text" class="h-daily" value="${dailyCost}" placeholder="--" style="width:100%; text-align:center; border:none; background:transparent; font-size:13px; font-weight:bold; color:#1c130b;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961;">
            <input type="text" class="h-notes" value="${notes}" placeholder="--" style="width:100%; border:none; background:transparent; font-size:11px; font-weight:bold; color:#7a1717;">
        </td>
        <td style="padding: 4px; border: 1px solid #8b7961; text-align:center;">
            <button type="button" onclick="this.closest('tr').remove();" style="background:#7a1717; color:#fff; border:none; font-size:10px; padding:2px 6px; cursor:pointer; border-radius:2px;">✖</button>
        </td>
    `;
    tbody.appendChild(tr);
}

function autoDetectHireling(input) {
    const tr = input.closest('tr');
    if (!tr) return;
    const name = input.value.trim();
    const cleanName = name.toLowerCase();
    
    let match = serverHirelingsCatalog.find(h => h.name.toLowerCase() === cleanName);
    if (match) {
        const dailyInput = tr.querySelector('.h-daily');
        if (dailyInput && !dailyInput.value) dailyInput.value = match.daily_cost;
        const notesInput = tr.querySelector('.h-notes');
        if (notesInput && !notesInput.value) notesInput.value = match.notes;
    }
}


function getArmourDesc(name) {
    if (!name) return '';
    const clean = name.toLowerCase();
    
    // First try the dynamic API catalog
    let match = serverArmourCatalog.find(a => clean.includes(a.name.toLowerCase()));
    if (match) return `${match.locations} (${match.ap} AP)`;
    
    // Fallback to hardcoded list
    match = WFRP_ARMOUR_CATALOG.find(a => clean.includes(a.name));
    return match ? match.desc : '';
}

function isItemWorn(cleanName, match) {
    // Weapons NEVER drop encumbrance when equipped — they always contribute full encumbrance
    if (serverWeaponsCatalog.some(w => w.name.toLowerCase() === cleanName || cleanName.includes(w.name.toLowerCase()))) {
        return false;
    }
    const knownWeaponKeywords = ["sword", "dagger", "bow", "crossbow", "spear", "halberd", "axe", "hammer", "flail", "pistol", "blunderbuss", "rapier", "hand weapon", "mace", "staff", "shield", "buckler"];
    if (knownWeaponKeywords.some(kw => cleanName.includes(kw))) {
        return false;
    }

    if (match) {
        if (match.is_worn === 1 || match.is_worn === true) return true;
        if (match.category === 'Clothing and Accessories' || match.category === 'Armour') return true;
        if (serverArmourCatalog.some(a => a.name.toLowerCase() === cleanName)) return true;
    }
    const knownWornKeywords = [
        "boots", "cloak", "clothing", "coat", "costume", "courtly garb", "gloves", "hood", "mask",
        "jewellery", "amulet", "ring", "robes", "shoes", "uniform", "leather jack", "mail shirt",
        "cuirass", "helm", "greaves", "vambraces", "breastplate", "armour", "backpack", "sling bag"
    ];
    return knownWornKeywords.some(kw => cleanName.includes(kw));
}

function autoDetectArmour(input) {
    const tr = input.closest('tr');
    if (!tr) return;
    const nameInput = tr.querySelector('.t-name');
    const name = nameInput ? nameInput.value.trim() : '';
    const cleanName = name.toLowerCase();
    const eqInp = tr.querySelector('.t-eq');
    const isEq = eqInp ? eqInp.checked : false;

    const encInput = tr.querySelector('.t-enc');
    if (encInput && cleanName) {
        let match = serverTrappingsCatalog.find(t => t.name.toLowerCase() === cleanName) || 
                    serverArmourCatalog.find(a => a.name.toLowerCase() === cleanName) ||
                    serverWeaponsCatalog.find(w => w.name.toLowerCase() === cleanName);
        
        let baseEnc = match && match.encumbrance !== undefined ? parseFloat(match.encumbrance) : (WFRP_TRAPPING_ENC_LOOKUP[cleanName] !== undefined ? WFRP_TRAPPING_ENC_LOOKUP[cleanName] : 1);
        if (isNaN(baseEnc)) baseEnc = 1;

        let worn = isItemWorn(cleanName, match);
        // Rule: Worn items (armour, clothing, jewellery, etc.) drop Encumbrance by 1 when equipped/worn (min 0)
        let effectiveEnc = (isEq && worn) ? Math.max(0, baseEnc - 1) : baseEnc;
        encInput.value = effectiveEnc;
    }

    const descInput = tr.querySelector('.t-ap-desc');
    const desc = getArmourDesc(name);
    if (descInput) {
        descInput.value = desc;
    }
    calcArmourAndEncSummary();
}





// ── WFRP 4E CORE SPELL & PRAYER LIBRARY ──────────────────────────────────────
const WFRP_SPELL_LIBRARY = {
    petty: [
        { name: "Bearings", tn: "0", range: "Touch", target: "You", duration: "Instant", effect: "You immediately know true north." },
        { name: "Cauterise", tn: "0", range: "Touch", target: "1 Target", duration: "Instant", effect: "Stops 1 Bleeding Condition; target takes 1 Wound." },
        { name: "Dart", tn: "0", range: "24 yards", target: "1 Target", duration: "Instant", effect: "Magic Missile dealing +SB+0 Damage." },
        { name: "Drain", tn: "0", range: "Touch", target: "1 Target", duration: "Instant", effect: "Removes 1 Advantage from target." },
        { name: "Eavesdrop", tn: "0", range: "12 yards", target: "1 Area", duration: "Init Rating mins", effect: "Hear whispers clearly over long distances." },
        { name: "Light", tn: "0", range: "Touch", target: "1 Object", duration: "WP Rating mins", effect: "Object glows as bright as a torch." },
        { name: "Marsh Light", tn: "0", range: "24 yards", target: "1 Point", duration: "WP Rating mins", effect: "Creates a floating orb of light to confuse." },
        { name: "Open", tn: "0", range: "Touch", target: "1 Lock", duration: "Instant", effect: "Unlocks non-magical padlocks or latches." },
        { name: "Purify Water", tn: "0", range: "Touch", target: "1 Gallon", duration: "Instant", effect: "Removes poison, rot, and foulness from liquid." },
        { name: "Shock", tn: "0", range: "Touch", target: "1 Target", duration: "Instant", effect: "Touch attack dealing +SB+0 Damage ignoring Armour." },
        { name: "Sleep", tn: "0", range: "Touch", target: "1 Target", duration: "WP Bonus rounds", effect: "Target falls asleep if failing Willpower Test." },
        { name: "Spring", tn: "0", range: "Touch", target: "1 Object", duration: "Instant", effect: "Repairs minor tears in clothing or leather." }
    ],
    arcane: [
        { name: "Bolt", tn: "4", range: "24 yards", target: "1 Target", duration: "Instant", effect: "Magic Missile dealing +SB+4 Damage." },
        { name: "Breath", tn: "5", range: "12 yards", target: "Cone Template", duration: "Instant", effect: "Magic Missile dealing +SB+5 Damage to all in cone." },
        { name: "Bridge", tn: "6", range: "24 yards", target: "1 Bridge", duration: "WP Bonus mins", effect: "Summons a glowing magical bridge over gaps." },
        { name: "Coruscating Bolt", tn: "6", range: "48 yards", target: "1 Target", duration: "Instant", effect: "Magic Missile +SB+6 Damage, Blinds target for 1 round." },
        { name: "Dome", tn: "5", range: "Touch", target: "6 yd radius", duration: "WP Bonus rounds", effect: "Protective dome blocking non-magical ranged attacks." },
        { name: "Entangle", tn: "5", range: "12 yards", target: "1 Target", duration: "WP Bonus rounds", effect: "Target gains Entangled condition." },
        { name: "Flight", tn: "7", range: "Touch", target: "1 Target", duration: "WP Bonus mins", effect: "Target gains Flight (Movement 4)." },
        { name: "Magic Shield", tn: "4", range: "Touch", target: "You", duration: "WP Bonus rounds", effect: "Dispel tests gain +2 Success Levels." },
        { name: "Push", tn: "3", range: "12 yards", target: "1 Target", duration: "Instant", effect: "Pushes target WP Bonus yards away and knocks Prone." },
        { name: "Teleport", tn: "8", range: "You", target: "You", duration: "Instant", effect: "Instantly teleport up to WP Rating yards." }
    ],
    blessings: [
        { name: "Blessing of Battle", tn: "3", range: "6 yards", target: "1 Target", duration: "1 round", effect: "Target gains +10 Weapon Skill on next melee attack." },
        { name: "Blessing of Courage", tn: "3", range: "6 yards", target: "1 Target", duration: "1 round", effect: "Target becomes immune to Fear and Terror." },
        { name: "Blessing of Healing", tn: "3", range: "Touch", target: "1 Target", duration: "Instant", effect: "Heals Wounds equal to your Willpower Bonus." },
        { name: "Blessing of Might", tn: "3", range: "Touch", target: "1 Target", duration: "1 round", effect: "Target gains +10 Strength." },
        { name: "Blessing of Protection", tn: "3", range: "Touch", target: "1 Target", duration: "1 round", effect: "Target gains +1 AP on all body locations." },
        { name: "Blessing of Wisdom", tn: "3", range: "Touch", target: "1 Target", duration: "1 round", effect: "Target gains +10 Intelligence on next lore test." }
    ],
    miracles: [
        { name: "Sigmar's Hammer (Sigmar)", tn: "7", range: "You", target: "You", duration: "WP Bonus rounds", effect: "Melee weapon deals +SB+8 Damage with Ablaze." },
        { name: "Shield of Faith (Sigmar)", tn: "6", range: "Touch", target: "1 Target", duration: "WP Bonus rounds", effect: "Target gains +4 AP against Magic and Daemonic attacks." },
        { name: "Howl of Ulric (Ulric)", tn: "5", range: "You", target: "12 yd radius", duration: "Instant", effect: "Enemies in radius test WP or gain Broken condition." },
        { name: "Tide's Fury (Manann)", tn: "6", range: "18 yards", target: "1 Area", duration: "Instant", effect: "Knocks targets Prone dealing +SB+5 Damage." },
        { name: "Shallya's Touch (Shallya)", tn: "6", range: "Touch", target: "1 Target", duration: "Instant", effect: "Cures all non-magical diseases and heals 2x WPB Wounds." },
        { name: "Ranald's Luck (Ranald)", tn: "4", range: "Touch", target: "1 Target", duration: "1 round", effect: "Target may re-roll any single failed d100 test." }
    ]
};

let currentSpellCategory = 'petty';

function openSpellSelectModal() {
    const careerInp = document.getElementById('m-char-career');
    const career = careerInp ? careerInp.value.toLowerCase() : '';
    if (career.includes('priest') || career.includes('flagellant') || career.includes('nun') || career.includes('monk')) {
        currentSpellCategory = 'blessings';
    } else if (career.includes('wizard') || career.includes('witch') || career.includes('hedge') || career.includes('sorcerer')) {
        currentSpellCategory = 'arcane';
    } else {
        currentSpellCategory = 'petty';
    }
    switchSpellCategory(currentSpellCategory);
    const modal = document.getElementById('spell-select-modal');
    if (modal) modal.style.display = 'flex';
}

function closeSpellSelectModal() {
    const modal = document.getElementById('spell-select-modal');
    if (modal) modal.style.display = 'none';
}

function switchSpellCategory(cat) {
    currentSpellCategory = cat;
    document.querySelectorAll('.spell-cat-tab').forEach(btn => {
        btn.classList.remove('active');
        btn.style.background = '#faf4e8';
        btn.style.color = '#1c130b';
    });
    const activeTab = document.getElementById(`sp-tab-${cat}`);
    if (activeTab) {
        activeTab.classList.add('active');
        activeTab.style.background = '#7a1717';
        activeTab.style.color = '#fff';
    }
    filterSpellList();
}

function filterSpellList() {
    const container = document.getElementById('spell-list-container');
    if (!container) return;
    const searchInp = document.getElementById('spell-search-inp');
    const q = searchInp ? searchInp.value.toLowerCase().trim() : '';

    const spellList = WFRP_SPELL_LIBRARY[currentSpellCategory] || [];
    container.innerHTML = '';

    const filtered = spellList.filter(s => s.name.toLowerCase().includes(q) || s.effect.toLowerCase().includes(q));

    if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: span 2; text-align: center; color: #666; font-style: italic; padding: 20px;">No matching spells found in this category.</div>`;
        return;
    }

    filtered.forEach(s => {
        const card = document.createElement('div');
        card.style.background = '#fffbf4';
        card.style.border = '1.5px solid #8b7961';
        card.style.borderRadius = '4px';
        card.style.padding = '10px 12px';
        card.style.cursor = 'pointer';
        card.style.transition = 'all 0.15s ease';
        card.onmouseover = () => { card.style.background = '#fcefdc'; card.style.borderColor = '#7a1717'; };
        card.onmouseout = () => { card.style.background = '#fffbf4'; card.style.borderColor = '#8b7961'; };
        card.onclick = () => selectSpell(s);

        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-family: var(--font-title); font-weight: bold; color: #7a1717; font-size: 14px;">${s.name}</span>
                <span style="background: #7a1717; color: #fff; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 3px;">TN ${s.tn}</span>
            </div>
            <div style="font-size: 11px; color: #555; margin-bottom: 6px;">
                <strong>Range:</strong> ${s.range} | <strong>Target:</strong> ${s.target} | <strong>Duration:</strong> ${s.duration}
            </div>
            <div style="font-size: 12px; color: #1c130b; line-height: 1.3;">
                ${s.effect}
            </div>
        `;
        container.appendChild(card);
    });
}

function selectSpell(s) {
    addSpellRow(s);
    closeSpellSelectModal();
}

function selectBlankSpell() {
    addSpellRow({});
    closeSpellSelectModal();
}


// ── WFRP 4E WEAPON QUALITIES & FLAWS ENGINE ─────────────────────────────────
const WFRP_QUALITIES = [
    { name: "Accurate", desc: "+10 BS to hit when aiming" },
    { name: "Damaging", desc: "Uses highest of d10 roll or SL for damage" },
    { name: "Fast", desc: "Opponents cannot use Shields or Fast to parry" },
    { name: "Hack", desc: "Inflicts +1 SL damage against shields/armour" },
    { name: "Impale", desc: "Criticals inflict Impaled condition (+1 Bleeding)" },
    { name: "Penetrating", desc: "Ignores 1 AP of target armour" },
    { name: "Precise", desc: "+1 Success Level on successful hit" },
    { name: "Pummel", desc: "Criticals inflict Stun condition" },
    { name: "Shield 1", desc: "+1 AP on arm/body, parries ranged attacks" },
    { name: "Shield 2", desc: "+2 AP on arm/body, parries ranged attacks" },
    { name: "Trap", desc: "Disarm/trap enemy weapon on successful parry" },
    { name: "Unbalanced", desc: "-10 to parry with this weapon" }
];

const WFRP_FLAWS = [
    { name: "Dangerous", desc: "Fumble on any double roll" },
    { name: "Inaccurate", desc: "-10 to hit targets" },
    { name: "Slow", desc: "Always strikes last in Initiative order" },
    { name: "Tiring", desc: "User suffers Fatigued condition after WP Bonus rounds" },
    { name: "Undamaging", desc: "Strength Bonus (SB) is not added to damage" }
];

let activeQualitiesInput = null;

function openQualitiesModal(inputEl) {
    activeQualitiesInput = inputEl;
    const currentVal = inputEl ? inputEl.value : '';

    const qContainer = document.getElementById('qualities-checkbox-list');
    const fContainer = document.getElementById('flaws-checkbox-list');

    if (qContainer) {
        qContainer.innerHTML = WFRP_QUALITIES.map(q => `
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                <input type="checkbox" class="q-cb" value="${q.name}" ${currentVal.includes(q.name) ? 'checked' : ''} style="accent-color: #1c521c;">
                <strong>${q.name}:</strong> <span style="color: #444;">${q.desc}</span>
            </label>
        `).join('');
    }

    if (fContainer) {
        fContainer.innerHTML = WFRP_FLAWS.map(f => `
            <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
                <input type="checkbox" class="f-cb" value="${f.name}" ${currentVal.includes(f.name) ? 'checked' : ''} style="accent-color: #7a1717;">
                <strong>${f.name}:</strong> <span style="color: #444;">${f.desc}</span>
            </label>
        `).join('');
    }

    const modal = document.getElementById('qualities-select-modal');
    if (modal) modal.style.display = 'flex';
}

function closeQualitiesModal() {
    const modal = document.getElementById('qualities-select-modal');
    if (modal) modal.style.display = 'none';
}

function applySelectedQualities() {
    if (!activeQualitiesInput) return;
    const selected = [];

    document.querySelectorAll('.q-cb:checked, .f-cb:checked').forEach(cb => {
        selected.push(cb.value);
    });

    const customInp = document.getElementById('custom-quality-input');
    if (customInp && customInp.value.trim()) {
        selected.push(customInp.value.trim());
        customInp.value = '';
    }

    activeQualitiesInput.value = selected.join(', ');
    closeQualitiesModal();
}

function parseArmourLocations(locStr) {
    if (!locStr) return [];
    if (Array.isArray(locStr)) return locStr;
    const s = String(locStr).toLowerCase();
    const locs = [];
    if (s.includes('head')) locs.push('head');
    if (s.includes('body')) locs.push('body');
    if (s.includes('arm')) { locs.push('l_arm'); locs.push('r_arm'); }
    if (s.includes('leg')) { locs.push('l_leg'); locs.push('r_leg'); }
    if (s.includes('shield')) locs.push('shield');
    return locs;
}

function calcArmourAndEncSummary() {
    // 1. Sync Weapons Table FIRST so weapon rows exist before measuring wEncSum
    syncWeaponsFromTrappings();

    let totals = { head: 0, body: 0, l_arm: 0, r_arm: 0, l_leg: 0, r_leg: 0, shield: 0 };
    let aEncSum = 0;
    let tEncSum = 0;
    let wEncSum = 0;

    const knownWeaponsFallback = [
        "hand weapon", "short sword", "dagger", "sword", "broadsword", "rapier", "main gauche",
        "bow", "longbow", "crossbow", "halberd", "spear", "flail", "warhammer", "axe", "staff",
        "shield", "buckler", "pistol", "blunderbuss", "greatsword", "two-handed", "hammer", "mace"
    ];

    // 2. Calculate Weapons Encumbrance from Weapons Table
    document.querySelectorAll('#m-weapons-table-body tr .w-enc').forEach(inp => { 
        wEncSum += parseFloat(inp.value) || 0; 
    });

    // 3. Process Trappings Table Rows
    document.querySelectorAll('#m-trappings-table-body tr').forEach(tr => {
        const eqInp = tr.querySelector('.t-eq');
        const nameInp = tr.querySelector('.t-name');
        const encInp = tr.querySelector('.t-enc');
        const isEq = eqInp ? eqInp.checked : false;
        const name = nameInp ? nameInp.value.trim() : '';
        const cleanName = name.toLowerCase();
        const enc = parseFloat(encInp ? encInp.value : 0) || 0;

        if (!cleanName) return;

        let isWeapon = serverWeaponsCatalog.some(w => w.name.toLowerCase() === cleanName || cleanName.includes(w.name.toLowerCase())) ||
                       knownWeaponsFallback.some(kw => cleanName.includes(kw));

        let matchArmour = serverArmourCatalog.find(a => cleanName.includes(a.name.toLowerCase())) || 
                          WFRP_ARMOUR_CATALOG.find(a => cleanName.includes(a.name.toLowerCase()));

        const locDescInp = tr.querySelector('.t-ap-desc');
        const locDesc = locDescInp ? locDescInp.value.trim() : '';

        if (isEq && (matchArmour || locDesc)) {
            aEncSum += enc;
            
            let apVal = matchArmour && matchArmour.ap !== undefined ? parseFloat(matchArmour.ap) : 1;
            if (isNaN(apVal)) apVal = 1;

            let rawLocations = matchArmour ? (matchArmour.locations || matchArmour.locs || locDesc) : locDesc;
            let parsedLocs = parseArmourLocations(rawLocations);

            parsedLocs.forEach(loc => {
                if (totals[loc] !== undefined) totals[loc] += apVal;
            });
        }

        // Encumbrance breakdown rules:
        // - Equipped Weapons are synced to Weapons Table and counted in wEncSum.
        // - Unequipped Weapons in inventory are counted in tEncSum.
        // - Equipped Armour is counted in aEncSum.
        // - General trappings (or unequipped armour) go into tEncSum.
        if (isWeapon) {
            if (!isEq) {
                tEncSum += enc;
            }
        } else if (isEq && (matchArmour || locDesc)) {
            // Equipped armour is counted in aEncSum
        } else {
            tEncSum += enc;
        }
    });

    // Update Armour Diagram AP Inputs
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    setVal('m-arm-head', totals.head);
    setVal('m-arm-body', totals.body);
    setVal('m-arm-larm', totals.l_arm);
    setVal('m-arm-rarm', totals.r_arm);
    setVal('m-arm-lleg', totals.l_leg);
    setVal('m-arm-rleg', totals.r_leg);
    setVal('m-arm-shield', totals.shield);

    // Update Encumbrance Summary
    setVal('m-enc-weapons', wEncSum);
    setVal('m-enc-armour', aEncSum);
    setVal('m-enc-trappings', tEncSum);

    const totalEnc = wEncSum + aEncSum + tEncSum;
    setVal('m-enc-curr', totalEnc);
}

// ── SYNC WEAPONS TABLE FROM EQUIPPED TRAPPINGS ────────────────────────────────
function syncWeaponsFromTrappings() {
    const knownWeaponsFallback = [
        "hand weapon", "short sword", "dagger", "sword", "broadsword", "rapier", "main gauche",
        "bow", "longbow", "crossbow", "halberd", "spear", "flail", "warhammer", "axe", "staff",
        "shield", "buckler", "pistol", "blunderbuss", "greatsword", "two-handed", "hammer", "mace"
    ];

    // 1. Gather all currently EQUIPPED weapon instances from Trappings table
    const equippedWeapons = [];
    document.querySelectorAll('#m-trappings-table-body tr').forEach((tr, trIdx) => {
        const eqInp = tr.querySelector('.t-eq');
        const nameInp = tr.querySelector('.t-name');
        const isEq = eqInp ? eqInp.checked : false;
        const rawName = nameInp ? nameInp.value.trim() : '';
        if (!isEq || !rawName) return;

        const cleanName = rawName.toLowerCase();

        // Check against serverWeaponsCatalog or fallback known list
        let catalogMatch = serverWeaponsCatalog.find(w => w.name.toLowerCase() === cleanName || cleanName.includes(w.name.toLowerCase()));
        const isKnown = knownWeaponsFallback.some(w => cleanName.includes(w));

        if (catalogMatch || isKnown) {
            let baseName = catalogMatch ? catalogMatch.name : "Hand Weapon";
            if (!catalogMatch) {
                if (cleanName.includes("dagger")) baseName = "Dagger";
                else if (cleanName.includes("bow")) baseName = "Bow";
                else if (cleanName.includes("shield")) baseName = "Shield";
                else if (cleanName.includes("halberd")) baseName = "Halberd";
                else if (cleanName.includes("spear")) baseName = "Spear";
                else if (cleanName.includes("pistol")) baseName = "Pistol";
                else if (cleanName.includes("axe")) baseName = "Axe";
            }

            equippedWeapons.push({
                trappingRowIdx: trIdx,
                rawName: rawName,
                baseName: baseName,
                group: catalogMatch ? (catalogMatch.group_name || "Basic") : "Basic",
                enc: catalogMatch ? (catalogMatch.encumbrance !== undefined ? catalogMatch.encumbrance : 1) : 1,
                range: catalogMatch ? (catalogMatch.range || "Melee") : "Melee",
                damage: catalogMatch ? (catalogMatch.damage || "+SB+4") : "+SB+4",
                qualities: catalogMatch ? (catalogMatch.qualities || "") : ""
            });
        }
    });

    // 2. Get existing rows in Weapons Table
    const existingWeaponRows = Array.from(document.querySelectorAll('#m-weapons-table-body tr'));
    const matchedExistingRows = new Set();

    equippedWeapons.forEach(eqWep => {
        // Try to find an unmatched existing row in weapons table that matches this equipped weapon
        let matchedRow = existingWeaponRows.find(wTr => {
            if (matchedExistingRows.has(wTr)) return false;
            const wType = (wTr.querySelector('.w-type')?.value || '').trim().toLowerCase();
            const wName = (wTr.querySelector('.w-name')?.value || '').trim().toLowerCase();
            const srcKey = (wTr.getAttribute('data-source-key') || '').trim().toLowerCase();
            const cleanEqName = eqWep.rawName.toLowerCase();
            const cleanBaseName = eqWep.baseName.toLowerCase();

            return (wType === cleanEqName || wName === cleanEqName || srcKey === cleanEqName || wName === cleanBaseName || wType.includes(cleanBaseName));
        });

        if (matchedRow) {
            matchedExistingRows.add(matchedRow);
        } else {
            // No existing row found for this equipped weapon instance -> Add new row!
            addWeaponRow({
                name: eqWep.baseName,
                type: eqWep.rawName !== eqWep.baseName ? eqWep.rawName : "",
                group: eqWep.group,
                enc: eqWep.enc,
                range: eqWep.range,
                damage: eqWep.damage,
                qualities: eqWep.qualities,
                source_key: eqWep.rawName.toLowerCase()
            });
        }
    });

    // 3. Remove any auto-synced weapon rows that are no longer matched to an equipped trapping
    existingWeaponRows.forEach(wTr => {
        if (!matchedExistingRows.has(wTr)) {
            const wType = (wTr.querySelector('.w-type')?.value || '').trim();
            const srcKey = (wTr.getAttribute('data-source-key') || '').trim().toLowerCase();
            // Only remove if it has no user-customized Specific Name (wType is empty)
            if (srcKey && !wType) {
                wTr.remove();
            }
        }
    });
}


// ── SAVE HOMEPAGE PARTY AMBITIONS ───────────────────────────────────────────
async function savePartyAmbitions() {
    const btn = document.getElementById('save-party-ambitions-btn');
    const shortVal = (document.getElementById('c-amb-short-inp')?.value || '').trim();
    const longVal = (document.getElementById('c-amb-long-inp')?.value || '').trim();

    if (btn) {
        btn.innerText = '⏳ SAVING...';
        btn.disabled = true;
    }

    try {
        const resp = await fetch('/api/campaign/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                party_ambition_short: shortVal,
                party_ambition_long: longVal
            })
        });
        const res = await resp.json();
        if (res.ok && res.active_campaign) {
            currentCampaign = res.active_campaign;
            if (btn) {
                btn.innerText = '✅ SAVED!';
                btn.style.background = '#1c521c';
                setTimeout(() => {
                    btn.innerText = '💾 SAVE PARTY AMBITIONS';
                    btn.style.background = '#7a1717';
                    btn.disabled = false;
                }, 1500);
            }
        } else {
            alert('Failed to save party ambitions: ' + (res.error || 'Unknown error'));
            if (btn) { btn.innerText = '💾 SAVE PARTY AMBITIONS'; btn.disabled = false; }
        }
    } catch (err) {
        console.error('Error saving party ambitions:', err);
        if (btn) { btn.innerText = '💾 SAVE PARTY AMBITIONS'; btn.disabled = false; }
    }
}


// ── REUSABLE UNIVERSAL SAVE VISUAL FEEDBACK ENGINE ────────────────────────────
async function executeWithSaveFeedback(btnOrId, asyncActionFn, originalText = '💾 SAVE', successText = '✅ SAVED!') {
    const btn = typeof btnOrId === 'string' ? document.getElementById(btnOrId) : btnOrId;
    let oldBg = '';
    if (btn) {
        oldBg = btn.style.background || '';
        btn.innerText = '⏳ SAVING...';
        btn.disabled = true;
    }
    try {
        const success = await asyncActionFn();
        if (success !== false && btn) {
            btn.innerText = successText;
            btn.style.background = '#1c521c';
            await new Promise(r => setTimeout(r, 1200));
            btn.innerText = originalText;
            btn.style.background = oldBg;
            btn.disabled = false;
        } else if (btn) {
            btn.innerText = originalText;
            btn.style.background = oldBg;
            btn.disabled = false;
        }
        return success;
    } catch (err) {
        console.error("Save execution error:", err);
        if (btn) {
            btn.innerText = originalText;
            btn.style.background = oldBg;
            btn.disabled = false;
        }
        return false;
    }
}


// ── COGITATOR MEMORY MANAGER CONTROLLER ───────────────────────────────────────
let _memoryData = { longterm: [], shortterm: [] };

async function fetchMemories() {
    try {
        const res = await fetch('/api/memory');
        const data = await res.json();
        if (data.ok) {
            _memoryData = data;
            renderMemories();
        } else {
            console.error("fetchMemories error:", data.error);
        }
    } catch(e) {
        console.error("fetchMemories exception:", e);
    }
}

function renderMemories() {
    const ltList = document.getElementById('longterm-memory-list');
    const stList = document.getElementById('shortterm-memory-list');
    const ltCount = document.getElementById('longterm-count');
    const stCount = document.getElementById('shortterm-count');

    if (ltCount) ltCount.textContent = `[ ${_memoryData.longterm.length} ]`;
    if (stCount) stCount.textContent = `[ ${_memoryData.shortterm.length} ]`;

    if (ltList) {
        if (_memoryData.longterm.length === 0) {
            ltList.innerHTML = `<div style="font-size: 12px; opacity: 0.6; padding: 8px;">No explicit long-term facts stored.</div>`;
        } else {
            ltList.innerHTML = _memoryData.longterm.map((fact, idx) => `
                <div style="background: rgba(0, 43, 17, 0.4); border: 1px solid var(--border-color, #00441b); border-radius: 3px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <span id="lt-text-${idx}" style="font-size: 12px; flex: 1; word-break: break-word;">${escapeHtml(fact)}</span>
                    <div id="lt-actions-${idx}" style="display: flex; gap: 6px;">
                        <button onclick="editMemoryItem(${idx}, true)" style="background: #003314; color: var(--bright-green, #00ff66); border: 1px solid var(--border-color, #00441b); padding: 3px 8px; font-size: 11px; cursor: pointer; border-radius: 3px;">✏️ EDIT</button>
                        <button onclick="deleteMemoryFact('${escapeJsString(fact)}', true)" style="background: #330000; color: #ff6666; border: 1px solid #660000; padding: 3px 8px; font-size: 11px; cursor: pointer; border-radius: 3px;">🗑️ DELETE</button>
                    </div>
                </div>
            `).join('');
        }
    }

    if (stList) {
        if (_memoryData.shortterm.length === 0) {
            stList.innerHTML = `<div style="font-size: 12px; opacity: 0.6; padding: 8px;">No auto-extracted world facts stored.</div>`;
        } else {
            stList.innerHTML = _memoryData.shortterm.map((fact, idx) => `
                <div style="background: rgba(0, 30, 45, 0.4); border: 1px solid #005577; border-radius: 3px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                    <span id="st-text-${idx}" style="font-size: 12px; flex: 1; word-break: break-word; color: #b3ecff;">${escapeHtml(fact)}</span>
                    <div id="st-actions-${idx}" style="display: flex; gap: 6px;">
                        <button onclick="editMemoryItem(${idx}, false)" style="background: #002233; color: #00ccff; border: 1px solid #005577; padding: 3px 8px; font-size: 11px; cursor: pointer; border-radius: 3px;">✏️ EDIT</button>
                        <button onclick="deleteMemoryFact('${escapeJsString(fact)}', false)" style="background: #330000; color: #ff6666; border: 1px solid #660000; padding: 3px 8px; font-size: 11px; cursor: pointer; border-radius: 3px;">🗑️ DELETE</button>
                    </div>
                </div>
            `).join('');
        }
    }
}

function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeJsString(str) {
    return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

async function addMemoryFact() {
    const input = document.getElementById('new-memory-input');
    if (!input) return;
    const fact = input.value.trim();
    if (!fact) return;
    try {
        const res = await fetch('/api/memory/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fact, longterm: true })
        });
        const data = await res.json();
        if (data.ok) {
            input.value = '';
            _memoryData = data;
            renderMemories();
        } else {
            alert('Failed to add memory: ' + data.error);
        }
    } catch(e) {
        console.error("addMemoryFact exception:", e);
    }
}

function editMemoryItem(idx, isLongterm) {
    const prefix = isLongterm ? 'lt' : 'st';
    const textEl = document.getElementById(`${prefix}-text-${idx}`);
    const actionsEl = document.getElementById(`${prefix}-actions-${idx}`);
    if (!textEl || !actionsEl) return;

    const currentFact = isLongterm ? _memoryData.longterm[idx] : _memoryData.shortterm[idx];
    textEl.innerHTML = `<input type="text" id="${prefix}-edit-input-${idx}" value="${escapeHtml(currentFact)}" style="width: 100%; background: #001206; border: 1px solid var(--border-color, #00441b); color: #fff; padding: 4px 8px; font-family: monospace; font-size: 12px; border-radius: 3px;" onkeydown="if(event.key==='Enter') saveMemoryItemEdit(${idx}, ${isLongterm})">`;
    actionsEl.innerHTML = `
        <button onclick="saveMemoryItemEdit(${idx}, ${isLongterm})" style="background: var(--bright-green, #00ff66); color: #000; border: none; padding: 3px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border-radius: 3px;">💾 SAVE</button>
        <button onclick="renderMemories()" style="background: #333; color: #ccc; border: none; padding: 3px 8px; font-size: 11px; cursor: pointer; border-radius: 3px;">CANCEL</button>
    `;
}

async function saveMemoryItemEdit(idx, isLongterm) {
    const prefix = isLongterm ? 'lt' : 'st';
    const inputEl = document.getElementById(`${prefix}-edit-input-${idx}`);
    if (!inputEl) return;
    const newFact = inputEl.value.trim();
    const oldFact = isLongterm ? _memoryData.longterm[idx] : _memoryData.shortterm[idx];
    if (!newFact || newFact === oldFact) {
        renderMemories();
        return;
    }
    try {
        const res = await fetch('/api/memory/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_fact: oldFact, new_fact: newFact, longterm: isLongterm })
        });
        const data = await res.json();
        if (data.ok) {
            _memoryData = data;
            renderMemories();
        } else {
            alert('Failed to update memory: ' + data.error);
        }
    } catch(e) {
        console.error("saveMemoryItemEdit exception:", e);
    }
}

async function deleteMemoryFact(fact, isLongterm) {
    if (!confirm(`Are you sure you want to erase this fact?\n\n"${fact}"`)) return;
    try {
        const res = await fetch('/api/memory/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fact, longterm: isLongterm })
        });
        const data = await res.json();
        if (data.ok) {
            _memoryData = data;
            renderMemories();
        } else {
            alert('Failed to delete memory: ' + data.error);
        }
    } catch(e) {
        console.error("deleteMemoryFact exception:", e);
    }
}
