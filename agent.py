"""V10 bounded autonomous desktop agent.

Agent mode chooses ONE approved tool at a time, observes again, and stops only
when the visible state supports the goal. It is intentionally capped to avoid
unbounded desktop automation during demos.
"""
import json
import re
import time
from google.genai import types
from actions import screenshot

AGENT_ACTIONS = {
    "open_app", "open_website", "open_setting", "open_folder", "open_file",
    "search_google", "search_youtube", "search_site", "play_youtube", "play_spotify",
    "vision_click", "type_text", "type_and_submit", "keypress", "shortcut",
    "system_control", "scroll", "wait", "verify_screen", "finish",
}

BLOCKED = {
    "buy", "purchase", "checkout", "pay", "payment", "transfer", "send money",
    "delete", "password", "otp", "bank", "upi", "credit card", "debit card",
}


def _json(text):
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end+1]
    return json.loads(text)


class AutonomousAgent:
    def __init__(self, ai, vision, router, max_steps=7):
        self.ai = ai
        self.vision = vision
        self.router = router
        self.max_steps = max(3, min(10, int(max_steps)))

    @staticmethod
    def is_agent_request(command):
        # Speech recognition often hears "agent mode" as "agent mod",
        # "agent mood", or even "agent node". Treat those as the same
        # explicit opt-in without making ordinary commands autonomous.
        c = re.sub(r"[^a-z0-9 ]+", " ", (command or "").lower())
        c = re.sub(r"\s+", " ", c).strip()
        if re.match(r"^agent\s+(?:mode|mod|mood|node)\b", c):
            return True
        return c.startswith((
            "autonomously ", "handle this autonomously ",
            "do this autonomously ", "take care of this ", "complete this autonomously "
        ))

    @staticmethod
    def clean_goal(command):
        c = command.strip()
        patterns = [
            r"^agent\s+(?:mode|mod|mood|node)[:,]?\s*",
            r"^autonomously[:,]?\s*",
            r"^handle this autonomously[:,]?\s*", r"^do this autonomously[:,]?\s*",
            r"^take care of this[:,]?\s*", r"^complete this autonomously[:,]?\s*",
        ]
        for p in patterns:
            c = re.sub(p, "", c, flags=re.I)
        return c.strip()


    @staticmethod
    def _norm(text):
        text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
        # Common speech-recognition spelling variants for the demo headset.
        text = re.sub(r"\brockers?\b", "rockerz", text)
        return re.sub(r"\s+", " ", text).strip()

    def _likely_goal_met(self, goal, screen):
        """Cheap fail-safe hint that decides whether strict verification is worth one call.

        This never declares success itself. It only avoids another planner call when
        the observation already contains strong visible evidence of completion.
        """
        g = self._norm(goal)
        s = self._norm(screen)

        if "connect" in g:
            stop = {
                "connect", "connected", "my", "the", "to", "with", "bluetooth",
                "device", "devices", "audio", "headphone", "headphones", "speaker",
                "speakers", "please", "and", "a", "an"
            }
            tokens = [t for t in g.split() if t not in stop and len(t) >= 3]
            # Target must actually be present; don't confuse some other connected device.
            for t in tokens:
                idx = s.find(t)
                if idx < 0:
                    continue
                nearby = s[max(0, idx - 100):idx + 140]
                if any(neg in nearby for neg in (
                    "not connected", "disconnected", "connecting", "didn t work"
                )):
                    continue
                # Word-boundary prevents "Disconnect button" from being mistaken
                # for a still-available "Connect button".
                if re.search(r"\bconnect button\b", nearby) and "disconnect button" not in nearby:
                    continue
                if (
                    "disconnect button" in nearby
                    or "connected mic audio" in nearby
                    or "connected audio" in nearby
                    or re.search(r"\bconnected\b", nearby)
                ):
                    return True
            return False

        # Other agent goals still use the normal decide loop. Keep this conservative.
        return False

    def _decide(self, goal, screen, history):
        prompt = f"""
You are Ultron's bounded Windows desktop agent. Choose exactly ONE next action.

GOAL: {goal}
CURRENT SCREEN: {screen}
RECENT ACTIONS: {history[-5:] if history else 'none'}
CURRENT CONTEXT: active_target={self.router.active_target!r}, last_query={self.router.last_query!r}

Allowed actions:
- open_app: installed app name
- open_website: website/service
- open_setting: Windows setting name
- open_folder: desktop/downloads/documents/pictures/music/videos
- open_file: filename/search terms
- search_google: query
- search_youtube: query
- search_site: site|||query
- play_youtube: query
- play_spotify: query
- vision_click: visible target description
- type_text: literal text
- type_and_submit: text then Enter
- keypress: enter/tab/esc/up/down/left/right
- shortcut: alt+tab, ctrl+a, ctrl+l, ctrl+t, ctrl+w, ctrl+s, win+d
- system_control: volume_up, volume_down, mute, play_pause, minimize, maximize, switch_window, close_window, show_desktop, task_manager, refresh, brightness_up, brightness_down, battery, system_status
- scroll: up or down
- wait: 0.5 to 3 seconds
- verify_screen: concise expected visible state
- finish: ONLY if CURRENT SCREEN explicitly proves the user's goal is complete

Rules:
1. Prefer direct deterministic actions over vision.
2. Do not claim success from an attempted click; use visible evidence.
3. If a site has a known direct search route, use search_site.
4. Never perform purchase/payment/transfer/password/OTP/deletion/destructive actions.
5. If screen is loading, wait briefly.
6. Do not repeat an action that already failed twice.

Return ONLY JSON:
{{"action":"vision_click","argument":"Connect button next to Rockerz 480","reason":"short reason"}}
""".strip()
        r = self.ai._generate(prompt, types.GenerateContentConfig(temperature=0.05))
        data = _json(r.text or "")
        action = str(data.get("action", "")).strip()
        argument = str(data.get("argument", "")).strip()
        reason = str(data.get("reason", "")).strip()
        if action not in AGENT_ACTIONS:
            raise RuntimeError(f"Agent selected unavailable action: {action}")
        return action, argument, reason

    def _execute(self, action, arg):
        if action == "wait":
            try:
                m = re.search(r"[0-9]+(?:\.[0-9]+)?", str(arg or "1"))
                delay = max(0.3, min(3.0, float(m.group(0)) if m else 1.0))
            except Exception:
                delay = 1.0
            time.sleep(delay)
            return True, f"Waited {delay:.1f} seconds."
        if action == "vision_click":
            path = screenshot()
            ok, msg = self.vision.click_target(path, arg)
            self.router.note_visual_click(arg, ok)
            if ok: time.sleep(0.7)
            return ok, msg
        if action == "verify_screen":
            path = screenshot()
            ok, evidence, confidence = self.vision.verify_state(path, arg)
            return ok, f"{evidence} (confidence {confidence:.2f})"
        if action == "scroll":
            return self.router.execute_non_ai("scroll", arg)
        return self.router.execute_non_ai(action, arg)

    def run(self, goal):
        low = goal.lower()
        if any(x in low for x in BLOCKED):
            return False, "I won't autonomously perform sensitive or destructive actions."

        history = []
        for step_no in range(1, self.max_steps + 1):
            path = screenshot()
            screen = self.vision.describe(
                path,
                "Describe the current app/page and only the visible controls/status relevant to completing a desktop task. Be concise and literal."
            )
            print(f"AGENT OBSERVE {step_no}> {screen}")

            # v10.5 early-stop: if the observation already contains strong
            # completion evidence, spend one strict verification call instead of
            # another decide/action/observe cycle. The heuristic itself never
            # claims success.
            if self._likely_goal_met(goal, screen):
                print(f"AGENT EARLY VERIFY {step_no}> observation suggests goal may already be complete")
                ok, evidence, confidence = self.vision.verify_state(path, goal)
                print(f"AGENT EARLY VERIFY RESULT> success={ok} confidence={confidence:.2f} evidence={evidence}")
                if ok:
                    return True, "Goal completed and visibly verified."

            action, arg, reason = self._decide(goal, screen, history)
            print(f"AGENT DECIDE {step_no}> {action} | {arg} | {reason}")

            if action == "finish":
                # Fail-closed final verification against a fresh screenshot.
                fresh = screenshot()
                ok, evidence, confidence = self.vision.verify_state(fresh, goal)
                print(f"AGENT FINAL VERIFY> success={ok} confidence={confidence:.2f} evidence={evidence}")
                if ok:
                    return True, "Goal completed and visibly verified."
                history.append({"action": "finish_rejected", "result": evidence})
                continue

            try:
                ok, msg = self._execute(action, arg)
            except Exception as e:
                ok, msg = False, f"{type(e).__name__}: {e}"
            print(f"AGENT ACT {step_no}> success={ok} message={msg}")
            history.append({"action": action, "argument": arg, "success": ok, "result": msg})

            # A strict verify_screen action already proves the goal. Do not waste
            # another observe -> decide -> finish -> final-verify cycle.
            if action == "verify_screen" and ok:
                print("AGENT VERIFIED STOP> strict verification succeeded; ending agent loop")
                return True, "Goal completed and visibly verified."

        return False, f"I reached my {self.max_steps}-action safety limit before I could verify the goal."
