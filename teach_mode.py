"""Ultron v11.0 Teach Me Mode.

Records a user's demonstrated mouse/keyboard workflow and replays it later.
Privacy-first: typed character content is NOT persisted. We record mouse
clicks, scrolls, and non-text control keys/hotkeys only.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pyautogui

WORKFLOW_DIR = Path.home() / ".ultron" / "workflows"
WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

SENSITIVE_KEYS = {"password", "otp", "pin", "bank", "upi", "card", "cvv", "payment"}

def _safe_name(name):
    cleaned = re.sub(r"[^a-zA-Z0-9 _-]+", "", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80] or "workflow"

def _workflow_path(name):
    slug = re.sub(r"[^a-z0-9]+", "_", _safe_name(name).lower()).strip("_")
    return WORKFLOW_DIR / f"{slug}.json"

class WorkflowRecorder:
    def __init__(self):
        self.recording = False
        self.started_at = 0.0
        self.events = []
        self._mouse_listener = None
        self._key_listener = None
        self._lock = threading.Lock()
        self._pressed_modifiers = set()

    def start(self):
        if self.recording:
            return False, "I'm already learning a workflow."
        try:
            from pynput import mouse, keyboard
        except Exception as e:
            return False, f"Teach Mode needs pynput. Install requirements again. Details: {e}"

        self.events = []
        self.started_at = time.time()
        self.recording = True

        def stamp():
            return round(time.time() - self.started_at, 3)

        def on_click(x, y, button, pressed):
            if not self.recording or not pressed:
                return
            with self._lock:
                self.events.append({
                    "t": stamp(),
                    "type": "click",
                    "x": int(x),
                    "y": int(y),
                    "button": str(button).split(".")[-1],
                })
            print(f"TEACH EVENT> click {int(x)},{int(y)} {button}")

        def on_scroll(x, y, dx, dy):
            if not self.recording:
                return
            with self._lock:
                self.events.append({
                    "t": stamp(),
                    "type": "scroll",
                    "amount": int(dy),
                })
            print(f"TEACH EVENT> scroll {int(dy)}")

        modifier_names = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r"}

        def key_name(key):
            try:
                from pynput.keyboard import Key
                if hasattr(key, "char") and key.char:
                    return key.char
            except Exception:
                pass
            return str(key).replace("Key.", "")

        def on_press(key):
            if not self.recording:
                return
            name = key_name(key)
            low = str(name).lower()

            if low in modifier_names:
                self._pressed_modifiers.add(low)
                return

            # Privacy guard: never store ordinary typed characters.
            # Only control/navigation keys and modifier shortcuts are kept.
            allowed_controls = {
                "enter","tab","esc","escape","space","backspace","delete",
                "up","down","left","right","home","end","page_up","page_down",
                "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12"
            }
            if self._pressed_modifiers and len(low) == 1:
                mods = sorted(self._pressed_modifiers)
                with self._lock:
                    self.events.append({
                        "t": stamp(),
                        "type": "hotkey",
                        "keys": mods + [low],
                    })
                print(f"TEACH EVENT> hotkey {'+'.join(mods+[low])}")
            elif low in allowed_controls:
                with self._lock:
                    self.events.append({
                        "t": stamp(),
                        "type": "key",
                        "key": "esc" if low == "escape" else low,
                    })
                print(f"TEACH EVENT> key {low}")

        def on_release(key):
            name = key_name(key).lower()
            if name in modifier_names:
                self._pressed_modifiers.discard(name)

        self._mouse_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        self._key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse_listener.start()
        self._key_listener.start()
        print("TEACH> recording started")
        return True, "Teach Mode started. Show me the workflow, then say stop learning and give it a name."

    def stop_and_save(self, name):
        if not self.recording:
            return False, "I'm not currently learning a workflow."
        self.recording = False

        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
            if self._key_listener:
                self._key_listener.stop()
        except Exception:
            pass

        safe = _safe_name(name)
        low = safe.lower()
        if any(term in low for term in SENSITIVE_KEYS):
            self.events = []
            return False, "I won't save workflows that appear to involve sensitive credentials or payments."

        payload = {
            "name": safe,
            "created_at": datetime.now().isoformat(),
            "screen_size": list(pyautogui.size()),
            "events": self.events,
            "privacy": "Typed character content is intentionally not stored.",
        }
        path = _workflow_path(safe)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        count = len(self.events)
        print(f"TEACH> saved {count} events -> {path}")
        self.events = []
        return True, f"I learned {safe} with {count} actions."

    def cancel(self):
        if not self.recording:
            return False, "Teach Mode is not active."
        self.recording = False
        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
            if self._key_listener:
                self._key_listener.stop()
        except Exception:
            pass
        self.events = []
        print("TEACH> cancelled")
        return True, "Teach Mode cancelled."

def list_workflows():
    items=[]
    for p in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            data=json.loads(p.read_text(encoding="utf-8"))
            items.append(data.get("name") or p.stem)
        except Exception:
            pass
    return items

def delete_workflow(name):
    p=_workflow_path(name)
    if not p.exists():
        return False, f"I couldn't find a workflow called {name}."
    p.unlink()
    return True, f"Deleted workflow {name}."

def replay_workflow(name, speed=1.0):
    p=_workflow_path(name)
    if not p.exists():
        return False, f"I couldn't find a learned workflow called {name}."

    data=json.loads(p.read_text(encoding="utf-8"))
    events=data.get("events",[])
    if not events:
        return False, f"The workflow {name} has no recorded actions."

    original_size=data.get("screen_size") or list(pyautogui.size())
    current_size=list(pyautogui.size())
    sx=current_size[0]/max(1, original_size[0])
    sy=current_size[1]/max(1, original_size[1])

    print(f"TEACH REPLAY> {name} | {len(events)} events")
    last_t=0.0
    for idx,event in enumerate(events,1):
        target_t=float(event.get("t",0))
        delay=max(0.0, min(3.0, (target_t-last_t)/max(0.2,speed)))
        if delay:
            time.sleep(delay)
        last_t=target_t

        typ=event.get("type")
        print(f"TEACH REPLAY STEP> {idx}/{len(events)} {typ}")
        if typ=="click":
            x=round(event.get("x",0)*sx)
            y=round(event.get("y",0)*sy)
            pyautogui.click(x,y,button=event.get("button","left"))
        elif typ=="scroll":
            pyautogui.scroll(int(event.get("amount",0)))
        elif typ=="key":
            pyautogui.press(event.get("key","enter"))
        elif typ=="hotkey":
            keys=[]
            for k in event.get("keys",[]):
                k=str(k).lower()
                if k.startswith("ctrl"): k="ctrl"
                elif k.startswith("alt"): k="alt"
                elif k.startswith("shift"): k="shift"
                elif k.startswith("cmd"): k="win"
                keys.append(k)
            if keys:
                pyautogui.hotkey(*keys)

    return True, f"Finished learned workflow {data.get('name',name)}."
