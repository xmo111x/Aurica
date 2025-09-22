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
### Erklärung

Hallo, dies ist mein erstes GitHub-Projekt. Ja, sogar mein erstes Projekt überhaupt. Man möge mir meine Fehler und Fauxpas verzeihen. Ich hoffe auf konstruktive Beiträge der Community und hoffe, dieses Projekt fortführen und verbessern zu können. Worum geht es? Es gibt schon einige Anbieter, die ein Arzt-Patienten-Gespräch aufzeichnen, transkribieren und zusammenfassen. Hier einige Anbieter:
Noa Notes
Eudaria
hedihealth
Via-health
PlaynVoice (eher diktieren als KI)
Doq Copilot
cgmone DokuAssistent
Jedoch stellt meiner Meinung nach die Cloudanbindung dieser Programme im medizinischen Bereich ein datenschutztechnisches NoGo dar. Meine Idee war es, diesen Prozess lokal laufen zu lassen. Hierfür habe ich auf einem Mac Mini mit M4 Pro Chip mit 14 Core CPU, 20 Core GPU, 16 Core Neutral Engine, 64 GB RAM und 1 TB SSD Ollama laufen. Als LLM nutze ich Mistral 7b, da dies schnell läuft und eine Apache-Lizenz hat. Im Backend läuft dieses Python-Programm. Ich greife im Netzwerk über das Frontend zu. Anfangs hatte ich noch mit einer gesonderten Sprechererkennung, erst mit Pyannote (Audio basiert) und dann über LLM versucht. Letztendlich habe ich es aber in ein Prompt zusammengefasst. Im Admin-Bereich sieht man noch weitere Informationen wie Verarbeitungszeit und Transkript. Auf der Hauptseite habe ich zwischen klassischen Mikroaufnahme und anschließendem Transkript und Livetranskript experimentiert. Bei meinen Versuchen stellt sich jedoch heraus, dass für meinen Anwendungsfall die Transkription bei der klassischen Aufnahme immer noch zu lange dauert. Zu guter Letzt will ich offen zugeben, dass meine Python-Kenntnisse nur marginal sind und ich größtenteils mit Hilfe von ChatGPT mühsam alles erarbeitet habe. Hier noch ein paar Screenshots.

<img width="2032" height="1213" alt="Bildschirmfoto 2025-08-27 um 16 58 39" src="https://github.com/user-attachments/assets/94156680-0c8c-47bd-aba8-820b97eefb50" />

<img width="2040" height="1213" alt="Bildschirmfoto 2025-08-27 um 16 58 56" src="https://github.com/user-attachments/assets/f26f78db-51c5-42ac-93f1-d68a023d108d" />


v2025_9_2.7 

Folgende Änderungen:

- Die Aufnahme mit Übertragung der .wav Datei nach Beendigung der Aufnahme zum Transkript und anschließende Übergabe an die KI zum zusammenfassen hat einfach zu lange gedauert sodass ich mich ab jetzt nur noch auf den Live Transkript konzentriere. Während der Aufnahme werden Chunks nach Heuristik erzeugt mit einer gewissen Überlappung so dass während der Aufnahme der Transkript erfolgt. Die Qualität des Transkript ist zwar minimal schlechter aber die gesamte Verarbeitungszeit ist deutlich schneller. 

- Der Transkript läuft über whisper.cpp mit ggml mit CoreML Unterstützung. Der beste Kompromiss zwischen Geschwindigkeit und Qualität ist bei mir ggml-medium.bin. Auch die quantisierten Modelle q5 und q8 sind gut. 

- Es gibt eine Live Simulation aus einer .wav Datei. Hierbei wird nicht einfach die .wav Datei hochgeladen (Wie bei Datei Upload ganz unten) sondern die Aufnahme mit Live Transkript simuliert. 

- Zur Verbesserung der Aufnahme nutze ich folgendes Tischmikrofon mit 4 Microfonen: beyerdynamic Space


Themen in Arbeit:

- Starten der Aufnahme über Gerätestart im PVS (T2med)

- 1 Klick Übernahme von Anamnese, Befund und Therapie mit automatischem Speichern der Änderungen in das PVS

- Benutzerstruktur aufbauen sodass mehrere Nutzer parallel arbeiten können. 




