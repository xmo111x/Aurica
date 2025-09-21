import subprocess
import os
import requests
import re
import shutil
import tempfile

# ── Neu: konfigurierbar per ENV (mit sinnvollen Defaults) ────────────────
MODEL_PATH = os.getenv("WHISPER_MODEL", os.path.abspath("/Users/Mesut/whisper_project/web_app/whisper.cpp/models/ggml-small-q8_0.bin"))
CLI_PATH   = os.getenv("WHISPER_CLI",   os.path.abspath("/Users/Mesut/whisper_project/web_app/whisper.cpp/build/bin/whisper-cli"))
DOMAIN_PROMPT = os.getenv("WHISPER_PROMPT", "").strip()

def _read_txt_fallback(stdout_text: str) -> str:
    """
    Fallback, falls keine .txt-Datei vorhanden ist:
    versuche, Text aus stdout zu gewinnen.
    """
    txt = (stdout_text or "").strip()
    # einfache, robuste Extraktion: entferne offensichtliches Logging
    txt = re.sub(r"(?i)^(processing|loading|using model).*?$", "", txt, flags=re.MULTILINE)
    return txt.strip()

def transcribe_with_whispercpp(
    audio_path: str,
    model_path: str = MODEL_PATH,
    lang: str = "de",
    write_outputs: bool = True,
    output_dir: str | None = None,
    output_basename: str | None = None,
    extra_args: list[str] | None = None,
):
    """
    Transkribiert mit whisper-cli.

    Args:
        audio_path: Eingabe-Audiodatei (wav/mp3/ogg/...)
        model_path: Pfad zum Model (GGUF empfohlen)
        lang: Sprachcode (z.B. 'de')
        write_outputs: Wenn True, schreibt .txt/.vtt. Wenn False, schreibt in temp-Dateien
                       (nur .txt) und löscht sie danach – ideal für Live-Chunks.
        output_dir: Zielordner für Outputs (wenn write_outputs=True). Default: Ordner von audio_path
        output_basename: Basisname ohne Endung für Outputs (wenn write_outputs=True).
                         Default: Name von audio_path ohne Endung.
        extra_args: zusätzliche CLI-Argumente (Liste), falls benötigt.

    Returns:
        (text, vtt_path, blocks)
        text: kompletter Text
        vtt_path: Pfad zur erzeugten VTT (falls vorhanden, sonst None)
        blocks: Liste von {"start": None, "end": None, "text": ...} (aus .txt-Zeilen)
    """
    cli_path = os.path.abspath(CLI_PATH)
    model_path = os.path.abspath(model_path)
    audio_path = os.path.abspath(audio_path)

    if not os.path.exists(cli_path):
        raise FileNotFoundError(f"whisper-cli nicht gefunden: {cli_path}")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model-Datei nicht gefunden: {model_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")

    cmd = [
        cli_path,
        "-m", model_path,
        "-f", audio_path,
        "-l", lang,
    ]

    # ── Neu: Defaults ergänzen (Beam-Search + optional Domain-Prompt) ─────────
    defaults = []
    beam_size = os.getenv("WHISPER_BEAM", "5")   # falls Build -bs unterstützt
    if beam_size:
        defaults += ["-bs", str(beam_size)]
    if DOMAIN_PROMPT:
        defaults += ["-p", DOMAIN_PROMPT]

    # Zusätzliche Args übernehmen (optional)
    if extra_args:
        cmd.extend(extra_args)
    # Defaults hinten anhängen
    if defaults:
        cmd.extend(defaults)

    # Output-Handling
    keep_files = False
    txt_path = None
    vtt_path = None

    if write_outputs:
        # Feste Output-Basis
        if output_dir is None:
            output_dir = os.path.dirname(audio_path)
        os.makedirs(output_dir, exist_ok=True)
        if output_basename is None:
            # Standard: gleicher Name wie Audio ohne Endung
            output_basename = os.path.splitext(os.path.basename(audio_path))[0]
        output_base = os.path.join(output_dir, output_basename)

        # .txt + .vtt erzeugen
        cmd.extend(["-otxt", "-ovtt", "-of", output_base])
        txt_path = output_base + ".txt"
        vtt_path = output_base + ".vtt"
        keep_files = True
    else:
        # Live-Chunk: minimaler IO – nur .txt schreiben, danach löschen
        # (Viele Builds unterstützen -otxt/-of.)
        tmp_dir = os.path.dirname(audio_path)  # landet i.d.R. in uploads/
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_base = os.path.join(tmp_dir, next(tempfile._get_candidate_names()))
        cmd.extend(["-otxt", "-of", tmp_base])
        txt_path = tmp_base + ".txt"
        vtt_path = tmp_base + ".vtt"  # falls die CLI doch eine VTT ablegt
        keep_files = False  # nach dem Lesen wieder löschen

    # Ausführen
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Versuche, nützlichen Fehler zu zeigen
        raise RuntimeError(f"whisper-cli Fehler:\ncmd: {' '.join(cmd)}\n{result.stderr}")

    text = ""
    blocks = []

    # Text aus Datei lesen oder Fallback stdout
    if txt_path and os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()
        # Blöcke pro Zeile (einfacher Fallback)
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            blocks.append({"start": None, "end": None, "text": line})
        text = content
    else:
        # Fallback: aus stdout bestmöglich extrahieren
        text = _read_txt_fallback(result.stdout)
        for line in text.splitlines():
            line = line.strip()
            if line:
                blocks.append({"start": None, "end": None, "text": line})

    # Aufräumen im Chunk-Mode
    if not keep_files:
        try:
            if txt_path and os.path.exists(txt_path):
                os.remove(txt_path)
        except Exception:
            pass
        try:
            if vtt_path and os.path.exists(vtt_path):
                os.remove(vtt_path)
        except Exception:
            pass

    # Nur zurückgeben, wenn eine echte VTT existiert
    vtt_path = vtt_path if (vtt_path and os.path.exists(vtt_path)) else None
    return text, vtt_path, blocks

def read_prompt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def assign_speakers_llm(blocks, lmmodel_name):
    """
    Weist Blöcken (Textzeilen) Sprecher zu ("Patient"/"Arzt") über einen lokalen LLM-Endpunkt.
    Robust gegen unterschiedliche JSON-Formate und API-Fehler.
    ENV:
      LMSTUDIO_URL (default: http://192.168.105.136:11434/api/generate)
      LMSTUDIO_TIMEOUT (Sekunden, default: 30)
    """
    url = os.getenv("LMSTUDIO_URL", "http://192.168.105.136:11434/api/generate")
    try:
        timeout = float(os.getenv("LMSTUDIO_TIMEOUT", "30"))
    except Exception:
        timeout = 30.0

    headers = {"Content-Type": "application/json"}
    speaker_prompt = read_prompt("prompt_speaker.txt")
    results = []
    last_speaker = None

    for i, block in enumerate(blocks):
        context = f"Vorheriger Satz:\n{blocks[i-1]['text']}\n\n" if i > 0 else ""
        prompt = speaker_prompt.format(context=context, sentence=block['text'])

        payload = {
            "model": lmmodel_name,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.0
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            try:
                obj = resp.json()
            except Exception:
                obj = {"error": f"Ungültige JSON-Antwort (HTTP {resp.status_code})", "raw": resp.text[:200]}

            if resp.status_code >= 400:
                msg = obj.get("error") or obj.get("message") or str(obj)
                raise RuntimeError(f"HTTP {resp.status_code}: {msg}")

            text = _extract_lm_text(obj) or ""
            low = text.lower()
            if "patient" in low:
                speaker = "Patient"
            elif "arzt" in low:
                speaker = "Arzt"
            else:
                speaker = "Patient" if last_speaker == "Arzt" else "Arzt"
        except Exception as e:
            speaker = f"Fehler: {e}"

        last_speaker = speaker
        results.append(f"{speaker}: {block['text']}")

    return results

    
def _extract_lm_text(obj: dict) -> str | None:
    """
    Versucht, aus diversen JSON-Formaten den Antworttext zu holen.
    Unterstützt: Ollama/LM Studio (response), OpenAI-like (choices[].message.content), u.a.
    """
    if not isinstance(obj, dict):
        return None

    # Häufige direkte Felder
    for key in ("response", "text", "output_text", "content"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # OpenAI-ähnlich
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            # message.content
            msg = c0.get("message")
            if isinstance(msg, dict):
                cont = msg.get("content")
                if isinstance(cont, str) and cont.strip():
                    return cont.strip()
            # delta.content (stream-end Zusammenfassung)
            delta = c0.get("delta")
            if isinstance(delta, dict):
                cont = delta.get("content")
                if isinstance(cont, str) and cont.strip():
                    return cont.strip()
            # text direkt in choice
            t = c0.get("text")
            if isinstance(t, str) and t.strip():
                return t.strip()

    # Manchmal liegt es unter data[0].text
    data = obj.get("data")
    if isinstance(data, list) and data:
        d0 = data[0]
        if isinstance(d0, dict):
            t = d0.get("text") or d0.get("content")
            if isinstance(t, str) and t.strip():
                return t.strip()

    return None

def summarize_with_lmstudio(transcript: str, geschlecht: str, lmmodel_name: str):
    """
    Fasst das Gespräch zusammen über einen lokalen LLM-Endpunkt.
    Robust gegen unterschiedliche JSON-Formate und Fehlermeldungen.
    Konfigurierbar per ENV:
      LMSTUDIO_URL (default: http://192.168.105.136:11434/api/generate)
      LMSTUDIO_TIMEOUT (Sekunden, default: 60)
    """
    import json

    summary_prompt = read_prompt("prompt_summary.txt")
    prompt = summary_prompt.format(dialog=transcript, geschlecht=geschlecht)

    url = os.getenv("LMSTUDIO_URL", "http://192.168.105.136:11434/api/generate")
    try:
        timeout = float(os.getenv("LMSTUDIO_TIMEOUT", "60"))
    except Exception:
        timeout = 60.0

    payload = {
        "model": lmmodel_name,
        "prompt": prompt,
        "stream": False,
        "temperature": 0.2
    }
    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        return f"Fehler bei Zusammenfassung: Verbindung fehlgeschlagen ({e})"

    # Versuche JSON zu parsen – sonst zeige Rohtext an
    try:
        obj = resp.json()
    except Exception:
        snippet = (resp.text or "").strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        return f"Fehler bei Zusammenfassung: Ungültige JSON-Antwort (HTTP {resp.status_code}): {snippet}"

    # API-spezifischer Fehler?
    if resp.status_code >= 400:
        err = obj.get("error") or obj.get("message") or str(obj)
        return f"Fehler bei Zusammenfassung: HTTP {resp.status_code}: {err}"

    text = _extract_lm_text(obj)
    if not text:
        # Letzte Rettung: alles als String
        try:
            text = json.dumps(obj, ensure_ascii=False)[:400]
        except Exception:
            text = str(obj)[:400]
        return f"Fehler bei Zusammenfassung: Unerwartetes Antwortformat. Inhalt: {text}"

    return text.strip()

def get_gespraechsdauer_from_vtt(vtt_path):
    last_end = 0.0
    with open(vtt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            # Beispiel: 00:00:00.000 --> 00:00:01.240
            match = re.search(r"-->\s*(\d{2}):(\d{2}):(\d{2}\.\d{3})", line)
            if match:
                h, m, s = match.groups()
                end_sec = int(h) * 3600 + int(m) * 60 + float(s)
                if end_sec > last_end:
                    last_end = end_sec
    return round(last_end, 1)
