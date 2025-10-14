from flask import Flask, request, render_template, session, jsonify, redirect, url_for, flash
from difflib import SequenceMatcher
from collections import defaultdict
from werkzeug.middleware.proxy_fix import ProxyFix
import subprocess
import shlex
import os, requests, tempfile
import re
import json
import uuid
import glob
import shutil
import time
try:
    from rapidfuzz import process, fuzz
    USE_RAPIDFUZZ = True
except Exception:
    USE_RAPIDFUZZ = False


from datetime import datetime
from utils import transcribe_with_whispercpp, assign_speakers_llm, summarize_with_lmstudio, get_gespraechsdauer_from_vtt, MODEL_PATH

app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

def _safe_unlink(path: str) -> bool:
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception as e:
        print(f"⚠️ Löschen fehlgeschlagen: {path} -> {e}")
    return False

def _load_med_terms(path="medical_terms_de.txt"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except Exception:
        return []

def _match_case(src: str, cand: str) -> str:
    # Groß-/Kleinschreibung vom Originalwort übernehmen
    if src.isupper(): return cand.upper()
    if src.istitle(): return cand[:1].upper() + cand[1:]
    if src.islower(): return cand.lower()
    return cand

def med_postprocess(text: str, terms=None, cutoff=0.90) -> str:
    import re
    replaced = 0
    if terms is None:
        terms = _load_med_terms()
    if not terms:
        return text

    tokens = re.findall(r"\w+|[^\w\s]+|\s+", text, flags=re.UNICODE)
    out = []
    for tok in tokens:
        if tok.strip() and tok.isalpha() and len(tok) >= 4:  # Mini-Filter
            if 'USE_RAPIDFUZZ' in globals() and USE_RAPIDFUZZ:
                from rapidfuzz import process, fuzz
                cand = process.extractOne(tok, terms, scorer=fuzz.WRatio)
                if cand and (cand[1] / 100.0) >= cutoff:
                    out.append(_match_case(tok, cand[0]))
                    replaced += 1
                else:
                    out.append(tok)
            else:
                from difflib import get_close_matches
                m = get_close_matches(tok, terms, n=1, cutoff=cutoff)
                if m:
                    out.append(_match_case(tok, m[0]))
                    replaced += 1
                else:
                    out.append(tok)
        else:
            out.append(tok)

    result = "".join(out)
    try:
        print(f"🔎 med_postprocess: backend={'rapidfuzz' if USE_RAPIDFUZZ else 'difflib'}, terms={len(terms)}, replacements={replaced}")
    except Exception:
        pass
    return result

def preprocess_audio_chunk_soft(input_path: str, output_path: str, timeout: int = 20) -> str:
    """
    Schonende Normalisierung für *Live-Chunks*:
    - KEIN silenceremove!
    - Nur HP/LP + milde Kompression
    - 16 kHz, Mono, PCM16
    """
    filt = "highpass=f=70,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2.0:attack=5:release=120:makeup=3"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-af", filt,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_path
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="ignore") or "ffmpeg failed")
    return output_path

# ==== Whisper model selection helpers ====
WHISPER_MODELS_DIR = os.getenv("WHISPER_MODELS_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "whisper.cpp", "models"))
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

def _load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ settings.json write failed:", e)

def get_current_whisper_model_path():
    # priority: session -> settings.json -> utils default
    p = session.get("whisper_model_path")
    if p and os.path.exists(p):
        return p
    cfg = _load_settings()
    p = cfg.get("whisper_model_path")
    if p and os.path.exists(p):
        return p
    return MODEL_PATH  # from utils.py

def list_available_models():
    import re
    def encoder_candidates(dirpath, base_name):
        # remove quant suffixes like -q5_0 / -q8_0 / -Q5_K_M at the end
        b = base_name
        b = re.sub(r'-(?:q\d+(?:_\d+)?|Q\d+(?:_[A-Za-z0-9]+)*)$', '', b)
        # map large-v3-turbo -> large-v3
        b = b.replace('large-v3-turbo-q5_0', 'large-v3')
        cand = [os.path.join(dirpath, f"{b}-encoder.mlmodelc")]
        return cand

    models = []
    search_dirs = []
    if os.path.isdir(WHISPER_MODELS_DIR):
        search_dirs.append(WHISPER_MODELS_DIR)
    try:
        d = os.path.dirname(MODEL_PATH)
        if os.path.isdir(d) and d not in search_dirs:
            search_dirs.append(d)
    except Exception:
        pass

    exts = (".bin", ".gguf")
    seen = set()
    for d in search_dirs:
        try:
            for name in sorted(os.listdir(d)):
                if not name.startswith("ggml-"):
                    continue
                if not name.endswith(exts):
                    continue
                full = os.path.join(d, name)
                base = os.path.splitext(name)[0]  # ggml-medium-q8_0
                if full in seen:
                    continue
                seen.add(full)
                # exact encoder
                exact_enc = os.path.join(d, f"{base}-encoder.mlmodelc")
                has_coreml = os.path.isdir(exact_enc)
                enc_used = exact_enc if has_coreml else None
                # family-mapped encoder (e.g., ggml-medium-encoder.mlmodelc)
                if not has_coreml:
                    for cand in encoder_candidates(d, base):
                        if os.path.isdir(cand):
                            has_coreml = True
                            enc_used = cand
                            break
                models.append({
                    "name": name,
                    "path": full,
                    "dir": d,
                    "has_coreml": bool(has_coreml),
                    "encoder_path": enc_used,
                })
        except Exception as e:
            print("list_available_models error:", e)
    return models
app.secret_key = "dein-geheimer-key"

DEFAULT_LMMODEL_NAME = 'mistral'

TRANSKRIPT_DIR = os.path.join(os.getcwd(), "transkripte")
UPLOAD_FOLDER = "uploads"

# Live-Streaming Session State
SESSION_TRANSCRIPTS = {}
SESSION_TEXT = {}                      # session_id -> kumulativer Text (für UI)
SESSION_CHUNK_IDX = defaultdict(int)   # session_id -> laufende Nummer
SESSION_CHUNK_WAVS = defaultdict(list) # session_id -> Liste der absoluten Chunk-WAV-Pfade

# Limits & Timeouts
FFMPEG_TIMEOUT = 15         # Sekunden pro ffmpeg-Aufruf
MAX_SESSION_TEXT = 20000    # Zeichen (UI bremst sonst aus)
OVERLAP_TRIM_MS = int(os.getenv("OVERLAP_TRIM_MS", "700"))


os.makedirs(TRANSKRIPT_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --------- Settings-Helpers (Datei-basiert) ---------
SETTINGS_PATH = os.path.join(os.getcwd(), "settings.json")

def _load_settings_json() -> dict:
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("⚠️ Konnte settings.json nicht laden:", e)
    return {}

def _save_settings_json(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ Konnte settings.json nicht schreiben:", e)

def load_setting(key: str, default=None):
    data = _load_settings_json()
    return data.get(key, default)

def save_setting(key: str, value) -> None:
    data = _load_settings_json()
    data[key] = value
    _save_settings_json(data)

def read_file_safely(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def save_file_safely(path: str, content: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content or "")
    except Exception as e:
        print(f"⚠️ Konnte Datei nicht speichern ({path}):", e)

def lm_base_url(gen_url: str) -> str:
    try:
        if "/api/" in gen_url:
            return gen_url.split("/api/")[0]
        return gen_url.rstrip("/")
    except Exception:
        return gen_url.rstrip("/")

def list_ollama_models(gen_url: str) -> list[str]:
    """
    Fragt eine Ollama/LM-Studio-kompatible Instanz nach verfügbaren Modellen.
    Erwartet GET {base}/api/tags → { "models": [{"name": "..."}] }.
    """
    base = lm_base_url(gen_url)
    url = f"{base}/api/tags"
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        models = data.get("models", [])
        names = []
        for m in models:
            name = m.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names
    except Exception:
        return []
        

def preprocess_audio(input_path: str, output_path: str, timeout: int = 30) -> str:
    """
    Robuste Sprach-Vorverarbeitung mit Fallbacks.
    """
    import os
    import subprocess

    # 1) Zielordner sicherstellen
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    # 2) Filterketten (von "gut" -> "sehr kompatibel")
    filter_variants = [
        # V1: bevorzugt – behutsam, mit alimiter
        "highpass=f=70,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2.5:attack=5:release=120:makeup=3,alimiter=limit=0.98,"
        "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB:"
        "stop_periods=1:stop_duration=0.8:stop_threshold=-40dB",
        # V2: ohne alimiter (manche FFmpeg-Builds haben das Filter nicht)
        "highpass=f=70,lowpass=f=12000,acompressor=threshold=-18dB:ratio=2.5:attack=5:release=120:makeup=3,"
        "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB:"
        "stop_periods=1:stop_duration=0.8:stop_threshold=-40dB",
        # V3: minimal-kompatibel (nur HP/LP + silenceremove)
        "highpass=f=70,lowpass=f=12000,"
        "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB:"
        "stop_periods=1:stop_duration=0.8:stop_threshold=-40dB",
        # V4: nur Resample (gar keine Filter) – als letzte Rückfallebene
        None,
    ]

    last_error = None
    for filt in filter_variants:
        try:
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", input_path,
            ]
            if filt:
                cmd += ["-af", filt]
            # Ziel: WAV 16 kHz mono PCM16
            cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path]

            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
            if proc.returncode == 0:
                return output_path
            last_error = proc.stderr.decode(errors="ignore")
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(f"ffmpeg preprocessing failed (all variants): {last_error}")


def find_vtt_for_basename(base, dirpath):
    c1 = os.path.join(dirpath, f"{base}.wav.vtt")
    c2 = os.path.join(dirpath, f"{base}.vtt")
    if os.path.exists(c1):
        return c1
    if os.path.exists(c2):
        return c2
    # Fallback: alles, was mit base beginnt und .vtt endet
    matches = sorted(glob.glob(os.path.join(dirpath, f"{base}*.vtt")))
    return matches[0] if matches else None
    
def replace_umlaute(text):
    return (
        text.replace("Ä", "A").replace("Ö", "O").replace("Ü", "U")
            .replace("ä", "a").replace("ö", "o").replace("ü", "u")
            .replace("ß", "ss")
            .replace("™", "O")
    )

def map_geschlecht(code):
    return {
        "1": "männlich",
        "2": "weiblich",
        "3": "divers",
        "0": "unbekannt"
    }.get(code, "unbekannt")

def extract_patient_data_from_gdt(gdt_path):
    patientennr, vorname, nachname = "", "", ""
    try:
        with open(gdt_path, 'r', encoding='cp850', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line[3:7] == "3000":
                    patientennr = line[7:].strip()
                elif line[3:7] == "3102":
                    vorname = line[7:].strip()
                elif line[3:7] == "3101":
                    nachname = line[7:].strip()
                elif line[3:7] == "3110":
                    Geschlechtsnummer = line[7].strip()

        if not (vorname and nachname and patientennr):
            raise ValueError("Unvollständige GDT-Daten")

        vorname_clean = replace_umlaute(vorname)
        nachname_clean = replace_umlaute(nachname)
        initialen = (vorname_clean[0] + nachname_clean[0])

        geschlecht = map_geschlecht(Geschlechtsnummer)
        return initialen.upper(), patientennr, geschlecht

    except Exception:
        return "XX", "999999", "unbekannt"

# =========================================================
# NEU: Live-Streaming-Transkription
# =========================================================

def _prefer_full_text(final_txt: str, live_txt: str) -> str:
    """Bewahrt guten Live-Text, falls der finale Dialog zu kurz/fragwürdig ist."""
    f = (final_txt or "").strip()
    l = (live_txt or "").strip()
    if not l:
        return f
    # Final akzeptieren, wenn lang genug: >= 20 Zeichen oder >= 60% des Live-Texts
    if len(f) >= max(20, int(len(l) * 0.6)):
        return f
    return l
    
def dedupe_sentences(text: str) -> str:
    """
    Entfernt direkt aufeinanderfolgende Dopplungen/Varianten auf Satzebene.
    Sehr defensiv, damit nichts Gutes verloren geht.
    """
    import re
    from difflib import SequenceMatcher

    s = (text or "").strip()
    if not s:
        return s
    # Sätze naiv splitten (nach ., !, ?)
    sents = re.split(r'(?<=[\.\!\?])\s+', s)
    out = []
    last_norm = None

    for sent in sents:
        t = sent.strip()
        if not t:
            continue
        norm = re.sub(r'[\s,.;:]+', ' ', t).strip().lower()
        # mit letztem Satz vergleichen
        if last_norm:
            sim = SequenceMatcher(None, norm, last_norm).ratio()
            if norm == last_norm or sim > 0.92:
                continue
        out.append(t)
        last_norm = norm

    return "\n".join(out)

def merge_with_overlap(prev: str, new: str, lookback: int = 400, min_overlap: int = 16) -> str:
    """
    Führt prev + new zusammen, indem es den besten Suffix/Prefix-Overlap (bis lookback Zeichen)
    sucht und doppelte Passagen vermeidet. Gut für Live-Text mit Audio-Overlap.
    """
    prev = prev or ""
    new  = (new or "").strip()
    if not new:
        return prev

    import difflib
    tail = prev[-lookback:] if prev else ""
    if tail.endswith(new):
        return prev

    sm = difflib.SequenceMatcher(a=tail, b=new, autojunk=False)
    match = sm.find_longest_match(0, len(tail), 0, len(new))
    if match.size >= min_overlap:
        add = new[match.b + match.size:]
        return (prev + add).strip()

    sep = "" if (not prev or prev.endswith((" ", "\n"))) else " "
    return (prev + sep + new).strip()

@app.route('/start_stream')
def start_stream():
    # (7) Robuste Session-Initialisierung / Reset
    session_id = str(uuid.uuid4())
    SESSION_TRANSCRIPTS.pop(session_id, None)
    SESSION_TEXT.pop(session_id, None)
    SESSION_CHUNK_IDX.pop(session_id, None)
    SESSION_CHUNK_WAVS.pop(session_id, None)
    # (Optional) man könnte hier alte Sessions aufräumen – lassen wir bewusst weg
    return jsonify({'session_id': session_id})

@app.route('/stream_chunk', methods=['POST'])
def stream_chunk():
    session_id = request.form.get('session_id')
    if not session_id:
        return jsonify({'error': 'No session_id provided'}), 400

    blob = request.files.get('audio_chunk')
    if not blob:
        return jsonify({'error': 'No audio_chunk provided'}), 400

    # Client kann uns die Endung schicken (webm/ogg/m4a/mp4/wav)
    ext = (request.form.get('ext') or os.path.splitext(blob.filename)[1].lstrip('.')).lower()
    if ext not in ('webm', 'ogg', 'm4a', 'mp4', 'wav'):
        ext = 'webm'

    try:
        SESSION_CHUNK_IDX[session_id] += 1
        idx = SESSION_CHUNK_IDX[session_id]

        # 1) Chunk speichern (immer als "raw", damit Input != Output ist – auch bei WAV)
        in_name = f"{session_id}_{idx}.raw.{ext}"           # <<— immer anderer Dateiname als Ziel
        tmp_in  = os.path.abspath(os.path.join(UPLOAD_FOLDER, in_name))
        with open(tmp_in, 'wb') as f:
            f.write(blob.read())

        # 2) Normalize -> WAV (16 kHz, Mono, PCM16)
        tmp_wav = os.path.abspath(os.path.join(UPLOAD_FOLDER, f"{session_id}_{idx}.wav"))
        ffmpeg_cmd = (
            f'ffmpeg -y -hide_banner -loglevel error '
            f'-i {shlex.quote(tmp_in)} '
            f'-ac 1 -ar 16000 -c:a pcm_s16le '
            f'{shlex.quote(tmp_wav)}'
        )
        try:
            proc = subprocess.run(
                ffmpeg_cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=FFMPEG_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            print(f"⚠️ ffmpeg Timeout bei Chunk {idx}")
            current_total = SESSION_TEXT.get(session_id, "")
            return jsonify({'partial_transcript': current_total, 'seq': idx, 'warning': 'ffmpeg_timeout'})

        if proc.returncode != 0 or not os.path.exists(tmp_wav):
            err = proc.stderr.decode(errors='ignore')
            print(f"⚠️ ffmpeg-Fehler bei Chunk {idx}: {err}")
            current_total = SESSION_TEXT.get(session_id, "")
            return jsonify({'partial_transcript': current_total, 'seq': idx, 'warning': 'ffmpeg_failed'})

        # Roh-Upload weg
        try: os.remove(tmp_in)
        except Exception: pass

        # >>> NEU: Soft-Preprocessing *vor* dem Append und genau *das* in die Liste
        clean_wav = tmp_wav.replace(".wav", "_clean.wav")
        try:
            preprocess_audio_chunk_soft(tmp_wav, clean_wav, timeout=FFMPEG_TIMEOUT)
            use_wav = clean_wav
            # Optional: raw tmp_wav entsorgen, spart Platz
            try: os.remove(tmp_wav)
            except Exception: pass
        except Exception as e:
            print(f"⚠️ Preprocess failed for chunk {idx}: {e}")
            use_wav = tmp_wav  # Fallback

        # WICHTIG: jetzt das *verwendete* WAV merken
        SESSION_CHUNK_WAVS[session_id].append(use_wav)

        # 3) Chunk transkribieren (auf use_wav)
        try:
            chunk_text, _, _ = transcribe_with_whispercpp(use_wav, model_path=get_current_whisper_model_path(), write_outputs=False)
        except TypeError:
            chunk_text, _, _ = transcribe_with_whispercpp(use_wav, model_path=get_current_whisper_model_path())
        chunk_text = (chunk_text or "").strip()

        # 4) Live-Text per Overlap mergen
        prev = SESSION_TEXT.get(session_id, "")
        new_total = merge_with_overlap(prev, chunk_text, lookback=400, min_overlap=16)
        if len(new_total) > MAX_SESSION_TEXT:
            new_total = new_total[-MAX_SESSION_TEXT:]
        SESSION_TEXT[session_id] = new_total

        return jsonify({'partial_transcript': new_total, 'seq': idx})


    except Exception as e:
        print("❌ stream_chunk exception:", str(e))
        return jsonify({'error': str(e)}), 500

# =========================================================
# Klassischer Workflow
# =========================================================

@app.route('/', methods=['GET', 'POST'])
def index():
    lmmodel_name = session.get('lmmodel_name') or DEFAULT_LMMODEL_NAME
    gdt_path = "GDT/AuriT2MD.gdt"
    initialen, patientennr, geschlecht = extract_patient_data_from_gdt(gdt_path)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    basename = f"{initialen}_{patientennr}_{timestamp}"
    
    if request.method == 'POST':
        file = request.files.get('audiofile')
        if file and file.filename:
            # 1) Upload mit Original-Endung speichern (mp3/wav/m4a/ogg/webm)
            orig_ext = os.path.splitext(file.filename)[1].lower()
            allowed = {'.wav', '.mp3', '.m4a', '.ogg', '.webm'}
            if orig_ext not in allowed:
                flash(f"Nicht unterstütztes Format: {orig_ext}", "error")
                return render_template("index.html", grouped_transkripte=group_transkripte_by_date())

            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{basename}{orig_ext}")
            file.save(upload_path)

            # 2) Schonende Normalisierung nach 16 kHz/Mono/PCM16 (ohne silenceremove)
            clean_wav = os.path.join(app.config['UPLOAD_FOLDER'], f"{basename}.wav")
            try:
                preprocess_audio_chunk_soft(upload_path, clean_wav, timeout=FFMPEG_TIMEOUT)
                wav_for_asr = clean_wav
            except Exception as e:
                print("⚠️ Soft-Preprocess fehlgeschlagen, nutze Upload direkt:", e)
                wav_for_asr = upload_path

            # 3) Transkription – **nur einmal**, auf der bereinigten Datei
            start_processing = datetime.now()
            transcript, _, blocks = transcribe_with_whispercpp(
                wav_for_asr,
                model_path=get_current_whisper_model_path(),
                write_outputs=True,
                output_dir=TRANSKRIPT_DIR,
                output_basename=basename  # erzeugt z.B. transkripte/<basename>.wav.vtt
            )

            # 4) Sprecher-Zuweisung / Dialog
            diarization = session.get("diarization", "llm")
            if diarization == "off":
                dialog = "\n".join([b["text"] for b in blocks])
            elif diarization == "llm":
                dialog = "\n".join(assign_speakers_llm(blocks, lmmodel_name))
            else:
                dialog = "\n".join([f"Unbekannt: {b.get('text', '')}" for b in blocks])
            
            # 4.1)Fuzzy Match
            dialog = med_postprocess(dialog)  # sanfte Fachwort-Korrektur
            anamnese = summarize_with_lmstudio(dialog, geschlecht, lmmodel_name)
            
            # 5) Zusammenfassung
            if dialog.strip():
                anamnese = summarize_with_lmstudio(dialog, geschlecht, lmmodel_name)
            else:
                anamnese = "⚠️ Keine Sprachaufnahme erkannt – keine Zusammenfassung möglich."

            # 6) Speichern
            os.makedirs(TRANSKRIPT_DIR, exist_ok=True)
            with open(os.path.join(TRANSKRIPT_DIR, f"{basename}_anamnese.txt"), 'w', encoding='utf-8') as f:
                f.write(anamnese)
            with open(os.path.join(TRANSKRIPT_DIR, f"{basename}_transkript.txt"), 'w', encoding='utf-8') as f:
                f.write(dialog)

            # 7) GDT & Meta
            if os.path.exists(gdt_path):
                os.remove(gdt_path)
            processing_duration = round((datetime.now() - start_processing).total_seconds(), 1)
            meta_path = os.path.join(TRANSKRIPT_DIR, f"{basename}.meta.json")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump({"verarbeitungsdauer": processing_duration}, f)

            return render_template(
                "result.html",
                dialog=dialog,
                anamnese=anamnese,
                filename=f"{basename}_anamnese.txt",
                grouped_transkripte=group_transkripte_by_date()
            )

    # GET
    return render_template("index.html", grouped_transkripte=group_transkripte_by_date())


@app.route("/upload_audio", methods=["POST"])
def upload_audio():
    from flask import abort
    return abort(404)


@app.route('/transkript/<filename>')
def load_anamnese(filename):
    filepath = os.path.join(TRANSKRIPT_DIR, filename)
    if not os.path.exists(filepath):
        return "❌ Datei nicht gefunden", 404
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    return render_template("result.html", anamnese=content, filename=filename, grouped_transkripte=group_transkripte_by_date(), saved=True)

@app.route('/save_anamnese', methods=['POST'])
def save_anamnese():
    try:
        text = request.form.get('anamnese')
        dialog = request.form.get('dialog', '')
        filename = request.form.get('filename')

        if not text:
            return jsonify({"error": "Kein Anamnese-Text empfangen"}), 400

        if not filename:
            filename = "dummy_anamnese.txt"

        filepath = os.path.join(TRANSKRIPT_DIR, filename)
        os.makedirs(TRANSKRIPT_DIR, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)

        if dialog:
            diag_filename = filename.replace("_anamnese.txt", "_transkript.txt")
            diag_path = os.path.join(TRANSKRIPT_DIR, diag_filename)
            with open(diag_path, 'w', encoding='utf-8') as f:
                f.write(dialog)

        print("✅ Anamnese gespeichert:", filepath)
        return jsonify({"message": "Anamnese gespeichert", "filename": filename})

    except Exception as e:
        print("❌ Fehler beim Speichern:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route('/admin/<filename>')
def admin_view(filename):
    anamnese_path = os.path.join(TRANSKRIPT_DIR, filename)
    if not os.path.exists(anamnese_path):
        return "❌ Anamnese-Datei nicht gefunden", 404
    with open(anamnese_path, 'r', encoding='utf-8') as f:
        anamnese = f.read()

    diag_file = filename.replace("_anamnese.txt", "_transkript.txt")
    diag_path = os.path.join(TRANSKRIPT_DIR, diag_file)
    if os.path.exists(diag_path):
        with open(diag_path, 'r', encoding='utf-8') as f:
            dialog = f.read()
    else:
        dialog = "❌ Kein Sprecher-Transkript vorhanden."

    metadata = {
        "filename": filename,
        "modified": datetime.fromtimestamp(os.path.getmtime(anamnese_path)).strftime("%Y-%m-%d %H:%M"),
        "size_kb": round(os.path.getsize(anamnese_path) / 1024, 1)
    }

    start_time, end_time = None, None
    try:
        with open(os.path.join(TRANSKRIPT_DIR, diag_file), 'r', encoding='utf-8') as f:
            lines = f.readlines()
            times = []
            for line in lines:
                match = re.search(r"\(([\d\.]+)s\s*-\s*([\d\.]+)s\)", line)
                if match:
                    times.append((float(match.group(1)), float(match.group(2))))
            if times:
                start_time = min(t[0] for t in times)
                end_time = max(t[1] for t in times)
    except Exception:
        pass

    if start_time is not None and end_time is not None:
        gesprächsdauer = round(end_time - start_time, 1)
    else:
        gesprächsdauer = None

    try:
        erstellt = datetime.fromtimestamp(os.path.getctime(anamnese_path))
        bearbeitet = datetime.fromtimestamp(os.path.getmtime(anamnese_path))
        verarbeitungsdauer = round((bearbeitet - erstellt).total_seconds(), 1)
    except Exception:
        verarbeitungsdauer = None

    meta_path = os.path.join(TRANSKRIPT_DIR, filename.replace("_anamnese.txt", ".meta.json"))
    verarbeitungsdauer = "-"
    try:
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta_data = json.load(f)
                verarbeitungsdauer = meta_data.get("verarbeitungsdauer", "-")
    except Exception:
        pass

    audio_basename = filename.replace("_anamnese.txt", "")
    vtt_path = find_vtt_for_basename(audio_basename, TRANSKRIPT_DIR)

    if vtt_path and os.path.exists(vtt_path):
        gesprächsdauer = get_gespraechsdauer_from_vtt(vtt_path)
    else:
        print("VTT nicht gefunden für Gesprächsdauer. Probiert:",
          os.path.join(TRANSKRIPT_DIR, f"{audio_basename}.wav.vtt"),
          os.path.join(TRANSKRIPT_DIR, f"{audio_basename}.vtt"),
          os.path.join(TRANSKRIPT_DIR, f"{audio_basename}*.vtt"))
        gesprächsdauer = "-"


    return render_template(
        "admin.html",
        content=anamnese,
        dialog=dialog,
        metadata=metadata,
        filename=filename,
        model=session.get("lmmodel_name", 'mistral-small3.2:24b'),
        summarizer=session.get("summarizer", "local"),
        diarization=session.get("diarization", "llm"),
        grouped_transkripte=group_transkripte_by_date(),
        gesprächsdauer=gesprächsdauer,
        verarbeitungsdauer=verarbeitungsdauer
    )

@app.route("/delete_record", methods=["POST"])
def delete_record():
    basename = (request.form.get("basename") or "").strip()
    if not basename:
        return jsonify({"error": "basename missing"}), 400

    # sehr defensive Validierung (XX_999999_YYYYMMDD_HHMMSS)
    if not re.fullmatch(r"[A-Za-z]{2}_[0-9]+_\d{8}_\d{6}", basename):
        return jsonify({"error": "invalid basename"}), 400

    # Ziele zusammenstellen
    to_delete = [
        os.path.join(TRANSKRIPT_DIR, f"{basename}_anamnese.txt"),
        os.path.join(TRANSKRIPT_DIR, f"{basename}_transkript.txt"),
        os.path.join(TRANSKRIPT_DIR, f"{basename}.meta.json"),
        os.path.join(TRANSKRIPT_DIR, f"{basename}.wav.vtt"),
        os.path.join(TRANSKRIPT_DIR, f"{basename}.vtt"),
        os.path.join(UPLOAD_FOLDER,   f"{basename}.wav"),
        os.path.join(UPLOAD_FOLDER,   f"{basename}_clean.wav"),
    ]

    deleted, missing = [], []
    for p in to_delete:
        if _safe_unlink(p):
            deleted.append(p)
        else:
            if not os.path.exists(p):
                missing.append(p)

    # (optional) kurze Log-Ausgabe
    print(f"🗑️ delete_record({basename}): gelöscht={len(deleted)}, fehlten={len(missing)}")

    # UI: zurück auf Startseite + Nachricht
    try:
        flash(f"Datensatz {basename} gelöscht ({len(deleted)} Datei(en)).", "success")
    except Exception:
        pass
    return redirect(url_for("index"))


@app.route('/admin/')
def admin_index():
    return render_template("admin_index.html", grouped_transkripte=group_transkripte_by_date())

@app.route("/settings", methods=["GET", "POST"])
def settings():
    # Aktuelle Werte laden (je nachdem, wie du speicherst – hier als Beispiel aus Datei/ENV)
    current_model = load_setting("lmmodel_name", default="llama3.1:8b")  # <— deine Ladefunktion
    diarization   = load_setting("diarization", default="off")
    summarizer    = load_setting("summarizer", default="local")
    prompt_speaker= load_setting("prompt_speaker", default=read_file_safely("prompt_speaker.txt"))
    prompt_summary= load_setting("prompt_summary", default=read_file_safely("prompt_summary.txt"))

    # Modelle vom LLM-Server holen
    lm_url = os.getenv("LMSTUDIO_URL", "http://192.168.105.136:11434/api/generate")
    models = list_ollama_models(lm_url)

    if request.method == "POST":
        new_model      = request.form.get("lmmodel_name", "").strip()
        new_diar       = request.form.get("diarization", "off")
        new_summarizer = request.form.get("summarizer", "local")
        new_prompt_spk = request.form.get("prompt_speaker", "")
        new_prompt_sum = request.form.get("prompt_summary", "")

        # Validierung: Wenn Modelle bekannt sind, nur erlaubte speichern
        if models:
            if new_model not in models:
                # Fallback: nimm das erste vorhandene Modell und gib Hinweis
                fallback = models[0]
                flash(f"Modell „{new_model}“ nicht gefunden. Stattdessen „{fallback}“ gespeichert.", "warning")
                new_model = fallback
        else:
            # Kein /api/tags verfügbar – speichere trotzdem, aber Hinweis
            flash("Konnte die Modellliste nicht abrufen. Stelle sicher, dass dein LLM-Server läuft.", "warning")

        # Speichern (passe an deine Persistence an)
        save_setting("lmmodel_name", new_model)
        save_setting("diarization", new_diar)
        save_setting("summarizer", new_summarizer)
        save_file_safely("prompt_speaker.txt", new_prompt_spk)
        save_file_safely("prompt_summary.txt", new_prompt_sum)
        
        # Session sofort aktualisieren, damit index/upload/process_stream das neue Modell sehen
        session["lmmodel_name"] = new_model
        session["diarization"] = new_diar
        session["summarizer"] = new_summarizer


        return render_template(
            "settings.html",
            saved=True,
            lmmodel_name=new_model,
            diarization=new_diar,
            summarizer=new_summarizer,
            prompt_speaker=new_prompt_spk,
            prompt_summary=new_prompt_sum,
            models=models
        )

    # GET – Seite anzeigen
    return render_template(
        "settings.html",
        saved=False,
        lmmodel_name=current_model,
        diarization=diarization,
        summarizer=summarizer,
        prompt_speaker=prompt_speaker,
        prompt_summary=prompt_summary,
        models=models
    )


def group_transkripte_by_date():
    groups = defaultdict(list)
    now = datetime.now()

    for file in os.listdir(TRANSKRIPT_DIR):
        if not file.endswith("_anamnese.txt"):
            continue
        try:
            parts = file.split("_")
            initialen = parts[0]
            patientennr = parts[1]
            timestamp_str = parts[2] + "_" + parts[3]
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")

            delta = (now.date() - timestamp.date()).days
            if delta == 0:
                group = "Heute"
            elif delta == 1:
                group = "Gestern"
            elif delta == 2:
                group = "Vorgestern"
            else:
                group = "Ältere"

            label = f"{initialen[0]}.{initialen[1]}. {patientennr}"
            groups[group].append((file, label, timestamp))
        except Exception:
            continue

    for group in groups:
        groups[group].sort(key=lambda x: x[2], reverse=True)

    cleaned_groups = {
        group: [(file, label) for file, label, _ in items]
        for group, items in groups.items()
    }

    group_order = {"Heute": 0, "Gestern": 1, "Vorgestern": 2, "Ältere": 3}
    return dict(sorted(cleaned_groups.items(), key=lambda g: group_order.get(g[0], 99)))

@app.route('/process_stream', methods=['POST'])
def process_stream():
    start_processing = datetime.now()

    lmmodel_name = session.get('lmmodel_name') or DEFAULT_LMMODEL_NAME
    session_id = request.form.get('session_id')
    if not session_id:
        return jsonify({"error": "Keine Session-ID übergeben"}), 400
    live_text = SESSION_TEXT.get(session_id, "") or ""

    # GDT lesen + Ziel-Basisname bauen
    gdt_path = "GDT/AuriT2MD.gdt"
    initialen, patientennr, geschlecht = extract_patient_data_from_gdt(gdt_path)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    basename = f"{initialen}_{patientennr}_{timestamp}"

    # Chunks einsammeln (concat)
    chunk_wavs = SESSION_CHUNK_WAVS.get(session_id, [])
    if not chunk_wavs:
        legacy_wav = os.path.abspath(os.path.join(UPLOAD_FOLDER, f"{session_id}.wav"))
        if not os.path.exists(legacy_wav):
            return jsonify({"error": "Keine Audio-Chunks gefunden"}), 404
        chunk_wavs = [legacy_wav]

    # NEU: Overlap der Audio-Chunks entfernen (alles außer dem ersten um OVERLAP_TRIM_MS kürzen)
    trimmed_chunks = []
    temp_trims = []
    if OVERLAP_TRIM_MS > 0 and len(chunk_wavs) > 1:
        tsec = OVERLAP_TRIM_MS / 1000.0
        for i, p in enumerate(chunk_wavs):
            if i == 0:
                trimmed_chunks.append(p)
                continue
            p_trim = os.path.abspath(p.replace(".wav", "_trim.wav"))
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", p,
                "-af", f"atrim=start={tsec:.3f},asetpts=PTS-STARTPTS",
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                p_trim
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0 and os.path.exists(p_trim) and os.path.getsize(p_trim) > 0:
                trimmed_chunks.append(p_trim)
                temp_trims.append(p_trim)
            else:
                # Fallback: ungeschnitten übernehmen
                trimmed_chunks.append(p)
    else:
        trimmed_chunks = list(chunk_wavs)

    concat_list_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, f"{session_id}_concat_list.txt"))
    with open(concat_list_path, 'w', encoding='utf-8') as f:
        for p in trimmed_chunks:
            f.write(f"file '{os.path.abspath(p)}'\n")


    concat_out = os.path.abspath(os.path.join(UPLOAD_FOLDER, f"{session_id}_concat.wav"))
    proc1 = subprocess.run(
        f'ffmpeg -y -f concat -safe 0 -i {shlex.quote(concat_list_path)} -c copy {shlex.quote(concat_out)}',
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc1.returncode != 0 or not os.path.exists(concat_out):
        print("❌ ffmpeg concat failed:", proc1.stderr.decode(errors='ignore'))
        return jsonify({"error": "Concat fehlgeschlagen"}), 500

    final_wav = os.path.abspath(os.path.join(UPLOAD_FOLDER, f"{session_id}.wav"))
    proc2 = subprocess.run(
        f'ffmpeg -y -i {shlex.quote(concat_out)} -ar 16000 -ac 1 {shlex.quote(final_wav)}',
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc2.returncode != 0 or not os.path.exists(final_wav):
        print("❌ ffmpeg resample failed:", proc2.stderr.decode(errors='ignore'))
        return jsonify({"error": "Resample fehlgeschlagen"}), 500

    # NEU: Gesamtdatei vorverarbeiten
    final_wav_clean = final_wav.replace(".wav", "_clean.wav")
    try:
        preprocess_audio_chunk_soft(final_wav, final_wav_clean, timeout=FFMPEG_TIMEOUT)
        wav_for_asr = final_wav_clean
    except Exception as e:
        print("⚠️ Preprocess (soft) failed, fallback:", e)
        wav_for_asr = final_wav


    # === Finale Transkription (hast du schon) ===
    transcript, _, blocks = transcribe_with_whispercpp(
        wav_for_asr, model_path=get_current_whisper_model_path(),
        write_outputs=True, output_dir=TRANSKRIPT_DIR, output_basename=session_id
    )

    # Finaltext bilden
    final_txt = (transcript or "").strip()
    if not final_txt and blocks:
        final_txt = "\n".join([b.get("text","") for b in blocks]).strip()

    # NEU: Nur finalen Text verwenden – dedupliziert
    dialog = dedupe_sentences(final_txt)

    # Fallback: falls final wider Erwarten leer/zu kurz ist
    if len(dialog) < 20 and live_text:
        dialog = dedupe_sentences(live_text)


    # VTT suchen (mit Polling), dann auf <basename>.wav.vtt umbenennen
    dst_vtt = os.path.join(TRANSKRIPT_DIR, f"{basename}.wav.vtt")
    candidates = [
        os.path.join(TRANSKRIPT_DIR, f"{session_id}.wav.vtt"),   # erwartete Datei nach obigem Aufruf
        os.path.join(TRANSKRIPT_DIR, f"{session_id}.vtt"),        # falls .wav.vtt nicht genutzt wurde
        os.path.join(TRANSKRIPT_DIR, f"{basename}.wav.vtt"),      # falls utils doch schon basename schrieb
        os.path.join(TRANSKRIPT_DIR, f"{basename}.vtt"),
        os.path.join(UPLOAD_FOLDER,  f"{session_id}.wav.vtt"),    # Fallbacks
        os.path.join(UPLOAD_FOLDER,  f"{session_id}.vtt"),
        final_wav + ".vtt",
    ]

    src_vtt = None
    deadline = time.time() + 5.0  # etwas großzügiger warten
    while time.time() < deadline and src_vtt is None:
        for cand in candidates:
            if os.path.exists(cand):
                src_vtt = cand
                break
        if src_vtt is None:
            time.sleep(0.2)

    if src_vtt:
        try:
            if os.path.abspath(src_vtt) != os.path.abspath(dst_vtt):
                shutil.move(src_vtt, dst_vtt)
            print(f"✅ VTT bereit: {dst_vtt}")
        except Exception as e:
            print(f"⚠️ Konnte VTT nicht verschieben/umbenennen: {e}")
            dst_vtt = src_vtt
    else:
        print(f"⚠️ VTT nicht gefunden. Gesuchte Kandidaten: {candidates}")
        dst_vtt = None

    # Dialog aus Blocks (Fallback: gesamter Text) + Plausibilitäts-Check ggü. Live-Text
    final_txt = (transcript or "").strip()
    if not final_txt and blocks:
        final_txt = "\n".join([b.get("text","") for b in blocks]).strip()

    # Live + Final per Overlap zusammenführen
    dialog = merge_with_overlap(live_text, final_txt, lookback=800, min_overlap=10)
    if not dialog.strip():  # Fallback, falls etwas schiefgeht
        dialog = final_txt or live_text

    # Fuzzy-Match
    dialog = med_postprocess(dialog)
    anamnese = summarize_with_lmstudio(dialog, geschlecht, lmmodel_name)

    # Zusammenfassung
    if dialog.strip():
        anamnese = summarize_with_lmstudio(dialog, geschlecht, lmmodel_name)
    else:
        anamnese = "⚠️ Keine Sprachaufnahme erkannt – keine Zusammenfassung möglich."


    # Gesprächsdauer
    if dst_vtt and os.path.exists(dst_vtt):
        gesprächsdauer = get_gespraechsdauer_from_vtt(dst_vtt)
    else:
        gesprächsdauer = "-"

    # Speichern
    with open(os.path.join(TRANSKRIPT_DIR, f"{basename}_anamnese.txt"), 'w', encoding='utf-8') as f:
        f.write(anamnese)
    with open(os.path.join(TRANSKRIPT_DIR, f"{basename}_transkript.txt"), 'w', encoding='utf-8') as f:
        f.write(dialog)

    processing_duration = round((datetime.now() - start_processing).total_seconds(), 1)
    with open(os.path.join(TRANSKRIPT_DIR, f"{basename}.meta.json"), 'w', encoding='utf-8') as f:
        json.dump({"verarbeitungsdauer": processing_duration}, f)

    # Cleanup
    try:
        if os.path.exists(concat_list_path): os.remove(concat_list_path)
        if os.path.exists(concat_out): os.remove(concat_out)
        for p in chunk_wavs:
            try: os.remove(p)
            except Exception: pass
    # NEU:
        for p in temp_trims:
            try: os.remove(p)
            except Exception: pass
    except Exception as e:
        print("⚠️ Cleanup Warnung:", e)


    SESSION_CHUNK_WAVS.pop(session_id, None)
    SESSION_CHUNK_IDX.pop(session_id, None)
    SESSION_TEXT.pop(session_id, None)
    if session_id in SESSION_TRANSCRIPTS:
        del SESSION_TRANSCRIPTS[session_id]

    if os.path.exists(gdt_path):
        os.remove(gdt_path)

    return jsonify({
        "dialog": dialog,
        "anamnese": anamnese,
        "filename": f"{basename}_anamnese.txt",
        "processing_duration": processing_duration,
        "gesprächsdauer": gesprächsdauer
    })


@app.route('/sidebar_reload')
def sidebar_reload():
    return render_template("sidebar.html", grouped_transkripte=group_transkripte_by_date())

# Starten


@app.route("/models")
def list_models_route():
    return jsonify({"models": list_available_models(), "current": get_current_whisper_model_path()})


@app.route("/set_model", methods=["POST"])
def set_model_route():
    # akzeptiere FormData, x-www-form-urlencoded oder JSON
    model_path = None
    try:
        if request.form:
            model_path = request.form.get("model_path") or model_path
        if not model_path and request.values:
            model_path = request.values.get("model_path")
        if not model_path:
            data = request.get_json(silent=True) or {}
            model_path = data.get("model_path")
        if not model_path:
            raw = (request.data or b"").decode("utf-8", errors="ignore").strip()
            if raw and (raw.endswith(".bin") or raw.endswith(".gguf")):
                model_path = raw
    except Exception:
        model_path = None

    if not model_path:
        return jsonify({"error": "model_path missing", "debug": {
            "content_type": request.content_type,
            "form_keys": list(request.form.keys()),
        }}), 400

    model_path = os.path.abspath(os.path.expanduser(model_path))
    if not os.path.exists(model_path):
        return jsonify({"error": f"model_path not found: {model_path}"}), 400

    session["whisper_model_path"] = model_path
    cfg = _load_settings()
    cfg["whisper_model_path"] = model_path
    _save_settings(cfg)
    return jsonify({"ok": True, "model_path": model_path})

    model_path = request.form.get("model_path") or request.json.get("model_path") if request.is_json else None
    if not model_path:
        return jsonify({"error": "model_path missing"}), 400
    if not os.path.exists(model_path):
        return jsonify({"error": f"model_path not found: {model_path}"}), 400

    # persist to session + settings.json
    session["whisper_model_path"] = model_path
    cfg = _load_settings()
    cfg["whisper_model_path"] = model_path
    _save_settings(cfg)
    return jsonify({"ok": True, "model_path": model_path})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001)   # kein ssl_context hier!



