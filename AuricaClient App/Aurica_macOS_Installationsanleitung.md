# 🍎 Aurica Client – Installations- und Build-Anleitung für macOS

Diese Anleitung beschreibt, wie du den **Aurica Client** unter **macOS 12 (Monterey) – macOS 15 (Sequoia)** baust und startest.

---

## 📋 Voraussetzungen

1. **Python 3.10 – 3.12**  
   → Empfohlen: **Python 3.11 (arm64 für Apple Silicon)**  
   👉 [Download von python.org](https://www.python.org/downloads/macos/)  
   > Falls du Homebrew nutzt:  
   > ```bash
   > brew install python@3.11
   > ```

2. **Command Line Tools for Xcode**  
   → Wird für das Kompilieren von PyObjC benötigt  
   ```bash
   xcode-select --install
   ```

3. **Homebrew** (optional, aber empfohlen)  
   👉 [https://brew.sh](https://brew.sh)

---

## 📦 Projekt auspacken & virtuelle Umgebung anlegen

```bash
# In den Ordner mit Aurica.zip wechseln
cd <DEIN-PFAD>

# Entpacken (falls noch nicht)
unzip -o Aurica.zip

# Ins Projektverzeichnis wechseln
cd Aurica

# Virtuelle Umgebung anlegen
python3 -m venv .venv

# Aktivieren
source .venv/bin/activate
```

---

## 🧩 macOS-spezifische Pakete installieren

Verwende die mitgelieferte **client_requirements.txt**, da sie PyObjC-Pakete enthält, die für macOS notwendig sind.

```bash
pip install --upgrade pip wheel
pip install -r client_requirements.txt
```

Falls du ohne die Datei installieren möchtest (typische Kernpakete):

```bash
pip install pywebview>=4.4 pyobjc pyautogui
```

> 💡 Wenn der Build für Apple Silicon-Macs fehlschlägt, stelle sicher, dass du Python arm64 verwendest:  
> ```bash
> python3 -c "import platform; print(platform.machine())"
> ```
> → Sollte `arm64` ausgeben.

---

## ⚙️ PyInstaller installieren

```bash
pip install pyinstaller
```

---

## 🏗️ macOS-Build mit PyInstaller erzeugen

Der Build erfolgt über die vorhandene **client.spec**:

```bash
pyinstaller ./client.spec
```

PyInstaller erstellt:

- Temporäre Dateien unter  
  ```
  ./build/
  ```
- Die fertige Anwendung unter  
  ```
  ./dist/AuricaClient.app
  ```

> 🔍 Wenn du eine **.app-Bundle-Version** möchtest, überprüfe, ob in deiner `client.spec` ein `BUNDLE(...)`-Eintrag vorhanden ist.  
> Beispiel:
> ```python
> app = BUNDLE(
>     exe,
>     name='AuricaClient.app',
>     icon=None,
>     bundle_identifier='com.aurica.client'
> )
> ```

---

## ▶️ Anwendung starten

```bash
open ./dist/AuricaClient.app
```

Falls macOS die App blockiert (nicht signiert), erlaube sie über:

**Systemeinstellungen → Datenschutz & Sicherheit → Trotzdem öffnen**

Oder per Terminal:

```bash
xattr -dr com.apple.quarantine ./dist/AuricaClient.app
```

---

## 🧰 Tipps zur Fehlersuche

- **Debug-Modus aktivieren:**  
  In `client.spec` `console=True` setzen und neu bauen.  
- **Log aktivieren:**  
  ```bash
  export WEBVIEW_LOG=1
  ```
- **Backend erzwingen (optional):**  
  ```bash
  export WEBVIEW_GUI=cocoa
  ```
- **Build säubern:**  
  ```bash
  rm -rf build dist __pycache__
  ```

---

## ✅ Nach erfolgreichem Build

- Die App liegt als **AuricaClient.app** im `dist`-Ordner.  
- Du kannst sie per Doppelklick starten oder in `/Applications` kopieren:
  ```bash
  cp -R dist/AuricaClient.app /Applications/
  ```

> Optional: Signieren und Notarisieren für die Weitergabe außerhalb deines Systems.

---

© Aurica Client – macOS Build Guide
