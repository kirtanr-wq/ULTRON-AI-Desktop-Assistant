# 🔴 ULTRON — Autonomous AI Desktop Assistant

> **Your computer. Now intelligent.**

ULTRON is a voice-controlled AI desktop assistant built to go beyond traditional chatbots. It combines **Generative AI, voice interaction, computer vision, persistent memory, workflow learning, autonomous planning, and desktop automation** to create an intelligent companion capable of interacting directly with a Windows computer.

Instead of only answering questions, ULTRON can understand a user's request, determine what needs to be done, interact with applications and websites, and verify the results of its actions.

---

## ✨ Key Features

### 🎙️ Voice-Controlled Assistant
Activate ULTRON simply by saying:

> **"Ultron"**

Once activated, users can communicate naturally through voice without repeating the wake word for every command.

ULTRON supports active and standby states and provides spoken responses using text-to-speech.

---

### 🤖 Autonomous Agent Mode

ULTRON can perform multi-step computer tasks using an autonomous workflow:

**UNDERSTAND → PLAN → ACT → VERIFY**

Rather than executing only predefined commands, the agent can break more complex requests into individual actions, perform them, observe the result, and determine whether the task was completed successfully.

---

### 👁️ Computer Vision & Screen Understanding

ULTRON can analyze the user's current screen and use visual information while performing tasks.

Capabilities include:

- Screen understanding
- Visual target detection
- Screen-based interaction
- Finding elements currently visible on screen
- Verification of performed actions
- Screen error assistance

This allows ULTRON to interact with interfaces that cannot be handled using simple predefined commands alone.

---

### 🧠 Persistent AI Memory

ULTRON includes a persistent memory system that allows useful information to be retained across sessions.

The memory system combines:

- SQLite storage
- Semantic embeddings
- Context retrieval
- Local fallback mechanisms

This gives ULTRON the ability to use previously stored context in future conversations.

---

### 🎓 Teach Me Mode

ULTRON can learn workflows by observing the user.

Example:

1. Say **"Learn this workflow."**
2. Perform the workflow manually.
3. Say **"Stop learning and call this Play Music."**
4. Later say **"Run Play Music."**

ULTRON can then replay the demonstrated sequence automatically.

Learned workflows are stored locally.

---

### 🌐 Web & Application Control

ULTRON can perform common desktop actions such as:

- Open applications
- Open websites
- Search websites
- Perform Google searches
- Search YouTube
- Play YouTube content
- Access Windows settings
- Open folders and projects
- Search for files
- Control media
- Take screenshots

---

### 🔎 AI-Powered Web Research

ULTRON integrates Gemini with grounded web search capabilities, allowing it to research current information and provide summarized responses through natural conversation.

---

### 🖥️ Futuristic Interactive GUI

ULTRON features a custom interface built using **PySide6 / Qt**.

The central ULTRON reactor dynamically changes based on the assistant's current state:

- Standby
- Active
- Listening
- Thinking
- Speaking
- Executing
- Vision
- Agent Mode
- Teach Mode
- Task Complete
- Error

The interface also displays system statistics, active modules, voice input, current tasks, and an execution timeline.

---

### 🔴 Floating ULTRON Companion

When ULTRON opens another application or website, the full dashboard transforms into a small **always-on-top floating companion**.

The floating reactor:

- Remains visible over other applications
- Displays ULTRON's current state
- Animates while ULTRON speaks
- Can be dragged anywhere on the desktop
- Provides quick access back to the main interface
- Allows ULTRON to remain visually present while performing tasks

Clicking the floating companion restores the complete ULTRON interface.

---

## 🛠️ Technologies Used

### Core
- Python
- Gemini API
- Google GenAI

### GUI
- PySide6
- Qt
- Custom QPainter animations

### Voice
- SpeechRecognition
- SoundDevice
- Pyttsx3

### AI & Intelligence
- Gemini LLM
- Gemini Embeddings
- Autonomous Agent Architecture
- LLM-based Task Planning
- Google Search Grounding

### Computer Vision & Automation
- OpenCV
- PyAutoGUI
- Pillow
- Pynput

### Memory & System Integration
- SQLite
- PSUtil
- Pyperclip
- PyWin32

### Media
- yt-dlp

---

## 🧩 System Architecture

```text
                     ┌────────────────────┐
                     │       USER         │
                     └─────────┬──────────┘
                               │
                              Voice
                               │
                     ┌─────────▼──────────┐
                     │  Speech Recognition │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │       ULTRON       │
                     │    Command Router   │
                     └─────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
        Local Actions       AI / LLM          Planner
             │                 │                 │
             │            ┌────┴────┐            ▼
             │            │         │       Agent Mode
             │         Memory    Research          │
             │                                Plan → Act
             │                                    │
             └──────────────┬─────────────────────┘
                            │
                            ▼
                    Desktop Automation
                            │
                    ┌───────┴───────┐
                    │               │
                  Vision        Verification
                    │               │
                    └───────┬───────┘
                            ▼
                       Task Result
```

---

## 📂 Project Structure

```text
ULTRON/
│
├── main.py             # Main voice assistant loop
├── gui.py              # PySide6 ULTRON interface
├── voice.py            # Speech recognition and TTS
├── ai.py               # Gemini AI integration
├── router.py           # Command routing
├── actions.py          # Desktop and application actions
├── planner.py          # Multi-step task planning
├── agent.py            # Autonomous agent execution
├── vision.py           # Screen understanding and visual interaction
├── memory.py           # Persistent AI memory
├── teach_mode.py       # Workflow learning and replay
├── productivity.py     # Productivity features
├── config.py           # Application configuration
├── requirements.txt    # Python dependencies
└── README.md
```

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd YOUR_REPOSITORY_NAME
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Gemini

Create a `.env` file in the project directory and add your API key:

```env
GEMINI_API_KEY=YOUR_API_KEY_HERE
```

> Never commit your `.env` file or API keys to GitHub.

### 5. Launch ULTRON

```bash
python gui.py
```

Or use:

```text
RUN_ULTRON_GUI.bat
```

---

## 🎮 Example Commands

```text
"Ultron"

"Open YouTube"

"Open VS Code"

"Open Bluetooth settings"

"Search Google for artificial intelligence"

"What do you see on my screen?"

"Learn this workflow"

"Run Play Music"

"Take a screenshot"

"Go on standby mode"
```

---

## 🔐 Privacy & Safety

ULTRON is designed with local control in mind.

- Learned workflows are stored locally.
- Sensitive workflow names are blocked from being saved.
- Teach Mode does not persist normal typed text.
- API credentials are stored using environment variables and should never be committed to the repository.
- Autonomous execution is bounded to prevent unlimited action loops.

---

## ⚠️ Current Limitations

ULTRON is currently designed primarily for **Windows**.

Some desktop automation and visual interactions can depend on screen resolution, application layout, hardware support, and external API availability.

Teach Mode currently learns interaction sequences rather than semantically understanding every interface element, so major UI/layout changes may affect workflow replay.

---

## 🔮 Future Scope

Future improvements can include:

- Semantic workflow learning
- Live audio-reactive UI visualization
- More advanced visual reasoning
- Cross-platform support
- Deeper application integrations
- Improved autonomous task execution
- Plugin-based capabilities
- Cloud synchronization across devices

---

## 💡 Vision

ULTRON explores what happens when an AI assistant moves beyond the chat window and becomes an active part of the computer itself.

The goal is to create an assistant that can:

**Listen. Understand. Remember. See. Plan. Act. Verify. Learn.**

---

## 👨‍💻 Developed For

Built as an AI-powered desktop automation and autonomous agent project.

---

⭐ If you like the project, consider starring the repository!