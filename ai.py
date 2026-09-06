import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_MEMORY_TURNS

SYSTEM_PROMPT = (
    "You are Ultron, a capable Windows desktop voice AI assistant. "
    "Be helpful, confident, concise and natural when spoken aloud. "
    "Keep most answers to 1 to 3 sentences unless the user explicitly asks for detail. "
    "You may explain, summarize, brainstorm, help with code, calculations, and questions."
)


class AIServiceBusy(RuntimeError):
    pass


class UltronAI:
    def __init__(self, long_term_memory=None):
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env")
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.memory = []
        self.long_term_memory = long_term_memory
        self.models = []
        for name in [GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-3.6-flash"]:
            if name and name not in self.models:
                self.models.append(name)
        # v10.5: remember quota/capacity failures so one autonomous task does not
        # repeatedly hammer an already exhausted model. Values are timestamps;
        # float("inf") means disabled for the rest of this process/session.
        self.model_unavailable_until = {}

    def _memory_text(self):
        return "\n".join(
            f"User: {user}\nUltron: {assistant}"
            for user, assistant in self.memory[-MAX_MEMORY_TURNS:]
        )

    @staticmethod
    def _is_capacity_error(exc):
        message = str(exc).lower()
        return any(x in message for x in (
            "503", "unavailable", "high demand", "overloaded", "resource exhausted",
            "429", "too many requests", "rate limit", "quota"
        ))

    @staticmethod
    def _quota_kind(exc):
        message = str(exc).lower()
        # Free-tier daily exhaustion should not be retried again this session.
        if any(x in message for x in (
            "perday", "per day", "requestsperday",
            "generaterequestsperday", "daily quota"
        )):
            return "daily"
        if any(x in message for x in (
            "perminute", "per minute", "requestsperminute",
            "generaterequestsperminute", "retrydelay", "429",
            "resource_exhausted", "resource exhausted", "rate limit"
        )):
            return "temporary"
        if any(x in message for x in ("503", "unavailable", "high demand", "overloaded")):
            return "temporary"
        return None

    @staticmethod
    def _retry_seconds(exc, default=60.0):
        message = str(exc)
        # Handles strings such as retryDelay='22s' and 'Please retry in 8.2s'.
        m = re.search(r"retry(?:delay| in)?[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)s", message, re.I)
        if m:
            try:
                return max(5.0, min(120.0, float(m.group(1)) + 2.0))
            except Exception:
                pass
        return default

    def _mark_model_capacity(self, model, exc):
        kind = self._quota_kind(exc)
        if kind == "daily":
            self.model_unavailable_until[model] = float("inf")
            print(f"AI MODEL DISABLED> {model} | daily quota exhausted for this session")
        elif kind == "temporary":
            seconds = self._retry_seconds(exc)
            until = time.time() + seconds
            self.model_unavailable_until[model] = max(
                self.model_unavailable_until.get(model, 0.0), until
            )
            print(f"AI MODEL COOLDOWN> {model} | {seconds:.0f}s")

    def _model_is_available(self, model):
        until = self.model_unavailable_until.get(model, 0.0)
        if until == float("inf"):
            return False
        if until and time.time() < until:
            return False
        if until:
            self.model_unavailable_until.pop(model, None)
        return True

    def _candidate_models(self, preferred=None):
        ordered = []
        for model in (preferred or []) + self.models:
            if model and model not in ordered:
                ordered.append(model)
        available = [m for m in ordered if self._model_is_available(m)]
        skipped = [m for m in ordered if m not in available]
        for model in skipped:
            state = self.model_unavailable_until.get(model)
            label = "session-disabled" if state == float("inf") else "cooldown"
            print(f"AI SKIP> model={model} reason={label}")
        return available

    def _generate(self, contents, config, retries=1, preferred_models=None):
        last_error = None
        models = self._candidate_models(preferred_models)
        if not models:
            raise AIServiceBusy("AI provider is temporarily busy")

        for model in models:
            for attempt in range(max(1, int(retries))):
                try:
                    print(f"AI> model={model} attempt={attempt + 1}")
                    return self.client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    )
                except Exception as e:
                    last_error = e
                    print(f"AI ERROR> {type(e).__name__}: {e}")
                    if self._is_capacity_error(e):
                        self._mark_model_capacity(model, e)
                        # v10.5: move to the next model immediately instead of
                        # spending another request on a quota/capacity failure.
                        break
                    if attempt + 1 < retries:
                        time.sleep(0.5)
                        continue
                    break
        if last_error and self._is_capacity_error(last_error):
            raise AIServiceBusy("AI provider is temporarily busy") from last_error
        raise RuntimeError(f"AI request failed: {last_error}") from last_error

    def ask(self, user_input):
        context = self._memory_text()
        long_memory = ""
        if self.long_term_memory is not None:
            try:
                long_memory = self.long_term_memory.context_for(user_input)
            except Exception as e:
                print(f"MEMORY RETRIEVAL ERROR> {type(e).__name__}: {e}")

        blocks = []
        if long_memory:
            blocks.append(
                "Relevant long-term memories about the user. Use them only when useful "
                "and never pretend they were said in the current turn:\n" + long_memory
            )
        if context:
            blocks.append("Recent conversation:\n" + context)
        blocks.append("User: " + user_input)
        contents = "\n\n".join(blocks)
        response = self._generate(
            contents,
            types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.6,
            ),
        )
        reply = (response.text or "I couldn't generate a response.").strip()
        self.memory.append((user_input, reply))
        self.memory = self.memory[-MAX_MEMORY_TURNS:]
        return reply


    def web_research(self, query, concise=True):
        """Research a topic with Gemini Google Search grounding.

        Returns a spoken-friendly answer. Falls back cleanly if grounding is
        unavailable for the current API/model/quota.
        """
        prompt = (
            "Research the following topic using current web information. "
            "Give a concise, factual answer with the most important findings. "
            "Mention dates when freshness matters and avoid unsupported claims.\n\n"
            + str(query).strip()
        )
        if concise:
            prompt += "\nKeep the answer to about 4 to 6 short bullet-style points suitable for voice."
        last_error = None
        search_tool = types.Tool(google_search=types.GoogleSearch())
        for model in self._candidate_models():
            try:
                print(f"WEB RESEARCH> model={model} query={query!r}")
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[search_tool],
                        temperature=0.2,
                    ),
                )
                text = (response.text or "").strip()
                if not text:
                    raise RuntimeError("Grounded search returned no text.")
                # Print source metadata when exposed by the SDK for terminal demo/debugging.
                try:
                    cand = response.candidates[0] if response.candidates else None
                    gm = getattr(cand, "grounding_metadata", None) if cand else None
                    chunks = getattr(gm, "grounding_chunks", None) if gm else None
                    if chunks:
                        urls = []
                        for chunk in chunks:
                            web = getattr(chunk, "web", None)
                            uri = getattr(web, "uri", None) if web else None
                            title = getattr(web, "title", None) if web else None
                            if uri and uri not in [u for _,u in urls]:
                                urls.append((title or "source", uri))
                        if urls:
                            print("WEB SOURCES>")
                            for title, uri in urls[:6]:
                                print(f"  - {title}: {uri}")
                except Exception as meta_err:
                    print(f"WEB SOURCE META WARN> {meta_err}")
                return text
            except Exception as e:
                last_error = e
                print(f"WEB RESEARCH ERROR> {type(e).__name__}: {e}")
                if self._is_capacity_error(e):
                    self._mark_model_capacity(model, e)
                continue
        if last_error and self._is_capacity_error(last_error):
            raise AIServiceBusy("Web research service is temporarily busy") from last_error
        raise RuntimeError(f"Web research failed: {last_error}") from last_error

    def analyze_image(self, image_path, question="Describe what is visible and help the user.", model_override=None):
        data = Path(image_path).read_bytes()
        preferred = [model_override] if model_override else None
        response = self._generate(
            [
                types.Part.from_bytes(data=data, mime_type="image/png"),
                question,
            ],
            types.GenerateContentConfig(
                system_instruction=(
                    "You are Ultron viewing the user's current computer screen. "
                    "Describe only what is actually visible. Be concise and useful. "
                    "If code or an error is visible, identify it and suggest the next step."
                ),
                temperature=0.25,
            ),
            preferred_models=preferred,
        )
        return (response.text or "I couldn't analyze the screen.").strip()
