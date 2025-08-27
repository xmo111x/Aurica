// record.js – Aufnahme (Classic & Live) mit robusten Defaults für STT
console.log("record.js geladen");

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

// Gemeinsame Constraints (Browser-Effekte aus)
const baseAudioConstraints = {
  channelCount: { ideal: 1 },
  sampleRate: 48000,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false
};

// ------------------------
// Klassische Einmal-Aufnahme – ROBUST (Timeslice, kein requestData)
// ------------------------
(() => {
  const startBtn = document.getElementById("recordBtn");
  const stopBtn  = document.getElementById("stopBtn");
  const statusEl = document.getElementById("status");
  const micSel   = document.getElementById("micSelectClassic");

  if (!startBtn || !stopBtn) return;

  let recorder = null;
  let chunks = [];
  let stream = null;
  let timesliceMs = 2000; // alle 2s ein Chunk – stabil in Firefox & Background

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
      // versuche, die Auswahl zu behalten
      if (current) {
        const keep = Array.from(micSel.options).some(o => o.value === current);
        if (keep) micSel.value = current;
      }
    } catch(e){
      console.warn("enumerateDevices (classic) fehlgeschlagen:", e);
    }
  }
  // Initial versuchen zu befüllen (nach kurzer Permission-Anfrage erhöht sich die Chance auf Labels)
  (async () => {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
      tmp.getTracks().forEach(t => t.stop());
    } catch(_) {}
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

    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e) {
      console.warn("getUserMedia Fallback (klassisch):", e);
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e2) {
        statusEl.textContent = "❌ Kein Zugriff aufs Mikrofon";
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        return;
      }
    }

    const mime = pickMimeClassic();
    const mrOptions = {};
    if (mime) mrOptions.mimeType = mime;
    mrOptions.audioBitsPerSecond = 192000; // konservativ

    try {
      recorder = new MediaRecorder(stream, mrOptions);
    } catch (e) {
      console.warn("MediaRecorder Fallback ohne Optionen:", e);
      recorder = new MediaRecorder(stream);
    }

    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };

    recorder.onerror = (ev) => {
      console.error("MediaRecorder error:", ev?.error || ev);
      statusEl.textContent = "❌ Aufnahmefehler";
      try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}
      startBtn.disabled = false;
      stopBtn.disabled  = true;
    };

    recorder.onstop = async () => {
      try {
        const outMime = recorder.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks, { type: outMime });

        // Stream freigeben
        try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}

        // Sanity-Check: wenn Blob zu klein, Hinweis geben
        if (blob.size < 5000) {
          console.warn("Warnung: Sehr kleine Aufnahme (", blob.size, "Bytes).");
        }

        const formData = new FormData();
        formData.append("audio", blob, `recorded.${extForMimeClassic(outMime)}`);
        statusEl.textContent = "⏳ Verarbeitung…";

        const res = await fetch("/upload_audio", { method: "POST", body: formData });
        const html = await res.text();

        // Buttons zurücksetzen
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        statusEl.textContent = "✅ Hochgeladen. Öffne Ergebnis…";

        // Ergebnis-Seite anzeigen
        document.open(); document.write(html); document.close();
      } catch(err) {
        console.error(err);
        statusEl.textContent = "❌ Fehler beim Upload";
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        try { stream && stream.getTracks().forEach(t => t.stop()); } catch(_) {}
      }
    };

    // WICHTIG: Timeslice setzen, damit auch im Hintergrund zuverlässig Daten kommen
    try {
      recorder.start(timesliceMs);
    } catch (e) {
      console.warn("recorder.start mit timeslice fehlgeschlagen, versuche ohne:", e);
      recorder.start(); // notfalls ohne – aber weniger robust im Hintergrund
    }
  };

  stopBtn.onclick = () => {
    if (!recorder || recorder.state !== "recording") return;
    statusEl.textContent = "⏹️ Stoppe…";
    // Kein requestData() hier – das kann in Firefox frühzeitig abschneiden
    try { recorder.stop(); } catch(_) {}
  };
})();

// ------------------------
// Live-Modus (Chunked) – STABILE VERSION (keine Doppel-Handler, sauberes Stoppen)
// ------------------------
(() => {
  if (window.__liveHandlersBound) return; // Guard gegen Mehrfachbindung
  window.__liveHandlersBound = true;

  const startBtn = document.getElementById("liveRecordBtn");
  const stopBtn  = document.getElementById("liveStopBtn");
  const statusEl = document.getElementById("liveStatus");
  const micSel   = document.getElementById("micSelect");
  const transcriptEl = document.getElementById("liveTranscript");

  if (!startBtn || !stopBtn) return;

  // globaler Live-State (einheitliche Quelle der Wahrheit)
  const live = {
    isRecording: false,
    mediaRecorder: null,
    segmentTimer: null,
    rawStream: null,          // getUserMedia Stream
    ctx: null,                // AudioContext
    processedStream: null,    // MediaStream aus AudioContext
    mime: "",
    ext: "",
    sessionId: null,
    lastSeqShown: 0,
  };
  window.__liveState = live; // optional fürs Debuggen in der Konsole

  function fmtErr(e){ return (e && e.message) ? e.message : String(e); }

  function pickMime() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4"
    ];
    for (const c of candidates) {
      if (window.MediaRecorder?.isTypeSupported?.(c)) return c;
    }
    return "";
  }
  function extForMime(m) {
    if (!m) return "webm";
    if (m.includes("webm")) return "webm";
    if (m.includes("ogg"))  return "ogg";
    return "m4a";
  }

  async function buildProcessedStream(rawStream) {
    const ctx = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: 48000,
      latencyHint: "interactive",
    });
    live.ctx = ctx;

    const source = ctx.createMediaStreamSource(rawStream);

    // milde, STT-freundliche Kette
    const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 70;
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass";  lp.frequency.value = 12000;

    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.knee.value = 25;
    comp.ratio.value = 2.5;
    comp.attack.value = 0.005;
    comp.release.value = 0.12;

    const dest = ctx.createMediaStreamDestination();

    source.connect(hp); hp.connect(lp); lp.connect(comp); comp.connect(dest);

    live.processedStream = dest.stream;
    return live.processedStream;
  }

  function clearSegmentTimer() {
    if (live.segmentTimer) {
      try { clearTimeout(live.segmentTimer); } catch(_) {}
      live.segmentTimer = null;
    }
  }

  function hardStopRecorder() {
    // onstop soll NICHT neu starten
    if (live.mediaRecorder) {
      try { live.mediaRecorder.onstop = null; } catch(_) {}
      if (live.mediaRecorder.state !== "inactive") {
        try { live.mediaRecorder.stop(); } catch(_) {}
      }
      live.mediaRecorder = null;
    }
  }

  function stopStreamsAndAudio() {
    if (live.rawStream) {
      try { live.rawStream.getTracks().forEach(t => { try{t.stop();}catch(_){}}); } catch(_) {}
      live.rawStream = null;
    }
    if (live.ctx) {
      try { live.ctx.close(); } catch(_) {}
      live.ctx = null;
    }
    live.processedStream = null;
  }

  function startSegment() {
    const mrOptions = {};
    if (live.mime) mrOptions.mimeType = live.mime;
    mrOptions.audioBitsPerSecond = 256000;

    try {
      live.mediaRecorder = new MediaRecorder(live.processedStream, mrOptions);
    } catch (e) {
      // Fallback ohne Optionen
      live.mediaRecorder = new MediaRecorder(live.processedStream);
    }

    live.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        sendChunkToServer(e.data, live.ext);
      }
    };

    live.mediaRecorder.onstop = () => {
      // Nur neu starten, wenn weiterhin Recording aktiv ist
      if (live.isRecording) startSegment();
    };

    live.mediaRecorder.start();
    // alle 3s Segment schließen -> onstop -> ggf. restart
    live.segmentTimer = setTimeout(() => {
      try { live.mediaRecorder.stop(); } catch(_) {}
    }, 3000);
  }

  async function startLive() {
    if (live.isRecording) return;
    live.isRecording = true;

    statusEl.textContent = "Aufnahme läuft…";
    startBtn.disabled = true;
    stopBtn.disabled  = false;
    transcriptEl.textContent = "Live-Transkript startet…";

    // Session vom Server holen
    const sid = await fetch("/start_stream").then(r => r.json());
    live.sessionId = sid.session_id;

    // Mic auswählen
    const deviceId = (micSel && micSel.value) ? { exact: micSel.value } : undefined;
    const constraints = {
      audio: {
        deviceId,
        channelCount: 1,
        sampleRate: 48000,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false
      }
    };

    try {
      live.rawStream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e) {
      // Fallback – aber dann evtl. mit Browser-Effekten
      live.rawStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }

    live.mime = pickMime();
    live.ext  = extForMime(live.mime);

    await buildProcessedStream(live.rawStream);
    startSegment();
  }

  async function stopLive() {
    if (!live.isRecording) return;
    live.isRecording = false;

    // zuerst Timer & Recorder stoppen, damit NICHTS neu startet
    clearSegmentTimer();
    hardStopRecorder();

    statusEl.textContent = "Aufnahme gestoppt.";
    startBtn.disabled = false;
    stopBtn.disabled  = true;

    // Quelle freigeben
    stopStreamsAndAudio();

    // Analyse anstoßen (mit Plausibilitäts-Fix für finalen Dialog)
    setTimeout(async () => {
      if (!live.sessionId) return;
      statusEl.textContent = "Analyse läuft…";
      const fd = new FormData();
      fd.append("session_id", live.sessionId);

      // Merke den letzten angezeigten Live-Text
      const lastLive = transcriptEl.textContent.trim();

      let data = {};
      try {
        const res = await fetch("/process_stream", { method: "POST", body: fd });
        data = await res.json(); // kann werfen, wenn HTML/Fehler kommt
      } catch (e) {
        console.warn("process_stream parse error:", e);
        data = {};
      }

      const finalDialog = (data && typeof data.dialog === "string") ? data.dialog.trim() : "";

      // Nur ersetzen, wenn plausibel lang (>= 20 Zeichen ODER >= 60% der Live-Länge)
      const minLen = 20;
      const okLength = finalDialog.length >= Math.min(minLen, Math.floor(lastLive.length * 0.6));

      if (okLength) {
        transcriptEl.textContent = finalDialog;
      } else {
        transcriptEl.textContent = lastLive;
        console.warn("Finaler Dialog zu kurz/fragwürdig – Live-Transkript behalten.");
      }

      statusEl.textContent = "Analyse abgeschlossen.";

      if (data && typeof data.anamnese === "string" && data.anamnese.trim()) {
        const anamneseBlock = document.getElementById("liveAnamnese");
        if (anamneseBlock) anamneseBlock.textContent = data.anamnese;
      }
      window.liveAnamneseFilename = data && data.filename;

      // Sidebar refresh (best effort)
      try {
        const html = await fetch("/sidebar_reload").then(r => r.text());
        const sb = document.querySelector(".sidebar");
        if (sb) sb.outerHTML = html;
      } catch (_) {}
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
      // still silent; Live darf robust bleiben
      console.warn("Chunk-Upload fehlgeschlagen:", fmtErr(e));
    }
  }

  // Buttons binden (einmalig)
  startBtn.addEventListener("click", startLive);
  stopBtn.addEventListener("click", stopLive);

  // Toggle Block (falls vorhanden)
  const toggleBtn = document.getElementById("toggleLiveBlock");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const block = document.getElementById("liveTranskriptBlock");
      if (!block) return;
      block.style.display = (block.style.display === "none") ? "" : "none";
    });
  }

  // Mic-Liste initial befüllen (Live + Classic)
  async function ensureMicPermission() {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
      tmp.getTracks().forEach(t => t.stop());
    } catch (_) {}
  }
  async function listMics() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter(d => d.kind === "audioinput");
      const fill = (id) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = "";
        mics.forEach((d, i) => {
          const opt = document.createElement("option");
          opt.value = d.deviceId;
          opt.textContent = d.label || `Mikrofon ${i+1}`;
          sel.appendChild(opt);
        });
        if (current) {
          const keep = Array.from(sel.options).some(o => o.value === current);
          if (keep) sel.value = current;
        }
      };
      fill("micSelect");
      fill("micSelectClassic");
    } catch (e) {
      console.warn("enumerateDevices fehlgeschlagen:", fmtErr(e));
    }
  }
  (async () => {
    if (navigator.mediaDevices?.enumerateDevices) {
      await ensureMicPermission();
      await listMics();
      navigator.mediaDevices.addEventListener?.("devicechange", listMics);
    }
  })();
})();
