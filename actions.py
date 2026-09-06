import os
import subprocess
import webbrowser
import time
import json
import shutil
import socket
import re
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from yt_dlp import YoutubeDL

import psutil
import pyautogui
import pyperclip

from config import APP_COMMANDS, PROCESS_NAMES, SCREENSHOT_DIR, WEBSITES, HOME


_APP_INDEX_CACHE = None
_APP_INDEX_BUILT_AT = 0.0


WINDOWS_SETTINGS = {
    "bluetooth": "ms-settings:bluetooth",
    "bluetooth settings": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "wi fi": "ms-settings:network-wifi",
    "network": "ms-settings:network-status",
    "internet": "ms-settings:network-status",
    "display": "ms-settings:display",
    "sound": "ms-settings:sound",
    "audio": "ms-settings:sound",
    "microphone": "ms-settings:privacy-microphone",
    "camera": "ms-settings:privacy-webcam",
    "notifications": "ms-settings:notifications",
    "printers": "ms-settings:printers",
    "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:devices-touchpad",
    "keyboard": "ms-settings:typing",
    "default apps": "ms-settings:defaultapps",
    "apps": "ms-settings:appsfeatures",
    "storage": "ms-settings:storagesense",
    "battery settings": "ms-settings:batterysaver",
    "power": "ms-settings:powersleep",
    "privacy": "ms-settings:privacy",
    "windows update": "ms-settings:windowsupdate",
    "update": "ms-settings:windowsupdate",
    "date and time": "ms-settings:dateandtime",
    "time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage",
    "accounts": "ms-settings:yourinfo",
}

def _normalize_setting_name(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

def resolve_setting(name):
    q = _normalize_setting_name(name)
    if not q:
        return None, None
    if q in WINDOWS_SETTINGS:
        return WINDOWS_SETTINGS[q], q
    # fuzzy-match the finite Windows Settings catalog.
    best_key = None
    best_score = 0.0
    for key in WINDOWS_SETTINGS:
        score = SequenceMatcher(None, q, key).ratio()
        if q in key or key in q:
            score = max(score, 0.9)
        if score > best_score:
            best_key, best_score = key, score
    if best_key and best_score >= 0.72:
        return WINDOWS_SETTINGS[best_key], best_key
    return None, None

def open_setting(name):
    uri, label = resolve_setting(name)
    if not uri:
        return False, f"I couldn't map {name} to a Windows settings page."
    try:
        if os.name == "nt":
            os.startfile(uri)
        else:
            subprocess.Popen([uri])
        print(f"SETTINGS> {name!r} -> {uri}")
        return True, f"Opening {label} settings."
    except Exception as e:
        return False, f"I found the {label} settings page, but couldn't open it: {e}"


def _normalize_app_name(text):
    text = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    aliases = {
        "visual studio code": "vs code",
        "microsoft edge": "edge",
        "google chrome": "chrome",
        "windows terminal": "terminal",
    }
    return aliases.get(text, text)


def _score_name(query, candidate):
    q = _normalize_app_name(query)
    c = _normalize_app_name(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        # Strong preference for containment, but still prefer closer lengths.
        return 0.88 + 0.1 * (min(len(q), len(c)) / max(len(q), len(c)))
    q_tokens, c_tokens = set(q.split()), set(c.split())
    token_score = len(q_tokens & c_tokens) / max(1, len(q_tokens | c_tokens))
    seq_score = SequenceMatcher(None, q, c).ratio()
    return max(seq_score, 0.72 * seq_score + 0.28 * token_score)


def _build_app_index(force=False):
    """Discover launchable Windows apps without maintaining a hardcoded map."""
    global _APP_INDEX_CACHE, _APP_INDEX_BUILT_AT
    now = time.time()
    if _APP_INDEX_CACHE is not None and not force and now - _APP_INDEX_BUILT_AT < 300:
        return _APP_INDEX_CACHE

    apps = []

    # 1) Start-menu apps, including UWP/Microsoft Store and many Win32 apps.
    if os.name == "nt":
        try:
            ps = (
                "Get-StartApps | Select-Object Name,AppID | "
                "ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps],
                text=True, encoding="utf-8", errors="ignore", timeout=12
            ).strip()
            if out:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for item in data or []:
                    name = str(item.get("Name", "")).strip()
                    appid = str(item.get("AppID", "")).strip()
                    if name and appid:
                        apps.append({"name": name, "kind": "appid", "value": appid})
        except Exception as e:
            print(f"APP INDEX> Get-StartApps unavailable: {e}")

        # 2) .lnk shortcuts from both Start Menu locations.
        start_roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in start_roots:
            if not root.exists():
                continue
            try:
                for link in root.rglob("*.lnk"):
                    apps.append({"name": link.stem, "kind": "path", "value": str(link)})
            except Exception:
                pass

    # 3) Keep tiny legacy commands only as a last-resort compatibility layer.
    for name, command in APP_COMMANDS.items():
        apps.append({"name": name, "kind": "command", "value": command})

    # De-duplicate while preserving useful alternate display names.
    seen = set()
    deduped = []
    for app in apps:
        k = (_normalize_app_name(app["name"]), app["kind"], app["value"])
        if k not in seen:
            seen.add(k)
            deduped.append(app)

    _APP_INDEX_CACHE = deduped
    _APP_INDEX_BUILT_AT = now
    print(f"APP INDEX> discovered {len(deduped)} launchable entries")
    return deduped


def find_app(name):
    query = _normalize_app_name(name)
    if not query:
        return None, 0.0

    # PATH commands are useful for developer tools (code, git-bash, etc.).
    direct = shutil.which(query) or shutil.which(query.replace(" ", ""))
    if direct:
        return {"name": name, "kind": "path", "value": direct}, 1.0

    best = None
    best_score = 0.0
    for app in _build_app_index():
        score = _score_name(query, app["name"])
        if score > best_score:
            best, best_score = app, score
    return best, best_score


def open_app(name):
    app, score = find_app(name)
    if not app or score < 0.58:
        return False, f"I couldn't find an installed app matching {name}."
    try:
        print(f"APP MATCH> {name!r} -> {app['name']!r} score={score:.2f} kind={app['kind']}")
        if app["kind"] == "appid":
            # shell:AppsFolder works for Store apps and many registered Win32 apps.
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['value']}"])
        elif app["kind"] == "path":
            os.startfile(app["value"]) if os.name == "nt" else subprocess.Popen([app["value"]])
        else:
            subprocess.Popen(app["value"], shell=True)
        return True, f"Opening {app['name']}."
    except Exception as e:
        # If a cached result went stale, rebuild once and retry a fresh match.
        if _APP_INDEX_CACHE is not None:
            _build_app_index(force=True)
        return False, f"I found {app['name']}, but couldn't launch it: {e}"


def close_app(name):
    process = PROCESS_NAMES.get(name.lower().strip())
    if not process:
        return False, f"I don't know the process name for {name}."
    closed = False
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == process.lower():
                proc.kill()
                closed = True
        except Exception:
            pass
    return (True, f"Closed {name}.") if closed else (True, f"{name} is not running.")


def _looks_like_url(text):
    t = (text or "").strip()
    return bool(re.match(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/:?#].*)?$", t, re.I))


def _domain_resolves(domain):
    try:
        socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
        return True
    except Exception:
        return False


def resolve_website(name):
    """Resolve a spoken website name without requiring a fixed website dictionary."""
    raw = (name or "").strip()
    if not raw:
        return None, None

    # Exact URLs/domains should be respected.
    if _looks_like_url(raw):
        url = raw if re.match(r"^https?://", raw, re.I) else "https://" + raw
        host = urlparse(url).netloc or raw
        return url, host

    # Existing aliases remain only as fast paths, not as a requirement.
    key = raw.lower().strip()
    if key in WEBSITES:
        return WEBSITES[key], key

    slug_compact = re.sub(r"[^a-z0-9]", "", key)
    slug_hyphen = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    candidates = []
    for slug in (slug_compact, slug_hyphen):
        if not slug:
            continue
        for suffix in (".com", ".in", ".org", ".ai", ".io", ".co"):
            candidates.extend([slug + suffix, "www." + slug + suffix])

    seen = set()
    for domain in candidates:
        if domain in seen:
            continue
        seen.add(domain)
        if _domain_resolves(domain):
            return "https://" + domain, domain

    return None, None


def open_website(name):
    url, label = resolve_website(name)
    if url:
        webbrowser.open(url)
        print(f"WEB RESOLVE> {name!r} -> {url}")
        return True, f"Opening {name}."

    # Last resort: resolve through search rather than refusing because it was not hardcoded.
    query = f"{name} official website"
    webbrowser.open("https://www.google.com/search?btnI=1&q=" + quote(query))
    print(f"WEB RESOLVE> direct domain not found; lucky-searching {query!r}")
    return True, f"I couldn't resolve the domain directly, so I'm opening the most likely website for {name}."



SITE_SEARCH_PROFILES = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "github": "https://github.com/search?q={q}&type=repositories",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "stack overflow": "https://stackoverflow.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={q}",
    "pinterest": "https://www.pinterest.com/search/pins/?q={q}",
    "quora": "https://www.quora.com/search?q={q}",
    "imdb": "https://www.imdb.com/find/?q={q}",
    "netflix": "https://www.netflix.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}

SITE_ALIASES = {
    "stack overflow": "stackoverflow",
    "stack-overflow": "stackoverflow",
    "wiki": "wikipedia",
    "amazon india": "amazon",
    "google search": "google",
}

def normalize_site_name(name):
    key = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    return SITE_ALIASES.get(key, key)

def supports_direct_site_search(name):
    return normalize_site_name(name) in SITE_SEARCH_PROFILES

def search_site(site, query):
    site_key = normalize_site_name(site)
    template = SITE_SEARCH_PROFILES.get(site_key)
    if not template:
        return False, f"I don't have a direct search route for {site}."
    url = template.format(q=quote((query or '').strip()))
    webbrowser.open(url)
    print(f"SITE SEARCH> {site_key!r} query={query!r} -> {url}")
    label = site_key.title() if site_key != "stackoverflow" else "Stack Overflow"
    return True, f"Searching {label} for {query}."

def open_first_search_result(site, query):
    """Open a first result deterministically where a stable route exists.

    Other sites should use visual result selection after direct search.
    """
    site_key = normalize_site_name(site)
    q = quote((query or '').strip())
    if site_key == "google":
        webbrowser.open(f"https://www.google.com/search?btnI=1&q={q}")
        print(f"SITE FIRST RESULT> google query={query!r}")
        return True, f"Opening the first Google result for {query}."
    if site_key == "youtube":
        return play_youtube(query)
    return False, ""

def search_google(query):
    webbrowser.open("https://www.google.com/search?q=" + quote(query))
    return True, f"Searching Google for {query}."


def search_youtube(query):
    webbrowser.open("https://www.youtube.com/results?search_query=" + quote(query))
    return True, f"Searching YouTube for {query}."


def spotify_search(query):
    webbrowser.open("https://open.spotify.com/search/" + quote(query))
    return True, f"Searching Spotify for {query}."



def play_youtube(query):
    """Open the first YouTube search result directly.

    Uses yt-dlp only to resolve the first result URL; nothing is downloaded.
    """
    query = query.strip()
    if not query:
        return False, "Tell me what you want me to play on YouTube."
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = (info or {}).get("entries") or []
        if not entries:
            return False, f"I couldn't find a YouTube video for {query}."
        first = entries[0]
        video_id = first.get("id")
        url = first.get("url") or first.get("webpage_url")
        if video_id and (not url or not str(url).startswith("http")):
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url:
            return False, f"I couldn't resolve a playable YouTube result for {query}."
        webbrowser.open(str(url))
        return True, f"Playing {query} on YouTube."
    except Exception as e:
        return False, f"I couldn't start YouTube playback: {e}"


def play_spotify(query):
    """Best-effort Spotify playback without requiring OAuth.

    Opens the Spotify search directly. If the desktop app handles the spotify:
    URI it will be preferred; otherwise the web player opens. We then send a
    play/pause media key after a short delay. Exact track selection is limited
    by Spotify unless OAuth/API playback is configured.
    """
    query = query.strip()
    if not query:
        return False, "Tell me what you want me to play on Spotify."
    try:
        opened = False
        if os.name == "nt":
            try:
                os.startfile("spotify:search:" + quote(query))
                opened = True
            except Exception:
                pass
        if not opened:
            webbrowser.open("https://open.spotify.com/search/" + quote(query))
        time.sleep(3.0)
        pyautogui.press("playpause")
        return True, f"Opened {query} on Spotify and sent the play command."
    except Exception as e:
        return False, f"I couldn't start Spotify playback: {e}"

def open_folder(name):
    folders = {
        "downloads": HOME / "Downloads",
        "documents": HOME / "Documents",
        "desktop": HOME / "Desktop",
        "pictures": HOME / "Pictures",
        "music": HOME / "Music",
        "videos": HOME / "Videos",
    }
    path = folders.get(name.lower().strip())
    if not path or not path.exists():
        return False, f"I couldn't find your {name} folder."
    os.startfile(path)
    return True, f"Opening {name}."


def screenshot():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / datetime.now().strftime("Screenshot_%Y-%m-%d_%H-%M-%S.png")
    pyautogui.screenshot().save(path)
    return str(path)


def screenshot_and_open():
    """Capture a user-requested screenshot, save it, then open it immediately.
    Internal vision continues using screenshot() so it does not pop open images.
    """
    try:
        path = screenshot()
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen([path])
        print(f"SCREENSHOT OPEN> {path}")
        return True, f"Screenshot captured and opened. Saved to {path}"
    except Exception as e:
        return False, f"I couldn't capture and open the screenshot: {e}"


def type_text(text):
    pyautogui.write(text, interval=0.03)
    return True, "Typing completed."


def keypress(key):
    allowed = {"enter", "esc", "tab", "space", "backspace", "delete", "up", "down", "left", "right"}
    key = key.lower().strip()
    if key not in allowed:
        return False, "That key is not in my approved key list."
    pyautogui.press(key)
    return True, f"Pressed {key}."


def shortcut(combo):
    combo = combo.lower().replace(" ", "")
    allowed = {
        "alt+tab": ("alt", "tab"),
        "ctrl+c": ("ctrl", "c"),
        "ctrl+x": ("ctrl", "x"),
        "ctrl+v": ("ctrl", "v"),
        "ctrl+z": ("ctrl", "z"),
        "ctrl+y": ("ctrl", "y"),
        "ctrl+s": ("ctrl", "s"),
        "ctrl+a": ("ctrl", "a"),
        "ctrl+l": ("ctrl", "l"),
        "ctrl+f": ("ctrl", "f"),
        "ctrl+t": ("ctrl", "t"),
        "ctrl+w": ("ctrl", "w"),
        "ctrl+tab": ("ctrl", "tab"),
        "win+d": ("win", "d"),
    }
    keys = allowed.get(combo)
    if not keys:
        return False, "That shortcut is not approved."
    pyautogui.hotkey(*keys)
    return True, f"Performed {combo}."


def system_control(action):
    action = action.lower().strip()
    if action == "volume_up":
        pyautogui.press("volumeup", presses=4)
        return True, "Volume increased."
    if action == "volume_down":
        pyautogui.press("volumedown", presses=4)
        return True, "Volume lowered."
    if action == "mute":
        pyautogui.press("volumemute")
        return True, "Audio muted."
    if action == "play_pause":
        pyautogui.press("playpause")
        return True, "Toggled playback."
    if action == "next_track":
        pyautogui.press("nexttrack")
        return True, "Skipped to the next track."
    if action == "previous_track":
        pyautogui.press("prevtrack")
        return True, "Went to the previous track."
    if action.startswith("volume_set:"):
        try:
            target=max(0,min(100,int(action.split(":",1)[1])))
            # Windows media keys don't expose an absolute volume API reliably without extra deps.
            # Reset low then step upward in ~2% increments.
            pyautogui.press("volumedown", presses=50, interval=0.01)
            pyautogui.press("volumeup", presses=max(0, round(target/2)), interval=0.01)
            return True, f"Set volume to about {target} percent."
        except Exception:
            return False, "I couldn't set that volume level."
    if action == "minimize":
        pyautogui.hotkey("win", "down")
        return True, "Minimized the current window."
    if action == "maximize":
        pyautogui.hotkey("win", "up")
        return True, "Maximized the current window."
    if action == "switch_window":
        pyautogui.hotkey("alt", "tab")
        return True, "Switched windows."
    if action == "close_window":
        pyautogui.hotkey("alt", "f4")
        return True, "Closed the current window."
    if action == "show_desktop":
        pyautogui.hotkey("win", "d")
        return True, "Showing the desktop."
    if action == "task_manager":
        pyautogui.hotkey("ctrl", "shift", "esc")
        return True, "Opening Task Manager."
    if action == "refresh":
        pyautogui.press("f5")
        return True, "Refreshed the current window."
    if action in {"brightness_up", "brightness_down"}:
        if os.name != "nt":
            return False, "Brightness control is only implemented on Windows."
        try:
            delta = 10 if action == "brightness_up" else -10
            ps = (
                "$b=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1).CurrentBrightness;"
                f"$n=[Math]::Max(0,[Math]::Min(100,$b+({delta})));"
                "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
                "Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{Timeout=1;Brightness=[byte]$n} | Out-Null;"
                "Write-Output $n"
            )
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True, stderr=subprocess.STDOUT, timeout=8).strip()
            return True, f"Brightness set to about {out.splitlines()[-1]} percent."
        except Exception as e:
            return False, f"I couldn't change brightness on this display: {e}"
    if action == "lock":
        os.system("rundll32.exe user32.dll,LockWorkStation")
        return True, "Locking the computer."
    if action == "battery":
        battery = psutil.sensors_battery()
        if not battery:
            return False, "Battery information is unavailable."
        state = "charging" if battery.power_plugged else "on battery"
        return True, f"Battery is at {battery.percent:.0f} percent and {state}."
    if action == "system_status":
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory().percent
        return True, f"CPU usage is {cpu:.0f} percent and memory usage is {ram:.0f} percent."
    return False, "I don't recognize that system control."


def file_search(query, max_results=8):
    query = query.lower().strip()
    if not query:
        return []
    tokens = [t for t in query.replace(".", " ").split() if t]
    roots = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads"]
    matches = []
    for root in roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")][:30]
            for filename in files:
                low = filename.lower()
                if all(token in low for token in tokens):
                    matches.append(str(Path(current) / filename))
                    if len(matches) >= max_results:
                        return matches
    return matches


def copy_text(text):
    pyperclip.copy(text)
    return True, "Copied to clipboard."

# ==================== V10: FILESYSTEM / CLIPBOARD / DESKTOP TOOLS ====================

def _windows_known_folder(name):
    """Resolve Windows user folders, including OneDrive/redirection."""
    key = (name or "").lower().strip()
    if os.name != "nt":
        return None
    try:
        import winreg
        reg_names = {
            "desktop": "Desktop",
            "documents": "Personal",
            "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
            "pictures": "My Pictures",
            "music": "My Music",
            "videos": "My Video",
        }
        value_name = reg_names.get(key)
        if value_name:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                value, _ = winreg.QueryValueEx(k, value_name)
                value = os.path.expandvars(str(value))
                if value:
                    return Path(value)
    except Exception as e:
        print(f"KNOWN FOLDER WARN> {key}: {e}")

    # Common fallback for PCs whose Desktop/Documents are redirected to OneDrive.
    one = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if one and key in {"desktop", "documents", "pictures"}:
        candidate = Path(one) / key.capitalize()
        if candidate.exists():
            return candidate
    return None


def _build_safe_roots():
    roots = {}
    for key in ("desktop", "documents", "downloads", "pictures", "music", "videos"):
        resolved = _windows_known_folder(key)
        roots[key] = resolved if resolved else (HOME / key.capitalize())
    return roots


SAFE_ROOTS = _build_safe_roots()


def _safe_root(name="desktop"):
    key = (name or "desktop").lower().strip()
    root = SAFE_ROOTS.get(key) or SAFE_ROOTS["desktop"]
    # Creation destinations may not exist yet; create the known user folder if safe.
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    print(f"FS ROOT> {key} -> {root}")
    return root


def find_files(query, max_results=10):
    """Return matching files/folders from common user locations."""
    q = (query or "").lower().strip()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if t]
    hits = []
    for root in (HOME / "Desktop", HOME / "Documents", HOME / "Downloads"):
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")][:40]
            for name in list(dirs) + list(files):
                low = name.lower()
                if all(t in low for t in tokens):
                    p = str(Path(current) / name)
                    hits.append(p)
                    if len(hits) >= max_results:
                        return hits
    return hits


def open_file(query):
    matches = find_files(query, max_results=5)
    if not matches:
        return False, f"I couldn't find a file matching {query}."
    path = matches[0]
    try:
        os.startfile(path) if os.name == "nt" else subprocess.Popen([path])
        return True, f"Opening {Path(path).name}."
    except Exception as e:
        return False, f"I found {Path(path).name}, but couldn't open it: {e}"


def create_folder(spec):
    """spec: location|||folder name, location defaults to desktop."""
    try:
        if "|||" in (spec or ""):
            location, name = spec.split("|||", 1)
        else:
            location, name = "desktop", spec
        name = re.sub(r'[<>:"/\\|?*]+', "_", (name or "New Folder")).strip().strip(".")
        if not name:
            return False, "The folder name was empty."
        path = _safe_root(location) / name
        path.mkdir(parents=True, exist_ok=True)
        return True, f"Created folder {name} in {location or 'desktop'}."
    except Exception as e:
        return False, f"I couldn't create that folder: {e}"


def _safe_path_segment(name):
    """Sanitize one Windows path segment without flattening the whole path."""
    return re.sub(r'[<>:"/\\|?*]+', "_", (name or "").strip()).strip().strip(".")


def _find_named_folder(folder_name, preferred_root=None):
    """Find an existing folder under the safe user roots. Returns Path or None."""
    wanted = (folder_name or "").strip().lower()
    if not wanted:
        return None
    roots = []
    if preferred_root:
        roots.append(_safe_root(preferred_root))
    roots.extend(r for k, r in SAFE_ROOTS.items() if r not in roots)
    # First prefer an exact direct child, then a shallow recursive exact match.
    for root in roots:
        direct = root / folder_name
        if direct.exists() and direct.is_dir():
            return direct
    for root in roots:
        if not root.exists():
            continue
        try:
            for current, dirs, _ in os.walk(root):
                rel_depth = len(Path(current).relative_to(root).parts)
                if rel_depth > 3:
                    dirs[:] = []
                    continue
                for d in dirs:
                    if d.lower() == wanted:
                        return Path(current) / d
        except Exception:
            continue
    return None


def create_text_file(spec):
    """Create TXT/MD in a safe root or nested folder.

    Accepted specs:
      location|||filename|||content
      location|||subfolder|||filename|||content
      folder:Folder Name|||filename|||content   (finds an existing folder)
    """
    try:
        raw = spec or ""
        parts = raw.split("|||")
        location = "desktop"
        subfolder = ""

        if len(parts) >= 4:
            location, subfolder, filename = parts[0], parts[1], parts[2]
            content = "|||".join(parts[3:])
        elif len(parts) >= 3:
            location, filename = parts[0], parts[1]
            content = "|||".join(parts[2:])
        elif len(parts) == 2:
            filename, content = parts
        else:
            return False, "I need a filename and content."

        filename = _safe_path_segment(filename)
        if not filename:
            return False, "The filename was empty."
        if "." not in filename:
            filename += ".txt"
        if Path(filename).suffix.lower() not in {".txt", ".md"}:
            return False, "For safety, v10 creates only TXT or Markdown files."

        # Explicit named-folder lookup, useful for natural commands like
        # 'create test.txt inside Ultron Demo'.
        if str(location).lower().startswith("folder:"):
            requested = str(location).split(":", 1)[1].strip()
            parent = _find_named_folder(requested)
            if not parent:
                return False, f"I couldn't find the folder {requested}."
        else:
            parent = _safe_root(location)
            if subfolder:
                segments = [_safe_path_segment(x) for x in re.split(r"[\\/]+", subfolder) if x.strip()]
                segments = [x for x in segments if x]
                for seg in segments:
                    parent = parent / seg
                parent.mkdir(parents=True, exist_ok=True)

        path = parent / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"FS FILE> {path}")
        return True, f"Created {filename} in {parent}."
    except Exception as e:
        return False, f"I couldn't create that file: {e}"


def rename_file(spec):
    """spec: search query|||new filename. No deletion."""
    try:
        query, new_name = spec.split("|||", 1)
        matches = find_files(query, max_results=2)
        if not matches:
            return False, f"I couldn't find {query}."
        src = Path(matches[0])
        new_name = re.sub(r'[<>:"/\\|?*]+', "_", new_name.strip())
        if not new_name:
            return False, "The new name was empty."
        if src.is_file() and "." not in new_name and src.suffix:
            new_name += src.suffix
        dst = src.with_name(new_name)
        src.rename(dst)
        return True, f"Renamed {src.name} to {dst.name}."
    except Exception as e:
        return False, f"I couldn't rename that item: {e}"


def move_file(spec):
    """spec: search query|||destination root name."""
    try:
        query, destination = spec.split("|||", 1)
        matches = find_files(query, max_results=2)
        if not matches:
            return False, f"I couldn't find {query}."
        src = Path(matches[0])
        root = _safe_root(destination)
        dst = root / src.name
        shutil.move(str(src), str(dst))
        return True, f"Moved {src.name} to {destination}."
    except Exception as e:
        return False, f"I couldn't move that item: {e}"


def clipboard_read():
    text = pyperclip.paste()
    if not text:
        return True, "Your clipboard is empty."
    return True, str(text)


def clipboard_write(text):
    pyperclip.copy(text or "")
    return True, "Clipboard updated."


def scroll_screen(direction_or_amount):
    raw = (direction_or_amount or "down").lower().strip()
    amount = -6 if "down" in raw else 6
    m = re.search(r"-?\d+", raw)
    if m:
        val = max(1, min(20, abs(int(m.group()))))
        amount = -val if "down" in raw or raw.startswith("-") else val
    pyautogui.scroll(amount)
    return True, f"Scrolled {'down' if amount < 0 else 'up'}."
