import re
from pathlib import Path
from productivity import (add_note, list_notes, add_task, list_tasks, complete_task, add_reminder, add_timer, set_pref, get_pref, smart_find, smart_open, open_in_vscode, close_except, calculate)
from actions import (
    close_app, file_search, keypress, open_app, open_folder, open_website,
    screenshot, screenshot_and_open, search_google, search_youtube, shortcut, spotify_search,
    play_youtube, play_spotify,
    system_control, type_text, open_setting, resolve_setting,
    search_site, supports_direct_site_search, normalize_site_name, open_first_search_result,
    open_file, create_folder, create_text_file, rename_file, move_file,
    clipboard_read, clipboard_write, scroll_screen,
)


class CommandRouter:
    """Local deterministic router.

    Gemini is deliberately NOT used for routing. This keeps desktop commands
    available even when the AI API is overloaded.
    """

    def __init__(self, ai, memory=None):
        self.ai = ai
        self.memory = memory
        # Lightweight local context for follow-up voice commands.
        # Example: "open YouTube" -> "search for Python tutorials".
        self.active_target = None
        self.last_intent = None
        self.last_query = None
        # Tracks a visually focused search input, e.g. after
        # "click the search box". This lets the next "search for X"
        # type into the already-focused field instead of reopening a URL.
        self.focused_search_target = None

    def route(self, command):
        c = command.lower().strip()

        if c in {
            "exit", "quit", "goodbye", "bye", "bye bye", "bye-bye",
            "go to sleep", "shutdown ultron", "stop ultron", "good night"
        }:
            return "exit", ""

        # Explicit long-term memory commands. These remain local and persistent.
        m = re.match(r"^remember(?: that)? (.+)$", c)
        if m:
            return "remember", m.group(1).strip()

        if c in {"what do you remember", "show my memories", "recent memories"}:
            return "recent_memories", ""

        m = re.match(r"^what do you remember about (.+)$", c)
        if m:
            return "recall_memory", m.group(1).strip()

        if c in {"memory status", "how many memories do you have"}:
            return "memory_status", ""

        if c in {"forget everything", "clear memory", "clear your memory"}:
            return "clear_memory", ""

        m = re.match(r"^forget(?: that| about)? (.+)$", c)
        if m:
            return "forget_memory", m.group(1).strip()


        # V10.7 Daily Computer Assistant Pack: local-first productivity.
        m = re.match(r"^(?:take a note|note this|save a note)(?: that)? (.+)$", c)
        if m: return "add_note", m.group(1).strip()
        if c in {"show my notes", "what are my notes", "read my notes", "recent notes"}: return "list_notes", ""
        m = re.match(r"^(?:add|put) (.+?) (?:to|on) my (?:tasks|task list|to do list|todo list)$", c)
        if m: return "add_task", m.group(1).strip()
        if c in {"what are my tasks", "show my tasks", "task list", "to do list", "todo list"}: return "list_tasks", ""
        m = re.match(r"^(?:mark|complete|finish) (.+?) (?:as complete|complete|done)$", c)
        if m: return "complete_task", m.group(1).strip()
        m = re.match(r"^set (?:a )?timer (?:for )?(\d+\s*(?:seconds?|minutes?|hours?))$", c)
        if m: return "timer", m.group(1)
        m = re.match(r"^remind me (in \d+\s*(?:seconds?|minutes?|hours?)) to (.+)$", c)
        if m: return "reminder", f"{m.group(1)}|||{m.group(2)}"
        m = re.match(r"^remind me (?:at )?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?) to (.+)$", c)
        if m: return "reminder", f"{m.group(1)}|||{m.group(2)}"
        m = re.match(r"^(?:whenever i say|when i say) (.+?),? (?:use|open) (.+)$", c)
        if m: return "set_preference", f"{m.group(1).strip()}|||{m.group(2).strip()}"
        m = re.match(r"^(?:find|locate) (?:the |my )?(.+?)(?: file)?$", c)
        if m and any(x in c for x in ["pdf","file","resume","downloaded","recent"]): return "smart_file_find", m.group(1).strip()
        m = re.match(r"^(?:open|find and open) (?:the |my )?(.+?)(?: file)?$", c)
        if m and any(x in c for x in ["pdf","resume","downloaded","recent file"]): return "smart_file_open", m.group(1).strip()
        m = re.match(r"^open (.+?) (?:project )?in (?:vs code|visual studio code)$", c)
        if m: return "open_in_vscode", m.group(1).strip()
        m = re.match(r"^close everything except (.+)$", c)
        if m: return "close_except", m.group(1).strip()
        if re.match(r"^(?:calculate |what is |what's )?[0-9.,+\-*/()% ]+(?: of [0-9.,]+)?$", c) or re.search(r"\d+(?:\.\d+)?\s*%\s*of\s*\d", c):
            return "calculate", c
        if c in {"next song", "next track", "skip song", "skip track"}: return "system_control", "next_track"
        if c in {"previous song", "previous track"}: return "system_control", "previous_track"
        m = re.match(r"^(?:set )?volume (?:to )?(\d{1,3})(?: percent)?$", c)
        if m: return "system_control", "volume_set:" + m.group(1)
        if c in {"draft an email", "write an email", "compose an email"}: return "email_draft", ""
        m = re.match(r"^(?:draft|write|compose) an email (?:to )?(.+)$", c)
        if m: return "email_draft", m.group(1).strip()
        if c in {"what's on my schedule today", "what is on my schedule today", "my calendar today", "my schedule today"}: return "calendar_today", ""
        if c in {"summarize this pdf", "summarise this pdf", "summarize this document", "summarise this document"}: return "screen_analyze", "Summarize the visible PDF or document. Give the title/topic and 5 concise key points based only on visible content."
        if c in {"explain what i copied", "explain what i just copied"}: return "clipboard_ai", "explain"
        if c in {"summarize what i copied", "summarise what i copied"}: return "clipboard_ai", "summarize"
        if c in {"look at this error and fix it", "fix the error on my screen"}: return "screen_analyze", "Read the visible error, identify the likely cause, and give the exact next safe fix steps. Do not invent unseen code."

        m = re.match(r"^(?:open|launch) (?:my )?([a-z0-9 _-]+)$", c)
        if m:
            pref = get_pref(m.group(1).strip())
            if pref: return "open_app", pref

                # V10 clipboard intelligence routes.
        if c in {"what's in my clipboard", "what is in my clipboard", "read my clipboard", "show clipboard"}:
            return "clipboard_read", ""

        m = re.match(r"^(?:copy to clipboard|put on clipboard) (.+)$", c)
        if m:
            return "clipboard_write", m.group(1).strip()

        if c in {"summarize my clipboard", "summarise my clipboard"}:
            return "clipboard_ai", "summarize"
        if c in {"rewrite my clipboard professionally", "make my clipboard professional"}:
            return "clipboard_ai", "professional"
        m = re.match(r"^translate my clipboard (?:to|into) (.+)$", c)
        if m:
            return "clipboard_ai", "translate:" + m.group(1).strip()
        if c in {"explain my clipboard", "explain this clipboard"}:
            return "clipboard_ai", "explain"

        # V10 filesystem routes. Keep these explicit so single-step file commands
        # never fall through to Gemini/planner interpretation.
        m = re.match(r"^(?:open file|open my file) (.+)$", c)
        if m:
            return "open_file", m.group(1).strip()

        # create [a] folder [called/named] NAME [on/in desktop|documents|downloads]
        m = re.match(r"^create (?:a )?folder(?: (?:called|named))? (.+?)(?: (?:on|in) (desktop|documents|downloads))?$", c)
        if m:
            name = m.group(1).strip()
            location = (m.group(2) or "desktop").strip()
            return "create_folder", f"{location}|||{name}"

        # Create a text/markdown file inside an existing named folder.
        # Examples:
        # create a file called test.txt inside Ultron Demo saying hello
        # create a text file named notes inside Ultron Demo on desktop containing hello
        nested_patterns = [
            r"^create (?:a )?(?:text |txt |markdown |md )?file (?:called|named) ([^,]+?) inside (?:the )?(.+?) (?:on|in) (desktop|documents|downloads) (?:saying|containing|with) (.+)$",
            r"^create (?:a )?(?:text |txt |markdown |md )?file (?:called|named) ([^,]+?) inside (?:the )?(.+?) (?:saying|containing|with) (.+)$",
            r"^create (?:a )?(?:text |txt |markdown |md )?file inside (?:the )?(.+?) (?:called|named) ([^,]+?) (?:saying|containing|with) (.+)$",
        ]
        m = re.match(nested_patterns[0], c)
        if m:
            return "create_text_file", f"{m.group(3)}|||{m.group(2).strip()}|||{m.group(1).strip()}|||{m.group(4).strip()}"
        m = re.match(nested_patterns[1], c)
        if m:
            return "create_text_file", f"folder:{m.group(2).strip()}|||{m.group(1).strip()}|||{m.group(3).strip()}"
        m = re.match(nested_patterns[2], c)
        if m:
            return "create_text_file", f"folder:{m.group(1).strip()}|||{m.group(2).strip()}|||{m.group(3).strip()}"

        # Flexible TXT/MD creation examples:
        # create a text file on desktop called demo.txt saying hello
        # create a file called demo.txt on desktop containing hello
        # create text file named notes in documents with hello
        file_patterns = [
            r"^create (?:a )?(?:text |txt |markdown |md )?file (?:on|in) (desktop|documents|downloads) (?:called|named) ([^,]+?) (?:saying|containing|with) (.+)$",
            r"^create (?:a )?(?:text |txt |markdown |md )?file (?:called|named) ([^,]+?) (?:on|in) (desktop|documents|downloads) (?:saying|containing|with) (.+)$",
            r"^create (?:a )?(?:text |txt |markdown |md )?file (?:called|named) ([^,]+?) (?:saying|containing|with) (.+)$",
        ]
        m = re.match(file_patterns[0], c)
        if m:
            return "create_text_file", f"{m.group(1)}|||{m.group(2).strip()}|||{m.group(3).strip()}"
        m = re.match(file_patterns[1], c)
        if m:
            return "create_text_file", f"{m.group(2)}|||{m.group(1).strip()}|||{m.group(3).strip()}"
        m = re.match(file_patterns[2], c)
        if m:
            return "create_text_file", f"desktop|||{m.group(1).strip()}|||{m.group(2).strip()}"

        m = re.match(r"^rename (.+?) to (.+)$", c)
        if m:
            return "rename_file", f"{m.group(1).strip()}|||{m.group(2).strip()}"

        m = re.match(r"^move (.+?) to (desktop|documents|downloads)$", c)
        if m:
            return "move_file", f"{m.group(1).strip()}|||{m.group(2).strip()}"

        m = re.match(r"^scroll (up|down)(?: (\d+))?$", c)
        if m:
            return "scroll", (m.group(1) + (" " + m.group(2) if m.group(2) else ""))

        # V10.3 grounded web research. Keep this distinct from ordinary Google navigation.
        m = re.match(r"^(?:research|web research|research about|look up the latest on|find the latest about) (.+)$", c)
        if m:
            return "web_research", m.group(1).strip()

        if c.startswith("what are the latest ") or c.startswith("what is the latest "):
            return "web_research", command

        # Screen understanding and visual UI actions.
        m = re.match(r"^(?:click|press|tap) (?:on )?(?:the )?(.+)$", c)
        if m:
            return "vision_click", m.group(1).strip()

        m = re.match(r"^(?:find|locate|where is|where's) (?:the )?(.+?)(?: on (?:my|the) screen)?$", c)
        if m and any(word in c for word in ["screen", "button", "box", "field", "icon", "menu", "link", "tab"]):
            return "vision_find", m.group(1).strip()

        if c in {"read this error", "explain this error", "what does this error mean", "fix this error"}:
            return "screen_analyze", "Read the visible error exactly enough to identify it, explain the likely cause, and give the next 1 to 3 steps to fix it. Do not invent text that is not visible."
        if c in {"summarize this page", "summarise this page", "summarize my screen", "summarise my screen"}:
            return "screen_analyze", "Summarize the visible page in 3 to 5 concise points. Mention the page/app and the most important visible information only."
        if c in {"what should i click", "what should i click next", "where should i click", "what do i do next"}:
            return "screen_analyze", "Based only on the visible screen, identify the most likely next control to use and briefly explain why. Do not click anything."
        if c in {"read this", "read my screen"}:
            return "screen_analyze", "Read and summarize the important visible text on the screen. Preserve error codes, filenames, prices, or key numbers when visible."

        if any(x in c for x in [
            "what's on my screen", "what is on my screen", "what am i looking at", "what am i seeing", "analyze my screen",
            "analyse my screen", "look at my screen", "screen error",
            "explain my screen", "read my screen", "what error is on my screen",
            "what should i do next on my screen", "help me with my screen"
        ]):
            return "screen_analyze", command

        if any(x in c for x in ["take a screenshot", "take screenshot", "screenshot", "screen shot", "capture my screen", "capture the screen"]):
            return "user_screenshot", ""

        # V10.4 deterministic compound website search.
        # Example: "open Google and search for OpenAI" should NOT invoke the
        # planner/vision stack. A stable site search URL can complete it in one step.
        m = re.match(r"^(?:open|launch|go to) (.+?) and (?:search(?: for)?|find) (.+)$", c)
        if m and supports_direct_site_search(m.group(1).strip()):
            site = m.group(1).strip()
            query = m.group(2).strip()
            if normalize_site_name(site) == "youtube":
                return "search_youtube", query
            return "search_site", f"{site}|||{query}"

        # Context-aware follow-up search.
        # If the user just opened YouTube/Google/Spotify, phrases such as
        # "search for lo-fi music" are routed to that service.
        m = re.match(r"^(?:search for|search) (.+)$", c)
        if m:
            query = m.group(1).strip()
            # Prefer deterministic site-native search whenever the current website
            # has a known stable search URL. This avoids brittle UI automation.
            if self.active_target and supports_direct_site_search(self.active_target):
                if normalize_site_name(self.active_target) == "youtube":
                    return "search_youtube", query
                return "search_site", f"{self.active_target}|||{query}"
            if self.focused_search_target:
                return "type_and_submit", query
            # Unknown websites/apps still use generic computer vision.
            return "smart_search", query

        # Context-aware result opening for deterministic search providers.
        if c in {"open the first result", "open first result", "click the first result", "click first result"}:
            if self.active_target and self.last_query:
                if normalize_site_name(self.active_target) in {"google", "youtube"}:
                    return "open_first_site_result", f"{self.active_target}|||{self.last_query}"
            # Other sites use vision because product/result markup changes frequently.
            return "vision_click", "first result"

        # Direct and context-aware playback.
        m = re.match(r"^play (.+?) on youtube$", c)
        if m:
            return "play_youtube", m.group(1).strip()

        m = re.match(r"^play (.+?) on spotify$", c)
        if m:
            return "play_spotify", m.group(1).strip()

        if c in {"play the first video", "play first video", "play that video",
                 "click the first video", "click first video", "open the first video", "open first video",
                 "the first video", "first video", "the first one", "first one"}:
            if self.active_target == "youtube" and self.last_query:
                return "play_youtube", self.last_query

        if c in {"play the first song", "play first song", "play that song", "play it"}:
            if self.active_target == "youtube" and self.last_query:
                return "play_youtube", self.last_query
            if self.active_target == "spotify" and self.last_query:
                return "play_spotify", self.last_query

        m = re.match(r"^play (.+)$", c)
        if m:
            query = m.group(1).strip()
            if self.active_target == "youtube":
                return "play_youtube", query
            return "play_spotify", query

        # Explicit site search: "search Amazon for keyboards", etc.
        m = re.match(r"^(?:search|find) (.+?) (?:for )(.+)$", c)
        if m and supports_direct_site_search(m.group(1).strip()):
            site = m.group(1).strip()
            query = m.group(2).strip()
            if normalize_site_name(site) == "youtube":
                return "search_youtube", query
            return "search_site", f"{site}|||{query}"

        # Search routes BEFORE generic "open" routes.
        patterns = [
            (r"^(?:search|find) youtube (?:for )?(.+)$", "search_youtube"),
            (r"^youtube search (?:for )?(.+)$", "search_youtube"),
            (r"^(?:search|find) google (?:for )?(.+)$", "search_google"),
            (r"^google (.+)$", "search_google"),
            (r"^(?:find file|find my file|find my) (.+)$", "file_search"),
            (r"^type (.+)$", "type_text"),
        ]
        for pattern, intent in patterns:
            m = re.match(pattern, c)
            if m:
                return intent, m.group(1).strip()

        m = re.match(r"^(?:open|launch|start|go to)\s+(.+)$", c)
        if m:
            target = m.group(1).strip()
            uri, _ = resolve_setting(target)
            if uri:
                return "open_setting", target
            folders = {"downloads", "documents", "desktop", "pictures", "music", "videos"}
            websites = {"youtube", "google", "github", "instagram", "gmail", "chatgpt", "linkedin", "spotify", "reddit", "amazon", "claude"}
            if target in folders:
                return "open_folder", target
            if target in websites:
                return "open_website", target
            return "open_app", target

        m = re.match(r"^(?:show|open) (.+?) settings$", c)
        if m:
            target = m.group(1).strip()
            uri, _ = resolve_setting(target)
            if uri:
                return "open_setting", target

        m = re.match(r"^(?:close|exit)\s+(.+)$", c)
        if m:
            return "close_app", m.group(1).strip()

        aliases = {
            "switch window": ("shortcut", "alt+tab"),
            "switch windows": ("shortcut", "alt+tab"),
            "new tab": ("shortcut", "ctrl+t"),
            "open new tab": ("shortcut", "ctrl+t"),
            "close tab": ("shortcut", "ctrl+w"),
            "next tab": ("shortcut", "ctrl+tab"),
            "show desktop": ("shortcut", "win+d"),
            "save": ("shortcut", "ctrl+s"),
            "save this": ("shortcut", "ctrl+s"),
            "undo": ("shortcut", "ctrl+z"),
            "redo": ("shortcut", "ctrl+y"),
            "copy": ("shortcut", "ctrl+c"),
            "paste": ("shortcut", "ctrl+v"),
            "select all": ("shortcut", "ctrl+a"),
            "press enter": ("keypress", "enter"),
            "press escape": ("keypress", "esc"),
            "press tab": ("keypress", "tab"),
            "volume up": ("system_control", "volume_up"),
            "increase volume": ("system_control", "volume_up"),
            "turn up the volume": ("system_control", "volume_up"),
            "volume down": ("system_control", "volume_down"),
            "lower volume": ("system_control", "volume_down"),
            "decrease volume": ("system_control", "volume_down"),
            "mute": ("system_control", "mute"),
            "unmute": ("system_control", "mute"),
            "play pause": ("system_control", "play_pause"),
            "minimize window": ("system_control", "minimize"),
            "minimize this window": ("system_control", "minimize"),
            "maximize window": ("system_control", "maximize"),
            "maximize this window": ("system_control", "maximize"),
            "pause music": ("system_control", "play_pause"),
            "resume music": ("system_control", "play_pause"),
            "battery": ("system_control", "battery"),
            "battery percentage": ("system_control", "battery"),
            "battery status": ("system_control", "battery"),
            "what is my battery percentage": ("system_control", "battery"),
            "what's my battery percentage": ("system_control", "battery"),
            "system status": ("system_control", "system_status"),
            "computer status": ("system_control", "system_status"),
            "lock computer": ("system_control", "lock"),
            "lock my computer": ("system_control", "lock"),
            "switch window": ("system_control", "switch_window"),
            "switch windows": ("system_control", "switch_window"),
            "close current window": ("system_control", "close_window"),
            "close this window": ("system_control", "close_window"),
            "show my desktop": ("system_control", "show_desktop"),
            "open task manager": ("system_control", "task_manager"),
            "task manager": ("system_control", "task_manager"),
            "refresh": ("system_control", "refresh"),
            "refresh page": ("system_control", "refresh"),
            "brightness up": ("system_control", "brightness_up"),
            "increase brightness": ("system_control", "brightness_up"),
            "turn up brightness": ("system_control", "brightness_up"),
            "brightness down": ("system_control", "brightness_down"),
            "decrease brightness": ("system_control", "brightness_down"),
            "lower brightness": ("system_control", "brightness_down"),
        }
        if c in aliases:
            return aliases[c]

        # Anything not matching an approved local action is conversational AI.
        return "ask_ai", command

    def note_visual_click(self, target, success):
        """Record useful UI focus after a successful visual click."""
        if not success:
            return
        t = (target or "").lower().strip()
        search_words = ("search box", "search bar", "search field", "search input")
        if any(word in t for word in search_words) or t == "search":
            # Preserve the current service context when known.
            self.focused_search_target = self.active_target or "screen"
            print(f"STATE> focused_search_target={self.focused_search_target}")
        else:
            # A click elsewhere means we should not assume a search box remains focused.
            self.focused_search_target = None

    def _remember_action(self, intent, argument, handled):
        if not handled:
            return
        self.last_intent = intent
        if intent == "open_website":
            self.active_target = argument.lower().strip()
        elif intent == "search_youtube":
            self.active_target = "youtube"
            self.last_query = argument
        elif intent == "play_youtube":
            self.active_target = "youtube"
            self.last_query = argument
        elif intent == "search_google":
            self.active_target = "google"
            self.last_query = argument
        elif intent == "search_site":
            try:
                site, query = argument.split("|||", 1)
                self.active_target = normalize_site_name(site)
                self.last_query = query
            except ValueError:
                pass
        elif intent == "spotify_search":
            self.active_target = "spotify"
            self.last_query = argument
        elif intent == "play_spotify":
            self.active_target = "spotify"
            self.last_query = argument
        elif intent == "type_and_submit":
            self.last_query = argument
            # The submit consumes the focused input state but preserves service context.
            self.focused_search_target = None
        elif intent in {"open_app", "open_folder"}:
            # Don't let an old browser context hijack later generic searches.
            self.active_target = None

    def execute_non_ai(self, intent, argument):
        if intent == "remember":
            if self.memory is None:
                result = (False, "")
            else:
                result = self.memory.add(argument)
        elif intent == "recall_memory":
            if self.memory is None:
                result = (False, "")
            else:
                matches = self.memory.search(argument, limit=4)
                if not matches:
                    result = (True, "I don't have a relevant long-term memory about that yet.")
                elif len(matches) == 1:
                    result = (True, f"I remember that {matches[0]['text']}.")
                else:
                    joined = "; ".join(m['text'] for m in matches[:3])
                    result = (True, f"I remember: {joined}.")
        elif intent == "recent_memories":
            if self.memory is None:
                result = (False, "")
            else:
                items = self.memory.recent(limit=5)
                if not items:
                    result = (True, "My long-term memory is empty.")
                else:
                    result = (True, "My recent memories are: " + "; ".join(x['text'] for x in items) + ".")
        elif intent == "memory_status":
            if self.memory is None:
                result = (False, "")
            else:
                n = self.memory.count()
                result = (True, f"I currently have {n} long-term memories stored locally.")
        elif intent == "forget_memory":
            if self.memory is None:
                result = (False, "")
            else:
                result = self.memory.forget_matching(argument)
        elif intent == "clear_memory":
            if self.memory is None:
                result = (False, "")
            else:
                result = self.memory.clear()
        elif intent == "add_note": result = add_note(argument)
        elif intent == "list_notes": result = list_notes()
        elif intent == "add_task": result = add_task(argument)
        elif intent == "list_tasks": result = list_tasks()
        elif intent == "complete_task": result = complete_task(argument)
        elif intent == "reminder": result = add_reminder(argument)
        elif intent == "timer": result = add_timer(argument)
        elif intent == "set_preference": result = set_pref(argument)
        elif intent == "smart_file_find":
            hits=smart_find(argument)
            result=(True, ("I found " + Path(hits[0]).name) if hits else "I couldn't find a matching file.")
        elif intent == "smart_file_open": result = smart_open(argument)
        elif intent == "open_in_vscode": result = open_in_vscode(argument)
        elif intent == "close_except": result = close_except(argument)
        elif intent == "calculate": result = calculate(argument)
        elif intent == "open_app": result = open_app(argument)
        elif intent == "close_app": result = close_app(argument)
        elif intent == "open_website": result = open_website(argument)
        elif intent == "open_setting": result = open_setting(argument)
        elif intent == "search_google": result = search_google(argument)
        elif intent == "search_youtube": result = search_youtube(argument)
        elif intent == "search_site":
            try:
                site, query = argument.split("|||", 1)
                result = search_site(site, query)
            except ValueError:
                result = (False, "")
        elif intent == "open_first_site_result":
            try:
                site, query = argument.split("|||", 1)
                result = open_first_search_result(site, query)
            except ValueError:
                result = (False, "")
        elif intent == "play_youtube": result = play_youtube(argument)
        elif intent == "spotify_search": result = spotify_search(argument)
        elif intent == "play_spotify": result = play_spotify(argument)
        elif intent == "type_and_submit":
            # Replace any selected/placeholder text, type the query, then submit.
            shortcut("ctrl+a")
            typed, _ = type_text(argument)
            if typed:
                keypress("enter")
                service = self.active_target.capitalize() if self.active_target else "the current page"
                result = (True, f"Searching {service} for {argument}.")
            else:
                result = (False, "")
        elif intent == "open_folder": result = open_folder(argument)
        elif intent == "type_text": result = type_text(argument)
        elif intent == "keypress": result = keypress(argument)
        elif intent == "shortcut": result = shortcut(argument)
        elif intent == "system_control": result = system_control(argument)
        elif intent == "file_search":
            matches = file_search(argument)
            if not matches:
                result = (True, "I couldn't find a matching file.")
            elif len(matches) == 1:
                result = (True, f"I found {matches[0]}")
            else:
                result = (True, f"I found {len(matches)} matching files. The first is {matches[0]}")
        elif intent == "open_file": result = open_file(argument)
        elif intent == "create_folder": result = create_folder(argument)
        elif intent == "create_text_file": result = create_text_file(argument)
        elif intent == "rename_file": result = rename_file(argument)
        elif intent == "move_file": result = move_file(argument)
        elif intent == "clipboard_read": result = clipboard_read()
        elif intent == "clipboard_write": result = clipboard_write(argument)
        elif intent == "scroll": result = scroll_screen(argument)
        elif intent == "user_screenshot":
            result = screenshot_and_open()
        elif intent == "screenshot":
            path = screenshot()
            result = (True, f"Screenshot captured and saved to {path}")
        else:
            result = (False, "")

        handled = bool(result[0]) if isinstance(result, tuple) and result else False
        self._remember_action(intent, argument, handled)
        return result
