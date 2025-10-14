// record.js – Aufnahme (Classic & Live) + Simulation aus Datei mit PCM/VAD/Overlap
console.log("record.js geladen");

// ========= Allgemeine Hilfen =========
function pickMime(...candidates) {
  for (const c of candidates) {
    if (window.MediaRecorder?.isTypeSupported?.(c)) return c;
  }
  return "";
}
function extForMime(m) {
  if (!m) return "webm";
  if (m.includes("ogg")) return "ogg";
  if (m.includes("mp4")) return "m4a";
  return "webm";
}

// WAV aus Float32 (mono) bauen
function wavFromFloat32(float32, sampleRate) {
  const numSamples = float32.length;
  const bytesPerSample = 2; // PCM16
  const blockAlign = 1 * bytesPerSample; // mono
  const byteRate = sampleRate * blockAlign;
  const dataSize = numSamples * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(off, s) { for (let i=0;i<s.length;i++) view.setUint8(off+i, s.charCodeAt(i)); }

  // RIFF header
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, 'WAVE');

  // fmt chunk
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);          // PCM fmt chunk size
  view.setUint16(20, 1, true);           // PCM
  view.setUint16(22, 1, true);           // channels = 1
  view.setUint32(24, sampleRate, true);  // sample rate
  view.setUint32(28, byteRate, true);    // byte rate
  view.setUint16(32, blockAlign, true);  // block align
  view.setUint16(34, 16, true);          // bits per sample

  // data chunk
  writeString(36, 'data');
  view.setUint32(40, dataSize, true);

  // PCM16 schreiben
  let o = 44;
  for (let i = 0; i < numSamples; i++) {
    let x = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7FFF, true);
    o += 2;
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
function concatFloat32(a, b) {
  if (!a || a.length === 0) return new Float32Array(b);
  if (!b || b.length === 0) return new Float32Array(a);
  const out = new Float32Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

// Gemeinsame Constraints (Browser-Effekte aus)
const baseAudioConstraints = {
  channelCount: { ideal: 1 },
  sampleRate: 48000,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false
};

// ================================
// Klassische Einmal-Aufnahme (falls UI vorhanden)
// ================================
(() => {
  const startBtn = document.getElementById("recordBtn");
  const stopBtn  = document.getElementById("stopBtn");
  const statusEl = document.getElementById("status");
  const micSel   = document.getElementById("micSelectClassic");

  if (!startBtn || !stopBtn) return;

  let recorder = null;
  let chunks = [];
  let stream = null;
  let timesliceMs = 2000; // 2s

  function pickMimeClassic() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4" // Safari
    ];
    for (const c of candidates) {
      if (window.MediaRecorder?.isTypeSupported?.(c)) return c;
    }
    return "";
  }
  function extForMimeClassic(m) {
    if (!m) return "webm";
    if (m.includes("webm")) return "webm";
    if (m.includes("ogg"))  return "ogg";
    return "m4a"; // Safari
  }

  async function listMicsClassic() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      if (!micSel) return;
      const current = micSel.value;
      micSel.innerHTML = "";
      devices.filter(d => d.kind === "audioinput").forEach((d, i) => {
        const opt = document.createElement("option");
        opt.value = d.deviceId;
        opt.textContent = d.label || `Mikrofon ${i + 1}`;
        micSel.appendChild(opt);
      });
      if (current) {
        const keep = Array.from(micSel.options).some(o => o.value === current);
        if (keep) micSel.value = current;
      }
    } catch(e){
      console.warn("enumerateDevices (classic) fehlgeschlagen:", e);
    }
  }
  (async () => {
    try { const tmp = await navigator.mediaDevices.getUserMedia({ audio: true }); tmp.getTracks().forEach(t => t.stop()); } catch(_) {}
    await listMicsClassic();
    navigator.mediaDevices?.addEventListener?.("devicechange", listMicsClassic);
  })();

  startBtn.onclick = async () => {
    if (recorder && recorder.state === "recording") return;

    chunks = [];
    statusEl.textContent = "🎙️ Aufnahme läuft…";
    startBtn.disabled = true;
    stopBtn.disabled  = false;

    const deviceId = micSel?.value ? { exact: micSel.value } : undefined;
    const constraints = {
      audio: {
        channelCount: 1,
        sampleRate: 48000,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        ...(deviceId ? { deviceId } : {})
      }
    };

    try { stream = await navigator.mediaDevices.getUserMedia(constraints); }
    catch (e) {
      console.warn("getUserMedia Fallback (klassisch):", e);
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (e2) {
        statusEl.textContent = "❌ Kein Zugriff aufs Mikrofon";
        startBtn.disabled = false; stopBtn.disabled = true; return;
      }
    }

    const mime = pickMimeClassic();
    const mrOptions = {};
    if (mime) mrOptions.mimeType = mime;
    mrOptions.audioBitsPerSecond = 192000;

    try { recorder = new MediaRecorder(stream, mrOptions); }
    catch (e) { console.warn("MediaRecorder Fallback ohne Optionen:", e); recorder = new MediaRecorder(stream); }

    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };

    recorder.onerror = (ev) => {
      console.error("MediaRecorder error:", ev?.error || ev);
      statusEl.textContent = "❌ Aufnahmefehler";
      try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}
      startBtn.disabled = false; stopBtn.disabled = true;
    };

    recorder.onstop = async () => {
      try {
        const outMime = recorder.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks, { type: outMime });
        try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}

        const formData = new FormData();
        formData.append("audio", blob, `recorded.${extForMimeClassic(outMime)}`);
        statusEl.textContent = "⏳ Verarbeitung…";

        const res = await fetch("/upload_audio", { method: "POST", body: formData });
        const html = await res.text();

        startBtn.disabled = false; stopBtn.disabled = true;
        statusEl.textContent = "✅ Hochgeladen. Öffne Ergebnis…";
        document.open(); document.write(html); document.close();
      } catch(err) {
        console.error(err);
        statusEl.textContent = "❌ Fehler beim Upload";
        startBtn.disabled = false; stopBtn.disabled = true;
        try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}
      }
    };

    try { recorder.start(timesliceMs); } catch (e) { console.warn("start(timeslice) fehlgeschlagen:", e); recorder.start(); }
  };

  stopBtn.onclick = () => { if (!recorder || recorder.state !== "recording") return; statusEl.textContent = "⏹️ Stoppe…"; try { recorder.stop(); } catch(_) {} };
})();

// ================================
// Live-Modus (Chunked) + Simulation aus Datei (PCM/VAD/Overlap)
// ================================
(() => {
  if (window.__liveHandlersBound) return;
  window.__liveHandlersBound = true;

  const startBtn = document.getElementById("liveRecordBtn");
  const stopBtn  = document.getElementById("liveStopBtn");
  const statusEl = document.getElementById("liveStatus");
  const micSel   = document.getElementById("micSelect");
  const transcriptEl = document.getElementById("liveTranscript");
  if (!startBtn || !stopBtn) return;

  // ---- Tuning per localStorage ----
  const SEGMENT_MS     = parseInt(localStorage.getItem('SEGMENT_MS')     || '10000', 10);
  const MIN_SEG_MS     = parseInt(localStorage.getItem('MIN_SEG_MS')     || '4500', 10);
  const OVERLAP_MS     = parseInt(localStorage.getItem('OVERLAP_MS')     || '700', 10);
  const VAD_WINDOW_MS  = parseInt(localStorage.getItem('VAD_WINDOW_MS')  || '50', 10);
  const VAD_THRESH     = parseFloat(localStorage.getItem('VAD_THRESH')   || '0.006');
  const VAD_HANG_MS    = parseInt(localStorage.getItem('VAD_HANG_MS')    || '450', 10);

  const live = {
    isRecording: false,
    mediaRecorder: null,
    segmentTimer: null,
    rawStream: null,
    ctx: null,
    processedStream: null,
    mime: "",
    ext: "",
    sessionId: null,
    lastSeqShown: 0,
    mode: "mic",
    simSource: null,
    pcmBuf: new Float32Array(0),
    carry:  new Float32Array(0),
    vadSilenceRun: 0,
    sampleRate: 48000,
    pcmActive: false,
  };
  window.__liveState = live;

  function fmtErr(e){ return (e && e.message) ? e.message : String(e); }

  function pickMimeLocal() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4"
    ];
    for (const c of candidates) { if (window.MediaRecorder?.isTypeSupported?.(c)) return c; }
    return "";
  }
  function extForMimeLocal(m) {
    if (!m) return "webm";
    if (m.includes("webm")) return "webm";
    if (m.includes("ogg"))  return "ogg";
    return "m4a";
  }

  async function buildProcessedStream(rawStream) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000, latencyHint: "interactive" });
    live.ctx = ctx;

    const source = ctx.createMediaStreamSource(rawStream);
    const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 70;
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass";  lp.frequency.value = 12000;

    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 25; comp.ratio.value = 2.5; comp.attack.value = 0.005; comp.release.value = 0.12;

    const dest = ctx.createMediaStreamDestination();
    source.connect(hp); hp.connect(lp); lp.connect(comp); comp.connect(dest);

    live.processedStream = dest.stream;
    return live.processedStream;
  }

  function clearSegmentTimer() { if (live.segmentTimer) { try { clearTimeout(live.segmentTimer); } catch(_) {} live.segmentTimer = null; } }
  function hardStopRecorder() {
    if (live.mediaRecorder) {
      try { live.mediaRecorder.onstop = null; } catch(_) {}
      if (live.mediaRecorder.state !== "inactive") { try { live.mediaRecorder.stop(); } catch(_) {} }
      live.mediaRecorder = null;
    }
  }
  function stopStreamsAndAudio() {
    if (live.rawStream) { try { live.rawStream.getTracks().forEach(t => { try{t.stop();}catch(_){}}); } catch(_) {} live.rawStream = null; }
    if (live.simSource) { try { live.simSource.stop(0); } catch(_) {} live.simSource = null; }
    if (live.ctx) { try { live.ctx.close(); } catch(_) {} live.ctx = null; }
    live.processedStream = null;
  }

  // ----- MediaRecorder-Segmentierung: nur für Mikro-Modus -----
  function startSegmentMic() {
    const mrOptions = {};
    if (live.mime) mrOptions.mimeType = live.mime;
    mrOptions.audioBitsPerSecond = 256000;
    try { live.mediaRecorder = new MediaRecorder(live.processedStream, mrOptions); }
    catch (e) { live.mediaRecorder = new MediaRecorder(live.processedStream); }

    live.mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) sendChunkToServer(e.data, live.ext); };
    live.mediaRecorder.onstop = () => { if (live.isRecording && live.mode === "mic") startSegmentMic(); };
    live.mediaRecorder.start();
    live.segmentTimer = setTimeout(() => { try { live.mediaRecorder.stop(); } catch(_) {} }, SEGMENT_MS);
  }

  async function startLive() {
    if (live.isRecording) return;
    live.mode = "mic";
    live.isRecording = true;

    statusEl.textContent = "Aufnahme läuft…";
    startBtn.disabled = true; stopBtn.disabled = false;
    transcriptEl.textContent = "Live-Transkript startet…";

    const sid = await fetch("/start_stream").then(r => r.json());
    live.sessionId = sid.session_id;

    const deviceId = (micSel && micSel.value) ? { exact: micSel.value } : undefined;
    const constraints = { audio: { deviceId, ...baseAudioConstraints } };

    try { live.rawStream = await navigator.mediaDevices.getUserMedia(constraints); }
    catch (e) { live.rawStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }

    live.mime = pickMimeLocal();
    live.ext  = extForMimeLocal(live.mime);

    await buildProcessedStream(live.rawStream);
    startSegmentMic();
  }

  // ====== Simulation aus Datei: PCM/VAD/Overlap ======
  async function startSimulationFromFile(file) {
    if (!file || live.isRecording) return;
    live.mode = "sim"; live.isRecording = true;

    statusEl.textContent = "Simulation läuft…";
    startBtn.disabled = true; stopBtn.disabled = false;
    transcriptEl.textContent = "Live-Transkript (Simulation) startet…";

    const sid = await fetch("/start_stream").then(r => r.json());
    live.sessionId = sid.session_id;

    const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000, latencyHint: "interactive" });
    live.ctx = ctx; live.sampleRate = ctx.sampleRate;

    const arrayBuf = await file.arrayBuffer();
    const audioBuf = await ctx.decodeAudioData(arrayBuf);

    const source = ctx.createBufferSource();
    source.buffer = audioBuf; live.simSource = source;

    const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 70;
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass";  lp.frequency.value = 12000;

    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 25; comp.ratio.value = 2.5; comp.attack.value = 0.005; comp.release.value = 0.12;

    // Worklet zum PCM-Abgriff
    const code = `
      class PCMWorklet extends AudioWorkletProcessor {
        process(inputs) {
          const ch0 = inputs[0][0];
          if (ch0 && ch0.length) this.port.postMessage(ch0);
          return true;
        }
      }
      registerProcessor('pcm-worklet', PCMWorklet);
    `;
    const blobUrl = URL.createObjectURL(new Blob([code], {type: 'application/javascript'}));
    await ctx.audioWorklet.addModule(blobUrl);
    const node = new AudioWorkletNode(ctx, 'pcm-worklet', { numberOfInputs: 1, numberOfOutputs: 0 });

    const dest = ctx.createGain(); dest.gain.value = 0; // stumm
    source.connect(hp); hp.connect(lp); lp.connect(comp); comp.connect(node); comp.connect(dest); dest.connect(ctx.destination);

    // PCM/VAD initialisieren
    live.pcmBuf = new Float32Array(0);
    live.carry  = new Float32Array(0);
    live.vadSilenceRun = 0;
    live.pcmActive = true;

    const SR = live.sampleRate;
    const MAX_SAMPLES   = Math.floor(SR * (SEGMENT_MS   / 1000));
    const MIN_SAMPLES   = Math.floor(SR * (MIN_SEG_MS   / 1000));
    const OVERLAP_SAMP  = Math.floor(SR * (OVERLAP_MS   / 1000));
    const VAD_WIN_SAMP  = Math.floor(SR * (VAD_WINDOW_MS/ 1000));
    const VAD_HANG_SAMP = Math.floor(SR * (VAD_HANG_MS  / 1000));

    function maybeFlush(cutIndex = -1, force = false) {
      const total = live.pcmBuf.length;
      if (!force) {
        if (total < MIN_SAMPLES && cutIndex < 0) return;
        if (cutIndex < 0 && total < MAX_SAMPLES) return;
      }
      if (cutIndex < 0 || cutIndex > total) cutIndex = Math.min(total, MAX_SAMPLES);
      const chunkPart = live.pcmBuf.subarray(0, cutIndex);
      const payload   = concatFloat32(live.carry, chunkPart);
      const wavBlob   = wavFromFloat32(payload, SR);
      sendChunkToServer(wavBlob, 'wav');

      const carryLen = Math.min(OVERLAP_SAMP, payload.length);
      live.carry = payload.subarray(payload.length - carryLen);
      live.pcmBuf = live.pcmBuf.subarray(cutIndex);
      live.vadSilenceRun = 0;
    }

    function rms(arr, start, len) {
      let s = 0; const n = Math.min(len, arr.length - start);
      for (let i=0;i<n;i++) { const x = arr[start+i]; s += x*x; }
      return Math.sqrt(s / Math.max(1,n));
    }

    function processVAD() {
      const total = live.pcmBuf.length;
      if (total < VAD_WIN_SAMP) return;

      let idx = 0;
      let cutCandidate = -1;
      const maxScan = Math.min(total, MAX_SAMPLES);
      while (idx + VAD_WIN_SAMP <= maxScan) {
        const r = rms(live.pcmBuf, idx, VAD_WIN_SAMP);
        if (r < VAD_THRESH) {
          live.vadSilenceRun += VAD_WIN_SAMP;
          if (live.vadSilenceRun >= VAD_HANG_SAMP && (idx + VAD_WIN_SAMP) >= MIN_SAMPLES) {
            cutCandidate = idx + VAD_WIN_SAMP;
            break;
          }
        } else {
          live.vadSilenceRun = 0;
        }
        idx += VAD_WIN_SAMP;
      }

      if (cutCandidate >= 0) {
        maybeFlush(cutCandidate, false);
      } else if (total >= MAX_SAMPLES) {
        maybeFlush(-1, true);
      }
    }

    node.port.onmessage = (e) => {
      if (!live.pcmActive || !live.isRecording || live.mode !== 'sim') return;
      const f32 = e.data; // Float32Array
      if (!(f32 && f32.length)) return;
      live.pcmBuf = concatFloat32(live.pcmBuf, f32);
      processVAD();
    };

    source.onended = () => {
      if (live.isRecording && live.mode === "sim") {
        if (live.pcmBuf.length > 0 || live.carry.length > 0) {
          maybeFlush(live.pcmBuf.length, true);
        }
        stopLive();
      }
    };

    source.start(0);
  }

  async function stopLive() {
    if (!live.isRecording) return;
    live.isRecording = false;

    clearSegmentTimer();
    hardStopRecorder();
    live.pcmActive = false;

    statusEl.textContent = "Aufnahme gestoppt.";
    startBtn.disabled = false; stopBtn.disabled = true;

    stopStreamsAndAudio();

    setTimeout(async () => {
      if (!live.sessionId) return;
      statusEl.textContent = "Analyse läuft…";
      const fd = new FormData(); fd.append("session_id", live.sessionId);

      const lastLive = transcriptEl.textContent.trim();

      let data = {};
      try { const res = await fetch("/process_stream", { method: "POST", body: fd }); data = await res.json(); }
      catch (e) { console.warn("process_stream parse error:", e); data = {}; }

      const finalDialog = (data && typeof data.dialog === "string") ? data.dialog.trim() : "";
      const minLen = 20;
      const okLength = finalDialog.length >= Math.min(minLen, Math.floor(lastLive.length * 0.6));
      transcriptEl.textContent = okLength ? finalDialog : lastLive;
      statusEl.textContent = "Analyse abgeschlossen.";

      if (data && typeof data.anamnese === "string" && data.anamnese.trim()) {
        const anamneseBlock = document.getElementById("liveAnamnese");
        if (anamneseBlock) anamneseBlock.textContent = data.anamnese;
      }
      window.liveAnamneseFilename = data && data.filename;

      try { const html = await fetch("/sidebar_reload").then(r => r.text()); const sb = document.querySelector(".sidebar"); if (sb) sb.outerHTML = html; } catch(_) {}

      if (data && data.filename) { window.location.href = `/transkript/${encodeURIComponent(data.filename)}`; return; }
    }, 500);
  }

  async function sendChunkToServer(blob, ext) {
    const fd = new FormData();
    fd.append("audio_chunk", blob, `chunk.${ext}`);
    fd.append("session_id", live.sessionId);
    fd.append("ext", ext);

    try {
      const data = await fetch("/stream_chunk", { method: "POST", body: fd }).then(r => r.json());
      if (typeof data.seq === "number" && data.seq < live.lastSeqShown) return;
      if (typeof data.seq === "number") live.lastSeqShown = data.seq;

      if (data.partial_transcript && data.partial_transcript !== transcriptEl.textContent) {
        transcriptEl.textContent = data.partial_transcript;
        transcriptEl.scrollTop = transcriptEl.scrollHeight;
      }
    } catch (e) {
      console.warn("Chunk-Upload fehlgeschlagen:", fmtErr(e));
    }
  }

  // Buttons binden
  startBtn.addEventListener("click", startLive);
  stopBtn.addEventListener("click", stopLive);

  // Simulations-UI (Datei + Button) – OHNE accept-Filter
  (function ensureSimulationUI() {
    const host = document.getElementById("liveTranskriptBlock") || document.body;
    const box = document.createElement("div");
    box.style.margin = "8px 0 4px 0";
    box.style.padding = "8px";
    box.style.border = "1px dashed #cbd5e1";
    box.style.borderRadius = "8px";
    box.style.background = "#f8fafc";
    box.style.display = "flex";
    box.style.gap = "8px";
    box.style.alignItems = "center";

    const label = document.createElement("label");
    label.textContent = "Live-Simulation aus Datei:";
    label.style.minWidth = "180px";

    const file = document.createElement("input");
    file.type = "file"; // KEIN accept -> alle Dateien sichtbar

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Als Live abspielen";
    btn.addEventListener("click", async () => {
      if (!file.files || !file.files[0]) { alert("Bitte eine Audiodatei auswählen (z. B. WAV)."); return; }
      try { await startSimulationFromFile(file.files[0]); }
      catch (e) { console.error(e); alert("Simulation konnte nicht gestartet werden: " + fmtErr(e)); }
    });

    box.appendChild(label); box.appendChild(file); box.appendChild(btn);
    const anchor = document.getElementById("liveControls") || host;
    anchor.appendChild(box);
  })();

  // Mic-Liste initialisieren
  async function ensureMicPermission() { try { const tmp = await navigator.mediaDevices.getUserMedia({ audio: true }); tmp.getTracks().forEach(t => t.stop()); } catch (_) {} }
  async function listMics() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter(d => d.kind === "audioinput");
      const fill = (id) => {
        const sel = document.getElementById(id); if (!sel) return;
        const current = sel.value; sel.innerHTML = "";
        mics.forEach((d, i) => { const opt = document.createElement("option"); opt.value = d.deviceId; opt.textContent = d.label || `Mikrofon ${i+1}`; sel.appendChild(opt); });
        if (current) { const keep = Array.from(sel.options).some(o => o.value === current); if (keep) sel.value = current; }
      };
      fill("micSelect"); fill("micSelectClassic");
    } catch (e) { console.warn("enumerateDevices fehlgeschlagen:", fmtErr(e)); }
  }
  (async () => {
    if (navigator.mediaDevices?.enumerateDevices) {
      await ensureMicPermission();
      await listMics();
      navigator.mediaDevices.addEventListener?.("devicechange", listMics);
    }
  })();
})();

