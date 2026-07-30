
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

        let webAudioEnabled = true;
        let lastAudioId = 0;
        let currentAudioObj = null;

        function toggleWebAudio() {
            webAudioEnabled = !webAudioEnabled;
            const btn = document.getElementById('web-audio-btn');
            if (webAudioEnabled) {
                btn.innerText = '🔊 WEB AUDIO: ENABLED';
                btn.style.color = 'var(--bright-green)';
                const silentAudio = new Audio();
                silentAudio.play().catch(() => {});
            } else {
                btn.innerText = '🔇 WEB AUDIO: DISABLED';
                btn.style.color = 'var(--dim-green)';
                if (currentAudioObj) {
                    currentAudioObj.pause();
                }
            }
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
                if (elGame && data.active_game) elGame.innerText = String(data.active_game).toUpperCase();

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

                // Update RAM pie
                const ramFloat = parseFloat(data.ram) || 0;
                const ramPie = document.getElementById('ram-pie');
                const ramValEl = document.getElementById('ram-val');
                if (ramValEl && data.ram) ramValEl.innerText = String(data.ram);
                if (ramPie) ramPie.setAttribute('stroke-dasharray', `${Math.min(100, Math.max(0, ramFloat))}, 100`);

                // Update STORAGE pie
                const storageFloat = parseFloat(data.storage) || 0;
                const storagePie = document.getElementById('storage-pie');
                const storageValEl = document.getElementById('storage-val');
                if (storageValEl && data.storage) storageValEl.innerText = String(data.storage);
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
                    if (scSelect.options.length <= 1) {
                        scSelect.innerHTML = '<option value="">-- SELECT SCREENSAVER --</option>';
                        data.screensavers.forEach(s => {
                            const opt = document.createElement('option');
                            opt.value = s;
                            opt.innerText = String(s).replace(/_/g, ' ').toUpperCase();
                            scSelect.appendChild(opt);
                        });
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
                        camStream.src = '/api/camera_frame.jpg?t=' + Date.now();
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

                // Update ocular eye display frame
                const eyeStream = document.getElementById('eye-stream');
                if (eyeStream) {
                    eyeStream.src = '/api/ocular_frame.jpg?t=' + Date.now();
                }


            } catch (err) {
                console.error("Error fetching state:", err);
                const errDiv = document.createElement('div');
                errDiv.style.cssText = 'position:fixed; top:160px; left:0; width:100%; background:orange; color:black; z-index:9999; padding:20px; font-size:24px; font-weight:bold; word-wrap:break-word;';
                errDiv.innerText = 'FETCH STATE ERROR: ' + err.toString();
                document.body.appendChild(errDiv);
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
    