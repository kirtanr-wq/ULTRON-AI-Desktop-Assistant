"""Visual screen understanding and safe UI targeting for Ultron."""
import json
import re

import pyautogui


SENSITIVE_WORDS = {
    "buy", "purchase", "pay", "payment", "checkout", "place order",
    "delete", "remove account", "factory reset", "format", "send money",
    "transfer", "confirm payment", "authorize", "unsubscribe",
}


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _normalize_bbox(data):
    # Accept either bbox=[ymin,xmin,ymax,xmax] in 0..1000,
    # bbox=[x1,y1,x2,y2] in 0..1, or x/y center coordinates.
    bbox = data.get("bbox") or data.get("box_2d") or data.get("bbox_2d")
    if isinstance(bbox, list) and len(bbox) == 4:
        vals = [float(v) for v in bbox]
        # Our prompt asks for [ymin, xmin, ymax, xmax] in 0..1000.
        if max(vals) > 1.5:
            ymin, xmin, ymax, xmax = [v / 1000.0 for v in vals]
        else:
            ymin, xmin, ymax, xmax = vals
        if 0 <= xmin <= xmax <= 1 and 0 <= ymin <= ymax <= 1:
            return xmin, ymin, xmax, ymax

    x, y = data.get("x"), data.get("y")
    if x is not None and y is not None:
        x, y = float(x), float(y)
        if x > 1.5 or y > 1.5:
            x, y = x / 1000.0, y / 1000.0
        if 0 <= x <= 1 and 0 <= y <= 1:
            pad = 0.02
            return max(0, x-pad), max(0, y-pad), min(1, x+pad), min(1, y+pad)
    return None


class ScreenVision:
    def __init__(self, ai):
        self.ai = ai
        self.last_target = None

    def describe(self, image_path, question):
        return self.ai.analyze_image(image_path, question)

    def locate(self, image_path, target):
        prompt = f"""
You are a precise GUI element localizer looking at a Windows desktop screenshot.
Find the single visible UI element that best matches this user target: {target!r}

Return ONLY one JSON object with this exact schema:
{{
  "found": true,
  "label": "visible label or concise description",
  "bbox": [ymin, xmin, ymax, xmax],
  "confidence": 0.0,
  "reason": "brief visual reason"
}}

Rules:
- bbox values MUST be integers from 0 to 1000.
- bbox order is [ymin, xmin, ymax, xmax].
- The box must tightly surround the clickable element itself.
- Search fields may be identified by magnifying-glass icon, placeholder text, or the long input rectangle.
- If several candidates exist, choose the most prominent visible one matching the request.
- Set found=false ONLY when no plausible visible target exists.
- Do not return markdown or prose outside the JSON.
""".strip()
        raw = self.ai.analyze_image(image_path, prompt, model_override="gemini-3.6-flash")
        print(f"VISION RAW> {raw[:500]}")
        try:
            data = _extract_json(raw)
            box = _normalize_bbox(data)
        except Exception as e:
            print(f"VISION JSON ERROR> {e}; raw={raw[:500]!r}")
            return {"found": False, "confidence": 0.0, "reason": "I couldn't parse the visual target."}

        found = bool(data.get("found", True)) and box is not None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0

        result = {
            "found": found,
            "label": data.get("label") or target,
            "confidence": confidence,
            "reason": data.get("reason", ""),
        }
        if found:
            xmin, ymin, xmax, ymax = box
            result.update({
                "bbox": [xmin, ymin, xmax, ymax],
                "x": (xmin + xmax) / 2.0,
                "y": (ymin + ymax) / 2.0,
            })
            self.last_target = result
            print(f"VISION LOCATE> {result}")
        else:
            print(f"VISION MISS> target={target!r} parsed={data}")
        return result


    def locate_ranked_result(self, image_path, target):
        """Locate ordinal content results such as first video / second result.

        This uses a result-list-specific prompt rather than the generic GUI locator.
        It is more reliable on search result pages where many similar cards are visible.
        """
        prompt = f"""
You are locating an item in a visible search-results/feed page on a Windows desktop screenshot.
The user wants to click: {target!r}

Interpret ordinal requests spatially and semantically:
- "first video" = the first visible organic video result in the main results column/feed, not the search bar, navigation, filter chips, Shorts shelf header, or an advertisement.
- "first result" = the first visible organic content result in the main result list.
- "second/third ..." = count only matching organic results in reading order, top to bottom.
- For a video result, prefer the clickable video TITLE or thumbnail bounding box.
- Ignore sponsored/ad results unless the user explicitly says ad/sponsored.

Return ONLY one JSON object:
{{
  "found": true,
  "label": "concise visible title/description",
  "bbox": [ymin, xmin, ymax, xmax],
  "confidence": 0.0,
  "reason": "brief reason"
}}

Rules:
- bbox values are integers 0..1000 in [ymin, xmin, ymax, xmax] order.
- Box the clickable title or thumbnail itself, not the entire page/card if avoidable.
- Set found=false only if the requested ranked result is not visibly present.
- No markdown outside JSON.
""".strip()
        raw = self.ai.analyze_image(image_path, prompt, model_override="gemini-3.6-flash")
        print(f"VISION RESULT RAW> {raw[:500]}")
        try:
            data = _extract_json(raw)
            box = _normalize_bbox(data)
        except Exception as e:
            print(f"VISION RESULT JSON ERROR> {e}; raw={raw[:500]!r}")
            return {"found": False, "confidence": 0.0, "reason": "I couldn't parse the result location."}

        found = bool(data.get("found", True)) and box is not None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0

        result = {
            "found": found,
            "label": data.get("label") or target,
            "confidence": confidence,
            "reason": data.get("reason", ""),
        }
        if found:
            xmin, ymin, xmax, ymax = box
            result.update({
                "bbox": [xmin, ymin, xmax, ymax],
                "x": (xmin + xmax) / 2.0,
                "y": (ymin + ymax) / 2.0,
            })
            self.last_target = result
            print(f"VISION RESULT LOCATE> {result}")
        else:
            print(f"VISION RESULT MISS> target={target!r} parsed={data}")
        return result

    @staticmethod
    def _is_sensitive(target, label=""):
        low = f"{target} {label}".lower()
        return any(word in low for word in SENSITIVE_WORDS)

    def click_target(self, image_path, target, min_confidence=0.35):
        low = (target or "").lower().strip()
        ranked_terms = (
            "first video", "second video", "third video",
            "first result", "second result", "third result",
            "first song", "second song", "third song",
            "first item", "second item", "third item",
        )
        if any(term in low for term in ranked_terms):
            result = self.locate_ranked_result(image_path, target)
        else:
            result = self.locate(image_path, target)
        if not result.get("found"):
            return False, f"I can't clearly find {target} on the current screen."
        if result.get("confidence", 0.0) < min_confidence:
            return False, f"I can see something that may be {target}, but I'm not confident enough to click it."
        if self._is_sensitive(target, result.get("label", "")):
            return False, f"I found {result.get('label') or target}, but I won't automatically click a sensitive action."

        width, height = pyautogui.size()
        px = max(0, min(width - 1, round(result["x"] * width)))
        py = max(0, min(height - 1, round(result["y"] * height)))
        print(f"VISION CLICK> target={target!r} label={result.get('label')!r} confidence={result.get('confidence'):.2f} xy=({px},{py})")
        pyautogui.moveTo(px, py, duration=0.35)
        pyautogui.click()
        return True, f"Clicked {result.get('label') or target}."


    def search_current_screen(self, image_path, query, min_confidence=0.25):
        """Find the primary visible search input once, focus it, type, and submit.

        Important: this deliberately makes ONE vision-model call. Older builds tried
        several synonyms (search box/search bar/search field/...) sequentially,
        which caused multi-second stalls even after the first call had already
        found the correct field.
        """
        target = (
            "the primary visible search input on the current app or website; "
            "this may be a search box, search bar, search field, or input next to a magnifying-glass icon"
        )
        best = self.locate(image_path, target)
        if not best.get("found") or best.get("confidence", 0.0) < min_confidence:
            return False, "I couldn't find a visible search field in the current app."

        width, height = pyautogui.size()
        px = max(0, min(width - 1, round(best["x"] * width)))
        py = max(0, min(height - 1, round(best["y"] * height)))
        print(
            f"VISION SEARCH CLICK> label={best.get('label')!r} "
            f"confidence={best.get('confidence',0):.2f} xy=({px},{py})"
        )
        pyautogui.moveTo(px, py, duration=0.25)
        pyautogui.click()
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(query, interval=0.02)
        pyautogui.press("enter")
        print(f"VISION SEARCH SUBMIT> query={query!r}")
        return True, f"Searching the current app for {query}."


    def verify_state(self, image_path, expectation):
        """Verify a UI state directly from a fresh screenshot.

        This is deliberately fail-closed: ambiguous or malformed model output is
        treated as not confirmed.
        """
        prompt = f"""
Inspect this CURRENT screenshot and verify the following expected state:
{expectation}

Return ONLY JSON with exactly this schema:
{{
  "success": false,
  "confidence": 0.0,
  "evidence": "brief visible evidence"
}}

Strict rules:
- success=true ONLY if the expected state is explicitly visible right now.
- Do not infer success from a button click, a plan, a device name, or an attempted action.
- For Bluetooth/device connection, require explicit visible status such as Connected, Paired and connected, or an unmistakable equivalent.
- Seeing a Connect button generally means the device is NOT yet confirmed connected.
- If text/status is unclear, cropped, loading, ambiguous, or absent, return success=false.
- Confidence must reflect only visible evidence in this screenshot.
""".strip()
        try:
            raw = self.ai.analyze_image(image_path, prompt, model_override="gemini-3.6-flash")
            print(f"VISION VERIFY RAW> {raw}")
            data = _extract_json(raw)
            success = bool(data.get("success", False))
            try:
                confidence = float(data.get("confidence", 0.0))
            except Exception:
                confidence = 0.0
            evidence = str(data.get("evidence", "")).strip()
            # Fail closed on weak positive claims.
            if success and confidence < 0.70:
                success = False
                evidence = evidence or "Verification confidence was too low."
            print(f"VISION VERIFY> success={success} confidence={confidence:.2f} evidence={evidence}")
            return success, evidence, confidence
        except Exception as e:
            print(f"VISION VERIFY ERROR> {type(e).__name__}: {e}")
            return False, "I could not confirm the expected state from the screen.", 0.0

    def find_target(self, image_path, target):
        result = self.locate(image_path, target)
        if not result.get("found"):
            return True, f"I can't clearly find {target} on the current screen."
        confidence = result.get("confidence", 0.0)
        label = result.get("label") or target
        horiz = "left" if result["x"] < 0.38 else "right" if result["x"] > 0.62 else "center"
        vert = "top" if result["y"] < 0.38 else "bottom" if result["y"] > 0.62 else "middle"
        return True, f"I found {label} around the {vert} {horiz} of the screen, with {confidence:.0%} confidence."
