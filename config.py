import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Ultron"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MIC_INDEX = int(os.getenv("MIC_INDEX", "1"))
SAMPLE_RATE = 16000
CHANNELS = 1
PHRASE_TIME_LIMIT = int(os.getenv("PHRASE_TIME_LIMIT", "5"))
HOME = Path.home()
SCREENSHOT_DIR = HOME / "Pictures" / "Ultron Screenshots"
MAX_MEMORY_TURNS = 8

WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "instagram": "https://www.instagram.com",
    "gmail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com",
    "linkedin": "https://www.linkedin.com",
    "spotify": "https://open.spotify.com",
    "reddit": "https://www.reddit.com",
    "amazon": "https://www.amazon.in",
    "claude": "https://claude.ai",
}

APP_COMMANDS = {
    "calculator": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "file explorer": "explorer.exe",
    "vs code": "code",
    "visual studio code": "code",
}

PROCESS_NAMES = {
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
}

# Voice wake word. V10.6 always starts in standby and uses this word to activate.
# REQUIRE_WAKE_WORD is retained for compatibility with older .env files but is no
# longer needed to enable the stateful wake/standby behavior.
REQUIRE_WAKE_WORD = True
WAKE_WORD = os.getenv("WAKE_WORD", "ultron")
