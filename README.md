# Aurica – lokale Transkription & Zusammenfassung

Lokale Flask-Web-App zur Aufnahme, Transkription (whisper.cpp) und Zusammenfassung (LM Studio/Ollama).
Siehe `.env.example` und `requirements.txt`. Secrets/Transkripte werden per `.gitignore` ausgeschlossen.

# Installation


## Inhalt
- [Überblick](#überblick)
- [Systemvoraussetzungen](#systemvoraussetzungen)
- [Projektstruktur](#projektstruktur)
- [Konfiguration](#konfiguration)
- [Schnellstart (nur HTTP, Test)](#schnellstart-nur-http-test)
- [Produktionsbetrieb mit HTTPS](#produktionsbetrieb-mit-https)
  - [macOS – Variante A: Reverse‑Proxy auf 443 (Root) **einfach**](#macos--variante-a-reverseproxy-auf-443-root-einfach)
  - [macOS – Variante B: Reverse‑Proxy auf 8443 + Portumleitung 443→8443 (ohne Root)](#macos--variante-b-reverseproxy-auf-8443--portumleitung-4438443-ohne-root)
  - [Windows – Reverse‑Proxy auf 443](#windows--reverseproxy-auf-443)
- [App als Dienst starten](#app-als-dienst-starten)
  - [macOS: LaunchAgent (User‑Kontext)](#macos-launchagent-userkontext)
  - [Windows: Taskplaner oder NSSM](#windows-taskplaner-oder-nssm)
- [Zertifikate (lokal)](#zertifikate-lokal)
- [Troubleshooting](#troubleshooting)
- [Sicherheitshinweise](#sicherheitshinweise)

---

## Überblick
- Backend: **Flask** (Python). Standardmäßig läuft die App lokal unter `http://127.0.0.1:5001`.
- Frontend: Greift per Browser oder optionaler PyInstaller‑Client zu.
- KI‑Module:
  - **Whisper / whisper.cpp**: lokale Transkription (benötigt Modelldatei).
  - **Ollama** (optional): lokale LLM‑Generierung für Zusammenfassungen (Standard: `http://127.0.0.1:11434`).
- **Empfohlen**: Betrieb hinter einem Reverse‑Proxy (Nginx oder Caddy) mit HTTPS auf **Port 443** im LAN.

> **Wichtig:** Die App ist für **lokale Nutzung** vorgesehen. Kein öffentliches Expose ins Internet, außer du härtest das Setup separat ab.

---

## Systemvoraussetzungen
- **Python 3.10+** (empfohlen 3.11)
- **pip** & **venv**
- **Git** (für Clone)
- **Reverse‑Proxy** (eine Option):
  - macOS: **Homebrew + Nginx** (oder Caddy)
  - Windows: **Caddy** (empfohlen) oder **Nginx für Windows**
- **KI‑Komponenten (optional)**:
  - Whisper Modelldatei (`.bin` für whisper.cpp) – Pfad konfigurierbar
  - **Ollama** lokal installiert & gestartet, falls LLM‑Features genutzt werden

---

## Projektstruktur
```
web_app/
├─ app.py                 # Flask Einstiegspunkt
├─ requirements.txt       # Python-Abhängigkeiten
├─ settings.json          # App-Konfiguration (Pfade, Ports, Modelle)
├─ static/, templates/    # Frontend
├─ utils.py, ...          # Hilfsfunktionen (Whisper/Ollama)
└─ certs/                 # (optional) Zertifikate, wenn lokal abgelegt
```

---

## Konfiguration
### 1) `settings.json`
Minimalbeispiel:
```json
{
  "host": "127.0.0.1",
  "port": 5001,
  "ollama_url": "http://127.0.0.1:11434",
  "whisper_model_path": "./whisper.cpp/models/ggml-medium.bin",
  "upload_dir": "./uploads",
  "secret_key": "<ersetzen-oder-über-env>"
}
```
> **Hinweis:** Vermeide absolute macOS‑Pfade wie `/Users/<name>/...` – nutze relative Pfade oder ENV‑Variablen.

### 2) Umgebungsvariablen (optional)
Lege eine `.env` an (wenn du mit `python-dotenv` arbeitest) oder setze ENV im Startskript:
```
FLASK_ENV=production
FLASK_SECRET_KEY=<zufällig>
OLLAMA_URL=http://127.0.0.1:11434
```

### 3) ProxyFix aktivieren
In `app.py` **nach** `app = Flask(__name__)`:
```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
```
Dadurch generiert Flask korrekte HTTPS‑URLs hinter dem Reverse‑Proxy.

---

## Schnellstart (nur HTTP, Test)
```bash
# 1) Repository klonen
git clone <REPO_URL>
cd web_app

# 2) Python‑Umgebung
python3 -m venv .venv
source ./.venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3) Start im Entwicklungsmodus (ohne TLS)
python app.py
# → http://127.0.0.1:5001
```
> Für den LAN‑Zugriff **ohne** HTTPS würdest du `host='0.0.0.0'` setzen und Port (z. B. 5001) im Router/Firewall nur im LAN öffnen. Für echte Nutzung wird **HTTPS** empfohlen.

---

## Produktionsbetrieb mit HTTPS
### macOS – Variante A: Reverse‑Proxy auf 443 (Root) **einfach**
> Einfacher, aber der Proxy bindet auf Port 443 → benötigt Admin‑Rechte.

1. **Homebrew & Nginx** (nur falls nicht vorhanden)
   ```bash
   brew install nginx
   ```
2. **Zertifikate**: siehe Abschnitt [Zertifikate](#zertifikate-lokal) (oder vorhandene nutzen).
3. **Minimal‑Konfig** (nur deine Site laden): `$(brew --prefix)/etc/nginx/nginx.conf`
   ```nginx
   worker_processes  1;
   events { worker_connections 1024; }
   http {
     include mime.types; default_type application/octet-stream;
     sendfile on; keepalive_timeout 65;
     include servers/*.conf;
     error_log  /Users/<USER>/Library/Logs/nginx/error.log;
     access_log /Users/<USER>/Library/Logs/nginx/access.log;
   }
   ```
4. **Site‑Datei** `servers/arztapp.conf`
   ```nginx
   server {
     listen 192.168.105.136:443 ssl;  # oder 0.0.0.0:443 fürs gesamte LAN
     http2 on;
     server_name 192.168.105.136;

     ssl_certificate     /Pfad/zum/cert.pem;
     ssl_certificate_key /Pfad/zum/key.pem;

     client_max_body_size 200M;

     location / {
       proxy_pass         http://127.0.0.1:5001;
       proxy_http_version 1.1;
       proxy_set_header   Host $host;
       proxy_set_header   X-Forwarded-Proto https;
       proxy_set_header   X-Forwarded-Port 443;
       proxy_set_header   Upgrade $http_upgrade;
       proxy_set_header   Connection "upgrade";
     }
   }
   ```
5. **Starten & Autostart**
   ```bash
   mkdir -p ~/Library/Logs/nginx && : > ~/Library/Logs/nginx/{access,error}.log
   "$(brew --prefix)"/bin/nginx -t && sudo "$(brew --prefix)"/bin/nginx
   # Autostart (Root) optional via LaunchDaemon oder: brew services run nginx (bindet aber i. d. R. nicht 443)
   ```

### macOS – Variante B: Reverse‑Proxy auf 8443 + Portumleitung 443→8443 (ohne Root)
> Empfohlen, wenn kein Root‑Dienst laufen soll.

1. **Nginx auf 8443 (User‑Dienst)**
   ```nginx
   # servers/arztapp.conf
   server {
     listen 127.0.0.1:8443 ssl; http2 on; server_name 192.168.105.136;
     ssl_certificate /Pfad/zum/cert.pem;
     ssl_certificate_key /Pfad/zum/key.pem;
     client_max_body_size 200M;
     location / {
       proxy_pass http://127.0.0.1:5001; proxy_http_version 1.1;
       proxy_set_header X-Forwarded-Proto https; proxy_set_header X-Forwarded-Port 443;
       proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";
     }
   }
   ```
   - Logs & Temp‑Dirs in den Benutzerordner legen:
     ```nginx
     # in nginx.conf (http{})
     error_log  /Users/<USER>/Library/Logs/nginx/error.log;
     access_log /Users/<USER>/Library/Logs/nginx/access.log;
     client_body_temp_path /Users/<USER>/Library/Caches/nginx/client_temp;
     proxy_temp_path       /Users/<USER>/Library/Caches/nginx/proxy_temp;
     fastcgi_temp_path     /Users/<USER>/Library/Caches/nginx/fastcgi_temp;
     uwsgi_temp_path       /Users/<USER>/Library/Caches/nginx/uwsgi_temp;
     scgi_temp_path        /Users/<USER>/Library/Caches/nginx/scgi_temp;
     proxy_request_buffering off; client_max_body_size 200M;
     ```
   - Start/Autostart:
     ```bash
     brew services start nginx    # startet beim User‑Login automatisch
     ```

2. **Portumleitung 443→8443 mit `pf`**
   - Anchor: `/etc/pf.anchors/arztapp`
     ```
     rdr pass on lo0 inet proto tcp from any to 192.168.105.136 port 443 -> 127.0.0.1 port 8443
     rdr pass on en0 inet proto tcp from any to 192.168.105.136 port 443 -> 127.0.0.1 port 8443
     ```
     > `en0` ggf. durch dein physisches Interface ersetzen.
   - In `/etc/pf.conf` im **translation**‑Block einhängen:
     ```
     rdr-anchor "arztapp"
     load anchor "arztapp" from "/etc/pf.anchors/arztapp"
     ```
   - Laden & prüfen:
     ```bash
     sudo pfctl -nf /etc/pf.conf && sudo pfctl -f /etc/pf.conf && sudo pfctl -e
     sudo pfctl -a arztapp -sn
     ```

3. **Test**
   ```bash
   curl -vk https://192.168.105.136/
   ```

### Windows – Reverse‑Proxy auf 443
> **Caddy** ist hier am einfachsten (ein Binary, moderne Defaults). Alternativ: Nginx für Windows.

**Variante Caddy**
1. Caddy herunterladen & ins Projekt (oder nach `C:\caddy\`), dann `Caddyfile` anlegen:
   ```
   https://192.168.105.136 {
     tls {
       # Selbstsigniertes internes Zertifikat – für LAN ausreichend
       internal
     }
     encode zstd gzip
     header Strict-Transport-Security "max-age=31536000"
     reverse_proxy 127.0.0.1:5001
   }
   ```
   > Alternativ kannst du eigene Zertifikate verwenden:
   > ```
   > tls C:\pfad\zu\cert.pem C:\pfad\zu\key.pem
   > ```
2. Starten:
   ```powershell
   caddy run --config Caddyfile --adapter caddyfile
   ```
3. Autostart als Windows‑Dienst: `caddy.exe` bietet `install`/`start` (siehe Caddy‑Doku) **oder** den Aufgabenplaner verwenden.

**Variante Nginx (Windows)**
- `nginx.conf` analog zur macOS‑Variante A: `listen 0.0.0.0:443 ssl;`, Zertifikate referenzieren, `proxy_pass http://127.0.0.1:5001;`
- Start als Dienst z. B. via **NSSM**.

---

## App als Dienst starten
### macOS: LaunchAgent (User‑Kontext)
`~/Library/LaunchAgents/com.app.local.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.app.local</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/Users/<USER>/web_app/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/<USER>/web_app</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key><dict>
    <key>FLASK_ENV</key><string>production</string>
  </dict>
</dict></plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.app.local.plist
```

### Windows: Taskplaner oder NSSM
- **Taskplaner**: Aufgabe „Beim Anmelden“ → `python.exe C:\Pfad\web_app\app.py`
- **NSSM**: `nssm install ArztApp` → Pfad zu `python.exe` und `app.py`, „Automatic (Delayed Start)“.

---

## Zertifikate (lokal)
- **Self‑Signed (OpenSSL)** – IP‑SAN eintragen:
  ```bash
  # macOS Beispiel
  cat > ip.cnf <<'EOF'
  [ req ]
  default_bits = 2048
  prompt = no
  default_md = sha256
  req_extensions = req_ext
  distinguished_name = dn
  [ dn ]
  C=DE
  ST=Local
  L=Local
  O=Local LAN
  CN=192.168.105.136
  [ req_ext ]
  subjectAltName = @alt_names
  [ alt_names ]
  IP.1 = 192.168.105.136
  EOF
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout 192.168.105.136.key -out 192.168.105.136.crt -config ip.cnf
  ```
- **Vertrauen**: Zertifikat im System‑Schlüsselbund (macOS) oder Zertifikatsspeicher (Windows) als „Vertrauenswürdig“ importieren, um Browser‑Warnungen zu vermeiden.

---

## Troubleshooting
- **`https://IP` lädt nicht, aber `http://127.0.0.1:5001` geht**
  - Reverse‑Proxy läuft? `lsof -nP -iTCP:443 -sTCP:LISTEN` (bzw. 8443) und Logs prüfen
  - Zertifikate lesbar? (Key 600, Cert 644)
  - Firewall lässt 443 im LAN zu?
  - macOS Variante B: `pfctl -a arztapp -sn` zeigt beide Regeln (`lo0` + `en0`)?
- **`connect() failed (61: Connection refused) while connecting to upstream`**
  - Flask nicht gestartet oder Port falsch → `curl -v http://127.0.0.1:5001/`
- **`Permission denied` auf `client_body_temp`**
  - Nginx‑Temp‑Pfade in Benutzerverzeichnis legen (siehe macOS Variante B, Schritt 1)
- **Zugriff aus dem LAN klappt, lokal nicht (oder umgekehrt)**
  - Prüfe, ob pf‑Regeln sowohl für `lo0` (lokal) als auch `en0` (LAN) gesetzt sind
- **Ollama/Whisper Fehlermeldungen**
  - Stimmt `ollama_url`? Läuft der Dienst?
  - Existiert `whisper_model_path` tatsächlich? (Dateipfad korrekt, Datei vorhanden)

---

## Sicherheitshinweise
- Standard‑`secret_key` **niemals** im Repo belassen – per ENV setzen.
- Das Setup ist **für LAN** konzipiert. Für Internet‑Expose (Port‑Forwarding) sind zusätzlich Hardening‑Schritte nötig (Rate‑Limit, Auth, CSRF, CSP, Logging, Updates, …).
- Zertifikate regelmäßig erneuern (auch Self‑Signed).

---

**Viel Erfolg!** 


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




