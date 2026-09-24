/* ==========================================================================
   SCAMTRAP AI // FRONTEND CLIENT SCRIPT
   ========================================================================== */

const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
let ws = null;

// DOM Elements
const statusPill = document.getElementById("status-pill");
const transcriptBox = document.getElementById("transcript-box");
const manualInput = document.getElementById("manual-input");
const sendBtn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const clearFeedBtn = document.getElementById("clear-feed-btn");
const copyIntelBtn = document.getElementById("copy-intel-btn");
const audioVisualizer = document.getElementById("audio-visualizer");
const callTimerEl = document.getElementById("call-timer");

// Telephony & Audio State
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let isRecording = false;
let callStartTime = null;
let callTimerInterval = null;
let latestIntelData = null;

// ==========================================================================
// 1. WEBSOCKET CONNECTION MANAGEMENT
// ==========================================================================

function connectWebSocket() {
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/audio`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    updateStatusPill("connected", "SYSTEM ONLINE // IDLE");
  };

  ws.onclose = () => {
    updateStatusPill("disconnected", "WS DISCONNECTED");
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
    updateStatusPill("disconnected", "CONNECTION ERROR");
  };

  ws.onmessage = handleIncomingMessage;
}

function updateStatusPill(state, text) {
  if (!statusPill) return;
  statusPill.className = `pill ${state}`;
  const textEl = statusPill.querySelector(".status-text") || statusPill;
  textEl.innerText = text;
}

// ==========================================================================
// 2. MICROPHONE CAPTURE (16kHz PCM Stream)
// ==========================================================================

async function startMicrophone() {
  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    mediaStream = await navigator.mediaDevices.getUserMedia({ 
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true
      } 
    });
    
    const source = audioContext.createMediaStreamSource(mediaStream);
    scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
      if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;
      const inputFloat32 = e.inputBuffer.getChannelData(0);
      const pcm16 = convertFloat32ToInt16(inputFloat32);
      ws.send(pcm16.buffer); // Stream binary PCM directly to server
    };

    source.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);

    startTimer();
    setVisualizerActive(true);
    updateStatusPill("recording-active", "STREAMING AUDIO // LIVE");
  } catch (err) {
    console.error("Microphone access denied or error:", err);
    showToast("Microphone access denied: " + err.message);
    isRecording = false;
    micBtn.classList.remove("recording");
    micBtn.querySelector("span").innerText = "Start Speaking (AssemblyAI Mic)";
  }
}

function convertFloat32ToInt16(float32Array) {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return int16Array;
}

function stopMicrophone() {
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
  }
  if (scriptProcessor) scriptProcessor.disconnect();
  if (audioContext && audioContext.state !== "closed") audioContext.close();
  setVisualizerActive(false);
  updateStatusPill("connected", "SYSTEM ONLINE // IDLE");
}

micBtn.onclick = async () => {
  if (!isRecording) {
    isRecording = true;
    micBtn.classList.add("recording");
    micBtn.querySelector("span").innerText = "Listening... (Click to Stop)";
    await startMicrophone();
  } else {
    isRecording = false;
    stopMicrophone();
    micBtn.classList.remove("recording");
    micBtn.querySelector("span").innerText = "Start Speaking (AssemblyAI Mic)";
  }
};

// ==========================================================================
// 3. TEXT FALLBACK & SIMULATION CHIPS
// ==========================================================================

sendBtn.onclick = () => {
  const text = manualInput.value.trim();
  if (text && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ manual_text: text }));
    manualInput.value = "";
    startTimer();
  }
};

manualInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendBtn.click();
  }
});

// Quick prompt simulation chips
document.querySelectorAll(".chip-btn").forEach(btn => {
  btn.onclick = () => {
    const promptText = btn.getAttribute("data-text");
    if (promptText && ws && ws.readyState === WebSocket.OPEN) {
      manualInput.value = promptText;
      sendBtn.click();
    }
  };
});

if (clearFeedBtn) {
  clearFeedBtn.onclick = () => {
    transcriptBox.innerHTML = `
      <div class="system-notice">
        <span class="notice-icon">ℹ</span>
        <span>Log cleared. Honeypot ready for incoming audio or simulation prompts.</span>
      </div>
    `;
  };
}

// ==========================================================================
// 4. INCOMING WEBSOCKET EVENTS
// ==========================================================================

let liveCallerBubble = null;

function handleIncomingMessage(event) {
  try {
    const data = JSON.parse(event.data);

    if (data.type === "partial_transcript") {
      // Live interim transcription from AssemblyAI
      setVisualizerActive(true);
      if (!liveCallerBubble) {
        liveCallerBubble = appendTranscript("Caller (Live)", data.text, "caller interim");
      } else {
        const textContent = liveCallerBubble.querySelector(".msg-content") || liveCallerBubble;
        textContent.innerText = data.text;
      }
    } else if (data.type === "caller_turn") {
      setVisualizerActive(false);
      if (liveCallerBubble) {
        liveCallerBubble.remove();
        liveCallerBubble = null;
      }
      appendTranscript("Scammer / Caller", data.text, "caller");
    } else if (data.type === "agent_reply") {
      appendTranscript("Harold (Agent)", data.text, "agent");
      updatePhaseTracker(data.phase);
      playAudioOrSpeech(data.audio, data.text);
    } else if (data.type === "agent_error") {
      appendTranscript("System Alert", `⚠️ Agent generation error: ${data.error}`, "agent system-alert");
      showToast("OpenAI API Error: Check your API Key & Credits");
    } else if (data.type === "threat_intel") {
      latestIntelData = data.intel;
      renderIntel(data.intel);
    }
  } catch (err) {
    console.error("Error parsing message:", err);
  }
}

// ==========================================================================
// 5. TRANSCRIPT RENDERING
// ==========================================================================

function appendTranscript(sender, text, role) {
  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const div = document.createElement("div");
  div.className = `msg ${role}`;

  const isAgent = role.includes("agent");
  const avatar = isAgent ? "👴" : "🚨";

  div.innerHTML = `
    <div class="msg-header">
      <span>${avatar} ${sender}</span>
      ${isAgent ? '<span class="voice-indicator">🔊 Voice Reply</span>' : ''}
      <span class="msg-time">${timeStr}</span>
    </div>
    <div class="msg-content">${escapeHtml(text)}</div>
  `;

  transcriptBox.appendChild(div);
  transcriptBox.scrollTop = transcriptBox.scrollHeight;
  return div;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ==========================================================================
// 6. AUDIO PLAYBACK & NATIVE VOICE FALLBACK
// ==========================================================================

function playAudioOrSpeech(base64Audio, fallbackText) {
  if (base64Audio && base64Audio.length > 0) {
    try {
      const audio = new Audio("data:audio/mp3;base64," + base64Audio);
      setVisualizerActive(true);
      audio.onended = () => {
        if (!isRecording) setVisualizerActive(false);
      };
      audio.play().catch(e => {
        console.warn("Audio autoplay blocked, falling back to Web Speech:", e);
        speakWithBrowserSpeech(fallbackText);
      });
      return;
    } catch (e) {
      console.error("Error playing audio, trying Web Speech:", e);
    }
  }
  // Native Web Speech Fallback for Harold
  speakWithBrowserSpeech(fallbackText);
}

function speakWithBrowserSpeech(text) {
  if (!('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.pitch = 0.85; // slightly lower pitch for Harold
  utterance.rate = 0.92;  // deliberate pace
  
  const voices = window.speechSynthesis.getVoices();
  const naturalVoice = voices.find(v => v.lang && v.lang.startsWith("en") && (v.name.includes("David") || v.name.includes("Guy") || v.name.includes("Male") || v.name.includes("Google US English")));
  if (naturalVoice) utterance.voice = naturalVoice;

  setVisualizerActive(true);
  utterance.onend = () => {
    if (!isRecording) setVisualizerActive(false);
  };
  utterance.onerror = () => {
    if (!isRecording) setVisualizerActive(false);
  };

  window.speechSynthesis.speak(utterance);
}

function setVisualizerActive(active) {
  if (audioVisualizer) {
    if (active) audioVisualizer.classList.add("active");
    else audioVisualizer.classList.remove("active");
  }
}

// ==========================================================================
// 7. INTEL & PHASE TRACKER RENDERING
// ==========================================================================

function updatePhaseTracker(phaseName) {
  const phaseEl = document.getElementById("agent-phase");
  if (phaseEl) {
    phaseEl.innerText = phaseName;
    phaseEl.className = `phase-badge phase-${phaseName}`;
  }

  const phaseOrder = ["hooking", "feigning_confusion", "stalling", "extracting", "wrap_up"];
  const currentIdx = phaseOrder.indexOf(phaseName);

  document.querySelectorAll(".phase-step").forEach((step, idx) => {
    step.classList.remove("active", "completed");
    if (idx < currentIdx) {
      step.classList.add("completed");
    } else if (idx === currentIdx) {
      step.classList.add("active");
    }
  });
}

function renderIntel(intel) {
  if (!intel) return;

  // 1. Urgency Level
  const urgencyEl = document.getElementById("threat-urgency");
  if (urgencyEl) {
    const level = intel.urgency_level || "Low";
    urgencyEl.innerText = level;
    urgencyEl.className = `urgency-pill urgency-${level.toLowerCase()}`;
  }

  // 2. Claimed Identity
  const claimedIdEl = document.getElementById("claimed-id");
  if (claimedIdEl) {
    claimedIdEl.innerText = intel.caller_claimed_identity || "Detecting...";
  }

  // 3. Tactics List
  const tacticsList = document.getElementById("tactics-list");
  const tacticsCount = document.getElementById("tactics-count");
  if (tacticsList) {
    if (intel.tactics_used && intel.tactics_used.length > 0) {
      tacticsList.innerHTML = intel.tactics_used.map(t => `<li>🎯 ${escapeHtml(t)}</li>`).join("");
      if (tacticsCount) tacticsCount.innerText = intel.tactics_used.length;
    } else {
      tacticsList.innerHTML = '<li class="empty-state">No tactics logged yet</li>';
      if (tacticsCount) tacticsCount.innerText = "0";
    }
  }

  // 4. Accounts List
  const accountsList = document.getElementById("accounts-list");
  const accountsCount = document.getElementById("accounts-count");
  if (accountsList) {
    if (intel.mule_bank_accounts && intel.mule_bank_accounts.length > 0) {
      accountsList.innerHTML = intel.mule_bank_accounts.map(a => `
        <li class="intel-item">
          <span>💳 ${escapeHtml(a)}</span>
          <button class="btn-copy-item" onclick="copyToClipboard('${escapeJs(a)}')" title="Copy Account">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
              <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
              <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
            </svg>
          </button>
        </li>
      `).join("");
      if (accountsCount) accountsCount.innerText = intel.mule_bank_accounts.length;
    } else {
      accountsList.innerHTML = '<li class="empty-state">Awaiting account or crypto wallet extraction...</li>';
      if (accountsCount) accountsCount.innerText = "0";
    }
  }

  // 5. URLs / Domains List
  const urlsList = document.getElementById("urls-list");
  const urlsCount = document.getElementById("urls-count");
  if (urlsList) {
    if (intel.urls_or_domains && intel.urls_or_domains.length > 0) {
      urlsList.innerHTML = intel.urls_or_domains.map(u => `
        <li class="intel-item url-item">
          <span>🌐 ${escapeHtml(u)}</span>
          <button class="btn-copy-item" onclick="copyToClipboard('${escapeJs(u)}')" title="Copy URL">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
              <rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>
              <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>
            </svg>
          </button>
        </li>
      `).join("");
      if (urlsCount) urlsCount.innerText = intel.urls_or_domains.length;
    } else {
      urlsList.innerHTML = '<li class="empty-state">Awaiting link or software indicator...</li>';
      if (urlsCount) urlsCount.innerText = "0";
    }
  }
}

function escapeJs(str) {
  return str.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ==========================================================================
// 8. HELPERS & TELEMETRY
// ==========================================================================

function startTimer() {
  if (callTimerInterval) return;
  callStartTime = Date.now();
  callTimerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - callStartTime) / 1000);
    const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const secs = String(elapsed % 60).padStart(2, '0');
    if (callTimerEl) callTimerEl.innerText = `${mins}:${secs}`;
  }, 1000);
}

window.copyToClipboard = function(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast("Copied to clipboard: " + text);
  }).catch(e => {
    showToast("Failed to copy");
  });
};

if (copyIntelBtn) {
  copyIntelBtn.onclick = () => {
    if (!latestIntelData) {
      showToast("No threat intel extracted yet");
      return;
    }
    const jsonStr = JSON.stringify(latestIntelData, null, 2);
    navigator.clipboard.writeText(jsonStr).then(() => {
      showToast("Extracted Threat Intel JSON copied to clipboard!");
    });
  };
}

function showToast(msg) {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<span>✓</span> <span>${escapeHtml(msg)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// Initialize WebSocket on startup
connectWebSocket();