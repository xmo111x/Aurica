# client_app.py – Aurica Client (pywebview, macOS/Windows)

# --- Optionales Log (UTI) -----------------------------------------------------
try:
    import UniformTypeIdentifiers as _UTI
    from UniformTypeIdentifiers import UTType  # noqa: F401
    print('[AuricaClient] UTI geladen:', hasattr(_UTI, 'UTType'))
except Exception as e:
    print('[AuricaClient] UTI NICHT geladen:', e)

# --- Standardlibs --------------------------------------------------------------
import os
import sys
import time
import platform
import subprocess
import webview

# --- Cocoa / WebKit ------------------------------------------------------------
if platform.system() == 'Darwin':
    from Cocoa import NSObject, NSOpenPanel, NSArray
else:
    NSObject = object
    NSOpenPanel = None
    NSArray = list

try:
    from WebKit import WKWebView  # noqa: F401
except Exception:
    WKWebView = None

# --- optionale Helfer ----------------------------------------------------------
try:
    import pyperclip
except Exception:
    pyperclip = None

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None


# ------------------- Konfiguration / URL --------------------------------------
DEFAULT_URL = "https://192.168.105.136"

def resolve_url() -> str:
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            return arg.split("=", 1)[1].strip()
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1].strip()
    env = os.environ.get("AURICA_SERVER_URL")
    if env:
        return env.strip()
    return DEFAULT_URL


def is_mac() -> bool:
    return platform.system() == 'Darwin'


def is_win() -> bool:
    return platform.system() == 'Windows'


def _osascript_bin() -> str:
    return "/usr/bin/osascript" if is_mac() else "osascript"


def _run_osa_with_args(script: str, *argv: str) -> subprocess.CompletedProcess:
    cmd = [_osascript_bin(), "-e", script]
    cmd.extend(argv)
    return subprocess.run(cmd, capture_output=True, text=True)


# =================== macOS: Quartz (CGEvent) & Pasteboard ======================
if is_mac():
    from AppKit import NSPasteboard
    from Quartz import (
        CGEventCreateKeyboardEvent, CGEventPost,
        kCGHIDEventTap
    )

    # Mac-Keycodes (reicht für unseren Use-Case)
    KEYCODES = {
        'a': 0,
        'b': 11,
        't': 17,
        'v': 9,
        'enter': 36,
        'tab': 48,
        'left': 123,
        'right': 124,
        'down': 125,
        'up': 126,
        'cmd': 55,
        'shift': 56,
    }

    def mac_clipboard_set(text: str):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, "public.utf8-plain-text")

    def _post_key(code: int, is_down: bool):
        ev = CGEventCreateKeyboardEvent(None, code, is_down)
        CGEventPost(kCGHIDEventTap, ev)
        time.sleep(0.02)

    def mac_key_down_up(code: int):
        _post_key(code, True)
        _post_key(code, False)

    def mac_type_char(ch: str):
        """
        Tippt Buchstaben; Großbuchstaben -> mit Shift.
        """
        if len(ch) != 1 or not ch.isalpha():
            return
        base = ch.lower()
        code = KEYCODES.get(base)
        if code is None:
            return
        if ch.isupper():
            _post_key(KEYCODES['shift'], True)
            time.sleep(0.02)
            mac_key_down_up(code)
            time.sleep(0.02)
            _post_key(KEYCODES['shift'], False)
            time.sleep(0.02)
        else:
            mac_key_down_up(code)
    def mac_press_enter():
        """Drückt die Enter-Taste"""
        mac_key_down_up(KEYCODES['enter'])
        
    def mac_press_special(name: str):
        name = name.lower()
        if name in KEYCODES:
            mac_key_down_up(KEYCODES[name])

    def mac_cmd_v():
        """Explizit: CMD down → 'v' → CMD up (robuster bei Java)"""
        _post_key(KEYCODES['cmd'], True)
        time.sleep(0.02)
        _post_key(KEYCODES['v'], True)
        _post_key(KEYCODES['v'], False)
        time.sleep(0.02)
        _post_key(KEYCODES['cmd'], False)
        time.sleep(0.02)

    def mac_send_token(token: str):
        """
        Sendet ein Token aus der Prefix-Sequenz.
        Unterstützt:
          - 'a'..'z' / 'A'..'Z'
          - 'enter', 'tab', 'left', 'right', 'up', 'down'
          - 'shift+<letter>', 'cmd+<letter>' (nur Buchstaben)
        """
        t = token.strip()
        if not t:
            return
        tl = t.lower()

        # Chords: cmd+X / shift+X
        if '+' in tl:
            parts = [p.strip() for p in tl.split('+')]
            if len(parts) == 2 and parts[1] and parts[1].isalpha():
                mod, letter = parts[0], parts[1]
                if mod == 'cmd':
                    _post_key(KEYCODES['cmd'], True)
                    time.sleep(0.02)
                    mac_type_char(letter)  # letter down/up
                    time.sleep(0.02)
                    _post_key(KEYCODES['cmd'], False)
                    time.sleep(0.02)
                elif mod == 'shift':
                    # Uppercase erzwingen
                    mac_type_char(letter.upper())
                return

        # Einzelbuchstabe?
        if len(t) == 1 and t.isalpha():
            mac_type_char(t)
            return

        # Spezielle Tasten
        if tl in ('enter', 'tab', 'left', 'right', 'up', 'down'):
            mac_press_special(tl)
            return

        # unbekannt -> ignorieren

    def mac_activate_by_title(win_title: str):
        osa = r'''
on run argv
  set winTitle to item 1 of argv
  tell application "System Events"
    set allProcs to application processes
    repeat with p in allProcs
      try
        set ws to windows of p
        repeat with w in ws
          set wt to (name of w as text)
          if (wt is winTitle) or (wt contains winTitle) then
            tell p
              set frontmost to true
              try
                tell w to perform action "AXRaise"
              end try
            end tell
            return "OK"
          end if
        end repeat
      end try
    end repeat
  end tell
  return "NO_MATCH"
end run
'''
        try:
            proc = _run_osa_with_args(osa, win_title or "")
            return (proc.stdout or "").strip()
        except Exception as e:
            return f"ERR:{e}"


# ------------------- Crashfester OpenPanel-Handler -----------------------------
def _safe_open_panel(self, webView, parameters, frame, completionHandler):
    try:
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        try:
            panel.setAllowsMultipleSelection_(parameters.allowsMultipleSelection())
        except Exception:
            panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["wav", "mp3", "m4a"])

        def done(result):
            try:
                if result == 1:
                    completionHandler(panel.URLs())
                else:
                    completionHandler(NSArray.array())
            except Exception:
                completionHandler(NSArray.array())

        panel.beginWithCompletionHandler_(done)
    except Exception:
        completionHandler(NSArray.array())
    return None


# ------------------- Bridge (JS API) ------------------------------------------
class Bridge:
    def ping(self):
        print('[Bridge] ping() from JS')
        return {'ok': True}

    def paste_to_t2med(self, text: str, window_title: str | None = None):
        print('[Bridge] paste_to_t2med called, len(text)=', len(text))
        return self.paste_to_t2med_mode(text, mode="anamnese", window_title=window_title)

    def paste_to_t2med_mode(self, text: str, mode: str = "anamnese", window_title: str | None = None):
        txt = (text or "").strip()
        if not txt:
            return {"ok": False, "error": "no_text"}

        # --- Prefix je Modus (konfigurierbar für Anamnese) ---
        prefix_key = None
        if mode == "befund":
            prefix_key = "b"
        elif mode == "therapie":
            prefix_key = "t"
        elif mode == "anamnese":
            # Standard: kein Prefix – aber via Env überschreibbar:
            prefix_key = os.environ.get("AURICA_T2MED_ANAMNESE_PREFIX", "").strip() or None
            # Beispiele:
            # export AURICA_T2MED_ANAMNESE_PREFIX="A"
            # export AURICA_T2MED_ANAMNESE_PREFIX="tab"
            # export AURICA_T2MED_ANAMNESE_PREFIX="tab,tab"
            # export AURICA_T2MED_ANAMNESE_PREFIX="shift+tab"

        paste_retries = 1
        try:
            paste_retries = max(1, int(os.environ.get("AURICA_T2MED_PASTE_RETRIES", "2")))
        except Exception:
            paste_retries = 2

        # ---------- macOS ----------
        if is_mac():
            win_title = os.environ.get("AURICA_T2MED_WINDOW", "").strip() or (window_title or "").strip() or "T2med"

            # 1) Clipboard setzen
            try:
                mac_clipboard_set(txt)
            except Exception as e:
                return {"ok": False, "error": f"clipboard_failed:{e}"}

            # 2) App in den Vordergrund
            act_res = mac_activate_by_title(win_title)

            # Fokus stabilisieren
            time.sleep(0.90)

            # 3) Sequenz senden
            try:
                if mode == "anamnese":
                    # Länger warten, damit T2med den Fokus wirklich übernommen hat
                    time.sleep(0.99)

                    # Versuch: "A" (Shift nötig für Großbuchstaben)
                    mac_type_char('a')
                    time.sleep(0.35)
                    mac_press_enter()
                    time.sleep(0.35)
                    mac_cmd_v()
                    time.sleep(0.35)
                    mac_press_enter()

                elif mode == "befund":
                    time.sleep(0.99)
                    mac_type_char('b')
                    time.sleep(0.35)
                    mac_press_enter()
                    time.sleep(0.35)
                    mac_cmd_v()
                    time.sleep(0.35)
                    mac_press_enter()

                elif mode == "therapie":
                    time.sleep(0.99)
                    mac_type_char('t')
                    time.sleep(0.35)
                    mac_press_enter()
                    time.sleep(0.35)
                    mac_cmd_v()
                    time.sleep(0.35)
                    mac_press_enter()

                return {"ok": True, "activated": act_res, "mode": mode}
            except Exception as e:
                return {"ok": False, "error": f"quartz_failed:{e}", "activated": act_res, "mode": mode}


        # ---------- Windows ----------
        if is_win():
            app_name = (window_title or os.environ.get("AURICA_T2MED_APPNAME") or "T2med").strip()

            if pyperclip:
                try:
                    pyperclip.copy(txt)
                except Exception:
                    pass

            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"$s=New-Object -ComObject WScript.Shell; $s.AppActivate('{app_name}')"],
                    check=False
                )
                time.sleep(0.4)
            except Exception:
                pass

            if not pyautogui:
                return {"ok": False, "error": "pyautogui_missing",
                        "hint": "pip install pyautogui; ggf. Windows fragt nach Zugriffsrechten."}

            # ---------- Windows ----------
            if is_win():
                app_name = (window_title or os.environ.get("AURICA_T2MED_APPNAME") or "T2med").strip()

                if pyperclip:
                    try:
                        pyperclip.copy(txt)
                    except Exception:
                        pass

                try:
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"$s=New-Object -ComObject WScript.Shell; $s.AppActivate('{app_name}')"],
                        check=False
                    )
                    time.sleep(0.4)
                except Exception:
                    pass

                if not pyautogui:
                    return {"ok": False, "error": "pyautogui_missing",
                            "hint": "pip install pyautogui; ggf. Windows fragt nach Zugriffsrechten."}

                # --- Anamnese ---
                if mode == "anamnese":
                    time.sleep(1.50)              # Fokuszeit
                    pyautogui.typewrite('a')
                    time.sleep(0.35)
                    pyautogui.press('enter')
                    time.sleep(0.35)
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.90)
                    pyautogui.press('enter')
                    return {"ok": True, "mode": mode}

                # --- Befund ---
                elif mode == "befund":
                    pyautogui.typewrite('b')
                    time.sleep(0.35)
                    pyautogui.press('enter')
                    time.sleep(0.35)
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.90)
                    pyautogui.press('enter')
                    return {"ok": True, "mode": mode}

                # --- Therapie ---
                elif mode == "therapie":
                    pyautogui.typewrite('t')
                    time.sleep(0.35)
                    pyautogui.press('enter')
                    time.sleep(0.35)
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.90)
                    pyautogui.press('enter')
                    return {"ok": True, "mode": mode}

                return {"ok": True}


        return {"ok": False, "error": "unsupported_os"}

    def pick_file(self):
        paths = webview.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=('Audio files (*.wav;*.mp3;*.m4a)',)
        )
        return paths[0] if paths else None


# ------------------- Start / Patch / Delegate-Setup ----------------------------
_global_win = None

def _patch_pywebview_delegate():
    try:
        from webview.platforms.cocoa import WebKitDelegate
        setattr(
            WebKitDelegate,
            'webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_',
            _safe_open_panel
        )
        print('Pywebview WebKitDelegate::runOpenPanel gepatcht')
    except Exception as e:
        print('Patch des WebKitDelegate fehlgeschlagen:', e)


def after_start():
    global _global_win
    try:
        if hasattr(_global_win, 'gui') and hasattr(_global_win.gui, 'webview'):
            wk = _global_win.gui.webview
            wk.setUIDelegate_(NSObject.alloc().init())
            print('WKWebView (gui.webview) erreichbar')
            return
    except Exception as e:
        print('Alt-Pfad (gui.webview) Fehler:', e)
    try:
        from webview.platforms.cocoa import BrowserView
        instance = BrowserView.instances.get(_global_win.uid)
        if instance and hasattr(instance, 'webview'):
            print('WKWebView (BrowserView) erreichbar')
        else:
            print('Konnte native WKWebView-Instanz nicht finden')
    except Exception as e:
        print('UIDelegate-Installationsfehler:', e)


def main():
    url = resolve_url()
    print(f"[AuricaClient] Lade URL: {url}")
    _patch_pywebview_delegate()

    bridge = Bridge()
    global _global_win
    _global_win = webview.create_window('Aurica Client', url, js_api=bridge, width=1100, height=800)

    webview.start(func=after_start, gui='cocoa', debug=False)


if __name__ == '__main__':
    main()


