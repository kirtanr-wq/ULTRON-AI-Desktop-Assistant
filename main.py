"""Ultron voice-only backend entry point.

No GUI. The terminal is diagnostics only; user interaction is entirely speech.
"""
import time
import re

from actions import screenshot, search_google, clipboard_read, clipboard_write
from ai import UltronAI, AIServiceBusy
from config import WAKE_WORD
from router import CommandRouter
from memory import LongTermMemory
from voice import listen, speak, test_microphone
from vision import ScreenVision
from planner import TaskPlanner
from agent import AutonomousAgent
from productivity import start_reminder_worker
from teach_mode import WorkflowRecorder, replay_workflow, list_workflows, delete_workflow


def say(text):
    text = str(text).strip()
    if not text:
        return
    print(f"\nULTRON> {text}")
    speak(text if len(text) <= 700 else text[:700])


def extract_wake_command(text):
    """Return text after the wake word, or None if the wake word was not heard."""
    original = str(text or "").strip()
    wake = WAKE_WORD.strip()
    if not wake:
        return None
    match = re.search(r"(?<!\w)" + re.escape(wake) + r"(?!\w)", original, flags=re.IGNORECASE)
    if not match:
        return None
    command = original[match.end():].lstrip(" ,:-").strip()
    return command


def is_standby_command(text):
    """Commands that put Ultron into passive wake-word-only mode."""
    low = str(text or "").lower().strip()
    phrases = {
        "standby",
        "stand by",
        "standby mode",
        "go on standby",
        "go on standby mode",
        "go to standby",
        "go to standby mode",
        "enter standby",
        "enter standby mode",
        "sleep mode",
        "go into standby",
        "go into standby mode",
    }
    return low in phrases or low.startswith("go on standby") or low.startswith("go to standby")



def execute_plan(router, ai, vision, planner, goal):
    """Execute a constrained multi-step plan with one recovery attempt."""
    context = (
        f"active_target={router.active_target!r}, last_query={router.last_query!r}, "
        f"last_intent={router.last_intent!r}"
    )
    try:
        steps = planner.create_plan(goal, context=context)
    except ValueError as e:
        say(str(e))
        return True
    except Exception as e:
        print(f"PLAN ERROR> {type(e).__name__}: {e}")
        return None

    print("PLAN>")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step.action} | {step.argument} | expected={step.expected}")

    say("I have a plan. Executing it now.")
    completed = []
    recovered = False

    while steps:
        step = steps.pop(0)
        print(f"PLAN STEP> {step.action} | {step.argument}")
        ok = False
        message = ""
        try:
            if step.action == "wait":
                delay = max(0.2, min(4.0, float(step.argument or 1)))
                time.sleep(delay)
                ok, message = True, f"Waited {delay:.1f} seconds."

            elif step.action == "vision_click":
                time.sleep(0.5)
                path = screenshot()
                ok, message = vision.click_target(path, step.argument)
                router.note_visual_click(step.argument, ok)
                if ok:
                    time.sleep(0.7)

            elif step.action == "vision_find":
                path = screenshot()
                ok, message = vision.find_target(path, step.argument)

            elif step.action == "verify_screen":
                # Verify directly against a fresh screenshot and fail closed.
                path = screenshot()
                expectation = step.argument or step.expected
                ok, evidence, confidence = vision.verify_state(path, expectation)
                message = evidence or "Expected state was not visibly confirmed."
                print(f"PLAN VERIFY DIRECT> success={ok} confidence={confidence:.2f} evidence={message}")

            else:
                ok, message = router.execute_non_ai(step.action, step.argument)

            print(f"PLAN RESULT> success={ok} message={message}")
        except AIServiceBusy:
            print("PLAN RESULT> AI service busy")
            ok, message = False, "The AI vision/planning service is temporarily busy."
        except Exception as e:
            print(f"PLAN STEP ERROR> {type(e).__name__}: {e}")
            ok, message = False, str(e)

        if ok:
            completed.append(step)
            continue

        if recovered:
            say(f"I couldn't complete the task. The step {step.action.replace('_',' ')} failed.")
            return True

        # One recovery attempt: inspect current screen and re-plan only remaining work.
        recovered = True
        try:
            path = screenshot()
            screen = vision.describe(
                path,
                "Briefly describe the current app, page, and the main visible controls relevant to completing a desktop task."
            )
            print(f"PLAN RECOVERY SCREEN> {screen}")
            steps = planner.replan(goal, completed, message or f"{step.action} failed", screen)
            print("PLAN RECOVERY>")
            for i, new_step in enumerate(steps, 1):
                print(f"  {i}. {new_step.action} | {new_step.argument} | expected={new_step.expected}")
        except Exception as e:
            print(f"PLAN RECOVERY ERROR> {type(e).__name__}: {e}")
            say("I couldn't recover from that step automatically.")
            return True

    say("Task completed.")
    return True


def handle_command(router, ai, vision, command, planner=None, agent=None, teacher=None):
    # V11 Teach Me Mode is intercepted before planner/agent routing.
    # This allows the user to demonstrate real mouse/keyboard navigation once
    # and replay it later without Gemini.
    low = str(command or "").lower().strip()

    if teacher is not None:
        if low in {"learn this workflow", "teach this workflow", "learn a workflow",
                   "teach me this workflow", "start learning", "start teach mode",
                   "teach mode"}:
            ok, message = teacher.start()
            say(message)
            return True

        if teacher.recording:
            m = re.match(
                r"^(?:stop learning|stop teaching)(?: and)?(?: call| name| save)(?: this| it)?(?: as)? (.+)$",
                low
            )
            if m:
                ok, message = teacher.stop_and_save(m.group(1).strip())
                say(message)
                return True
            if low in {"cancel learning", "cancel teach mode", "stop learning without saving"}:
                ok, message = teacher.cancel()
                say(message)
                return True

        m = re.match(r"^(?:run|replay|execute|start) (?:my )?(?:learned )?(.+?)(?: workflow)?$", low)
        if m and not low.startswith(("run agent", "start agent")):
            requested = m.group(1).strip()
            # Only treat it as Teach Mode when a saved workflow actually matches.
            names = list_workflows()
            match = next((n for n in names if n.lower() == requested.lower()), None)
            if match:
                say(f"Running learned workflow {match}.")
                try:
                    ok, message = replay_workflow(match)
                    say(message)
                except Exception as e:
                    print(f"TEACH REPLAY ERROR> {type(e).__name__}: {e}")
                    say("The learned workflow stopped safely because an action failed.")
                return True

        if low in {"what workflows have you learned", "show learned workflows",
                   "list workflows", "show my workflows"}:
            names = list_workflows()
            say("I have learned: " + ", ".join(names) + "." if names else "I haven't learned any workflows yet.")
            return True

        m = re.match(r"^(?:delete|forget) (?:the )?(?:workflow )?(.+?)(?: workflow)?$", low)
        if m:
            ok, message = delete_workflow(m.group(1).strip())
            say(message)
            return True

    # V10 Agent Mode is explicit so stable deterministic/planner behavior is preserved.
    if agent is not None and agent.is_agent_request(command):
        goal = agent.clean_goal(command)
        say("Agent mode engaged.")
        try:
            ok, message = agent.run(goal)
            say(message if ok else "I couldn't fully complete that autonomously. " + message)
        except AIServiceBusy:
            say("My agent reasoning service is busy right now.")
        except Exception as e:
            print(f"AGENT ERROR> {type(e).__name__}: {e}")
            say("Agent mode stopped safely because I hit an unexpected error.")
        return True

    if planner is not None and planner.should_plan(command):
        planned = execute_plan(router, ai, vision, planner, command)
        if planned is not None:
            return planned

    intent, argument = router.route(command)
    print(f"ROUTE> {intent} | {argument}")

    if intent == "exit":
        say("Shutting down core protocols.")
        return False

    if intent == "screen_analyze":
        try:
            path = screenshot()
            answer = vision.describe(path, argument or command)
            say(answer)
        except AIServiceBusy:
            say("My vision service is busy right now. My local controls are still online.")
        return True

    if intent == "vision_find":
        try:
            path = screenshot()
            _, message = vision.find_target(path, argument)
            say(message)
        except AIServiceBusy:
            say("My vision service is busy right now. My local controls are still online.")
        return True

    if intent == "vision_click":
        try:
            # Give freshly loaded search/results pages a brief moment to settle.
            time.sleep(0.65)
            path = screenshot()
            clicked, message = vision.click_target(path, argument)
            router.note_visual_click(argument, clicked)
            say(message)
        except AIServiceBusy:
            say("My vision service is busy right now. My local controls are still online.")
        return True


    if intent == "smart_search":
        try:
            path = screenshot()
            ok, message = vision.search_current_screen(path, argument)
            if ok:
                router.focused_search_target = None
                router.last_query = argument
                say(message)
            else:
                _, fallback = search_google(argument)
                say(f"I couldn't find a search field here, so {fallback.lower()}")
        except AIServiceBusy:
            _, fallback = search_google(argument)
            say(f"My vision service is busy, so {fallback.lower()}")
        return True

    if intent == "clipboard_ai":
        try:
            _, clip = clipboard_read()
            if not clip or clip == "Your clipboard is empty.":
                say("Your clipboard is empty.")
                return True
            mode = argument or "summarize"
            if mode == "summarize":
                prompt = "Summarize this clipboard content concisely:\n\n" + clip
            elif mode == "professional":
                prompt = "Rewrite this clipboard content professionally. Return only the rewritten text:\n\n" + clip
            elif mode.startswith("translate:"):
                lang = mode.split(":", 1)[1]
                prompt = f"Translate this clipboard content into {lang}. Return only the translation:\n\n" + clip
            else:
                prompt = "Explain this clipboard content clearly and concisely:\n\n" + clip
            answer = ai.ask(prompt)
            if mode == "professional" or mode.startswith("translate:"):
                clipboard_write(answer)
                say("Done. I updated your clipboard.")
            else:
                say(answer)
        except AIServiceBusy:
            say("My AI service is busy right now.")
        return True

    if intent == "web_research":
        try:
            say("Researching that now.")
            answer = ai.web_research(argument or command)
            say(answer)
        except AIServiceBusy:
            # Quota/capacity errors are common on free Gemini tiers. Preserve the
            # user's intent by opening the live Google results rather than failing.
            _, fallback = search_google(argument or command)
            print("WEB RESEARCH FALLBACK> AI quota/capacity unavailable; opened Google search")
            say("My grounded research quota is unavailable right now, so I opened a live Google search instead.")
        except Exception as e:
            print(f"WEB RESEARCH ERROR> {type(e).__name__}: {e}")
            # Safe fallback: open a Google search instead of pretending we researched it.
            _, fallback = search_google(argument or command)
            say("I couldn't complete grounded research, so I opened a Google search instead.")
        return True

    if intent == "email_draft":
        try:
            detail = argument or "a concise professional email based on what I tell you next"
            prompt = "Draft a concise email based on this request: " + detail + ". Return a subject line and body. Do not claim it was sent."
            draft = ai.ask(prompt)
            clipboard_write(draft)
            say("I drafted the email and copied it to your clipboard. " + draft)
        except AIServiceBusy:
            say("My AI service is busy, so I couldn't draft the email right now.")
        return True

    if intent == "calendar_today":
        # v10.7 local build deliberately does not pretend it can read a cloud calendar without OAuth.
        say("Calendar account access is not connected in this local build yet. I can still manage Ultron reminders and tasks locally.")
        return True

    if intent == "ask_ai":
        try:
            say(ai.ask(argument or command))
        except AIServiceBusy:
            say("The AI service is busy right now. My local computer controls are still online.")
        return True

    handled, message = router.execute_non_ai(intent, argument)
    if handled:
        say(message)
    else:
        say("I understood the request, but that action is not implemented yet.")
    return True


def main():
    print("=" * 58)
    print("          ULTRON // VOICE AGENT BACKEND")
    print("=" * 58)

    ok, mic_info = test_microphone()
    print(f"MIC> {mic_info}")
    if not ok:
        print("ERROR> Fix MIC_INDEX in .env before starting Ultron.")
        return

    try:
        long_memory = LongTermMemory()
        print(f"MEMORY> {long_memory.count()} persistent memories loaded from {long_memory.db_path}")
        ai = UltronAI(long_term_memory=long_memory)
    except Exception as e:
        print(f"AI INIT ERROR> {e}")
        print("Ultron can only start after GEMINI_API_KEY is present in .env.")
        return

    router = CommandRouter(ai, memory=long_memory)
    vision = ScreenVision(ai)
    planner = TaskPlanner(ai)
    agent = AutonomousAgent(ai, vision, router, max_steps=7)
    teacher = WorkflowRecorder()
    start_reminder_worker(say)
    # V10.6 starts silently. The terminal can show diagnostics, but Ultron does not
    # speak until the user explicitly says the wake word.
    print("ULTRON> Version 11.0 Teach Me build loaded silently.")
    print(f"WAKE WORD> {WAKE_WORD!r} armed")
    print("STATE> STANDBY")

    running = True
    awake = False
    while running:
        try:
            print("\nMIC> Listening...")
            heard = listen()
            if not heard:
                continue

            print(f"YOU> {heard}")

            # STANDBY: ignore ordinary speech. Only the wake word can activate Ultron.
            if not awake:
                wake_command = extract_wake_command(heard)
                if wake_command is None:
                    print("STANDBY> ignored; wake word not detected")
                    continue

                awake = True
                print("STATE> ACTIVE")
                if not wake_command:
                    say("Yes?")
                    continue

                # Supports one-shot wake commands such as "Ultron, open YouTube".
                command = wake_command
            else:
                command = heard.strip()

            # Standby is handled before planner/AI routing so it is instant and local.
            if is_standby_command(command):
                say("Standing by.")
                awake = False
                print("STATE> STANDBY")
                time.sleep(0.15)
                continue

            running = handle_command(router, ai, vision, command, planner, agent, teacher)
            time.sleep(0.15)

        except KeyboardInterrupt:
            print("\nSYSTEM> Keyboard interrupt")
            say("Shutting down core protocols.")
            break
        except Exception as e:
            print(f"SYSTEM ERROR> {type(e).__name__}: {e}")
            say("I hit a local error, but the voice loop is still running.")


if __name__ == "__main__":
    main()
