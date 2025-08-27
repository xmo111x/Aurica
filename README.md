# Aurica – lokale Transkription & Zusammenfassung

Lokale Flask-Web-App zur Aufnahme, Transkription (whisper.cpp) und Zusammenfassung (LM Studio/Ollama).
Siehe `.env.example` und `requirements.txt`. Secrets/Transkripte werden per `.gitignore` ausgeschlossen.

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Pfade setzen
python app.py
```
