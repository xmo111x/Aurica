# 🪟 Aurica Client – Installations- und Build-Anleitung für Windows

Diese Anleitung beschreibt, wie du den **Aurica Client** unter **Windows 10 / 11** lokal baust und startest.

---

## 📋 Voraussetzungen

1. **Python 3.10 – 3.12**  
   → Empfohlen: **Python 3.11 (64-bit)**  
   👉 [Download von python.org](https://www.python.org/downloads/windows/)

2. **Microsoft Edge WebView2 Runtime**  
   → Wird für das moderne **pywebview-Backend** benötigt.  
   → Ist auf vielen Systemen bereits vorhanden.  
   👉 [WebView2 Runtime herunterladen (Microsoft)](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)

3. **PowerShell 5+** oder **PowerShell Core (7+)**

> 💡 Wenn PowerShell beim Aktivieren des venv-Scripts blockiert, führe einmalig als **Administrator** aus:
> ```powershell
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

---

## 📦 Projekt auspacken & virtuelle Umgebung anlegen

```powershell
# In den Ordner mit Aurica.zip wechseln
cd <DEIN-PFAD>

# Entpacken (falls noch nicht)
Expand-Archive -Path .\Aurica.zip -DestinationPath . -Force

# Ins Projekt wechseln
cd .\Aurica

# Virtuelle Umgebung anlegen
python -m venv .venv

# Aktivieren (PowerShell)
.\.venv\Scripts\Activate.ps1
```

---

## 🧩 Windows-abhängige Pakete installieren

Die mitgelieferte Datei `client_requirements.txt` enthält macOS-Pakete (z. B. `PyObjC`),  
die unter Windows **nicht installierbar** sind.  
Installiere daher nur die relevanten Windows-Pakete:

```powershell
pip install --upgrade pip wheel
pip install pywebview>=4.4 pywin32 pyautogui
```

> ⚠️ Hinweis: Wenn du zusätzliche Pakete nutzt (z. B. für Logging, GUI, API-Zugriffe),  
> installiere diese ebenfalls hier, bevor du den Build startest.

---

## ⚙️ PyInstaller installieren

```powershell
pip install pyinstaller
```

---

## 🏗️ Windows-Build mit PyInstaller erzeugen

Baue das Projekt mithilfe deiner vorhandenen **client.spec**:

```powershell
pyinstaller .\client.spec
```

PyInstaller erstellt anschließend:

- Temporäre Dateien unter  
  ```
  .\build\
  ```
- Die fertige Anwendung unter  
  ```
  .\dist\
  ```

Wenn in deiner `client.spec` beispielsweise steht:

```python
exe = EXE(
    ...
    name='AuricaClient',
    ...
)
```

findest du nach dem Build dein Programm hier:

- **Bei Onedir-Builds:**  
  ```
  .\dist\AuricaClient\AuricaClient.exe
  ```
- **Bei Onefile-Builds:**  
  ```
  .\dist\AuricaClient.exe
  ```

---

## ▶️ Anwendung starten

```powershell
.\dist\AuricaClient\AuricaClient.exe
```

Falls beim Start ein weißes Fenster erscheint oder ein Fehler mit  
`No module named 'Cocoa'`, setze das WebView-Backend manuell:

```powershell
$env:WEBVIEW_GUI = 'edgechromium'
.\dist\AuricaClient\AuricaClient.exe
```

---

## 🧰 Tipps zur Fehlersuche

- **Debug-Konsole aktivieren:**  
  In `client.spec` `console=True` setzen und neu bauen.
- **Logging aktivieren:**  
  ```powershell
  $env:WEBVIEW_LOG = '1'
  ```
- **Fehlendes WebView2:**  
  Installiere die Runtime über den Link oben.
- **SmartScreen-Warnung:**  
  Klicke auf **„Mehr Informationen → Trotzdem ausführen“**, um die App zu starten.

---

## ✅ Nach erfolgreichem Build

- Die Anwendung kann direkt aus dem `dist`-Ordner gestartet werden.  
- Für eine Weitergabe oder Installation kannst du optional einen Windows-Installer  
  (z. B. **Inno Setup**, **NSIS** oder **WiX**) erstellen.

---

© Aurica Client – Windows Build Guide
