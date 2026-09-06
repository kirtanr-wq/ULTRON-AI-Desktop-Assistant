import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from google.genai import types
from actions import supports_direct_site_search


ALLOWED_ACTIONS = {
    "open_app", "close_app", "open_website", "open_setting", "open_folder",
    "search_google", "search_youtube", "search_site", "play_youtube", "play_spotify",
    "vision_click", "vision_find", "type_text", "type_and_submit",
    "keypress", "shortcut", "system_control", "wait", "verify_screen",
    "open_file", "create_folder", "create_text_file", "rename_file", "move_file",
    "clipboard_read", "clipboard_write", "scroll",
}

SENSITIVE_TERMS = {
    "buy", "purchase", "checkout", "pay", "payment", "transfer", "send money",
    "delete account", "delete everything", "password", "otp", "one time password",
    "bank", "upi", "credit card", "debit card",
}


@dataclass
class PlanStep:
    action: str
    argument: str = ""
    expected: str = ""


class TaskPlanner:
    """Constrained multi-step planner for Ultron.

    The model may choose only from ALLOWED_ACTIONS. Execution remains local and
    deterministic, with visual tools used only when direct actions are unavailable.
    """

    def __init__(self, ai):
        self.ai = ai

    @staticmethod
    def should_plan(command: str) -> bool:
        c = (command or "").lower().strip()
        if not c:
            return False
        # A compound open+search request for a site with a stable direct search
        # URL is actually a single deterministic action. Let the local router handle it.
        direct = re.match(r"^(?:open|launch|go to) (.+?) and (?:search(?: for)?|find) (.+)$", c)
        if direct and supports_direct_site_search(direct.group(1).strip()):
            return False

        # Explicit goal language always opts into planning.
        if c.startswith(("do this task ", "do this for me ", "complete this task ", "plan and ")):
            return True
        # Natural multi-action requests.
        connectors = (" and then ", " then ", " after that ", " afterwards ", " and search ",
                      " and click ", " and open ", " and play ", " and type ", " and press ",
                      " and connect ")
        if any(x in c for x in connectors):
            return True
        # Two or more clear action verbs usually indicates a compound goal.
        verbs = re.findall(r"\b(open|launch|search|find|click|press|type|play|close|connect|go|turn)\b", c)
        return len(verbs) >= 2

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
            text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        return json.loads(text)

    @staticmethod
    def is_sensitive_goal(goal: str) -> bool:
        low = (goal or "").lower()
        return any(term in low for term in SENSITIVE_TERMS)

    def create_plan(self, goal: str, context: str = "") -> List[PlanStep]:
        if self.is_sensitive_goal(goal):
            raise ValueError("That multi-step task includes a sensitive action I won't automate.")

        prompt = f"""
You are the planning module for Ultron, a Windows desktop voice agent.
Convert the user's goal into the SHORTEST reliable sequence of executable actions.

USER GOAL:
{goal}

CURRENT CONTEXT:
{context or 'No extra context.'}

Allowed actions ONLY:
- open_app: argument is an installed app name
- close_app: app name
- open_website: website/service name
- open_setting: Windows setting name, e.g. bluetooth, wifi, display, sound
- open_folder: downloads/documents/desktop/pictures/music/videos
- search_google: query
- search_youtube: query
- search_site: argument MUST be site|||query, e.g. amazon|||mechanical keyboards
- play_youtube: query
- play_spotify: query
- vision_click: visible target label, e.g. first result, connect button, profile icon
- vision_find: visible target label
- type_text: literal text to type into the currently focused field
- type_and_submit: text to type then press Enter
- keypress: one key such as enter, tab, esc
- shortcut: approved shortcut such as ctrl+l, ctrl+a, alt+tab
- system_control: volume_up, volume_down, mute, play_pause, battery, system_status, lock, minimize, maximize
- open_file: filename/search terms
- create_folder: location|||folder name; location is desktop/documents/downloads
- create_text_file: location|||filename|||content OR location|||subfolder|||filename|||content
- create_text_file: location|||filename|||content; only .txt or .md
- rename_file: search terms|||new filename
- move_file: search terms|||desktop/documents/downloads
- clipboard_read: no argument
- clipboard_write: literal text
- scroll: up or down
- wait: number of seconds, maximum 4
- verify_screen: a short statement describing what should now be visible

Planning rules:
1. Prefer deterministic actions over vision. Example: use search_site for Amazon/Google/GitHub/etc. instead of visually finding their search box.
2. Use vision_click only when a direct action cannot perform the requested UI interaction.
3. After opening an app/site/settings page, add wait 1 only if the next action needs the UI loaded.
4. Use verify_screen after important visual clicks or at the final state when success can be seen.
5. Maximum 8 steps.
6. Do NOT plan purchases, payments, money transfers, account deletion, password/OTP entry, or irreversible destructive actions.
7. Do not invent unavailable actions.

Return ONLY JSON:
{{
  "steps": [
    {{"action": "open_website", "argument": "youtube", "expected": "YouTube opens"}}
  ]
}}
""".strip()

        response = self.ai._generate(
            prompt,
            types.GenerateContentConfig(
                system_instruction="You are a strict desktop task planner. Output JSON only.",
                temperature=0.1,
            ),
        )
        data = self._extract_json(response.text or "")
        raw_steps = data.get("steps") or []
        steps: List[PlanStep] = []
        for item in raw_steps[:8]:
            action = str(item.get("action", "")).strip()
            if action not in ALLOWED_ACTIONS:
                continue
            argument = str(item.get("argument", "")).strip()
            expected = str(item.get("expected", "")).strip()
            if action == "wait":
                try:
                    seconds = max(0.2, min(4.0, float(argument or 1)))
                    argument = str(seconds)
                except Exception:
                    argument = "1.0"
            steps.append(PlanStep(action, argument, expected))
        if not steps:
            raise RuntimeError("Planner returned no executable steps.")

        goal_low = (goal or "").lower()
        if "connect" in goal_low and not any(s.action == "verify_screen" for s in steps):
            steps.append(PlanStep(
                "verify_screen",
                "The requested device is visibly shown as Connected or an equivalent explicit connected status.",
                "The requested device is visibly connected."
            ))
        return steps[:8]

    def verify(self, screen_description: str, expectation: str) -> bool:
        if not expectation:
            return True
        prompt = f"""
You are a strict UI-state verifier. Decide whether the expected state is EXPLICITLY proven by the visible-screen evidence.
EXPECTED: {expectation}
SCREEN EVIDENCE: {screen_description}

Rules:
- Return success=true ONLY when the screen evidence explicitly shows the expected state.
- A clicked button, attempted action, device name, or presence of a Connect button is NOT proof of success.
- For connection tasks, require visible wording such as Connected, Paired and connected, or an equivalent unmistakable connected-status indicator.
- If the evidence is ambiguous, incomplete, inferred, stale, or merely says the action was attempted, return success=false.
- Never assume success from the plan or previous steps.

Return ONLY JSON: {"success": false, "reason": "short evidence-based reason"}
""".strip()
        response = self.ai._generate(
            prompt,
            types.GenerateContentConfig(temperature=0.0),
        )
        try:
            data = self._extract_json(response.text or "")
            ok = bool(data.get("success", False))
            print(f"PLAN VERIFY> success={ok} reason={data.get('reason','')}")
            return ok
        except Exception as e:
            print(f"PLAN VERIFY PARSE ERROR> {e}")
            return False  # malformed/uncertain verification must never count as success

    def replan(self, goal: str, completed: List[PlanStep], failure: str, screen_description: str) -> List[PlanStep]:
        completed_text = "; ".join(f"{s.action}({s.argument})" for s in completed) or "none"
        context = (
            f"Completed steps: {completed_text}. The previous attempt failed because: {failure}. "
            f"Current screen: {screen_description}. Plan ONLY the remaining work and avoid repeating successful steps."
        )
        return self.create_plan(goal, context=context)
