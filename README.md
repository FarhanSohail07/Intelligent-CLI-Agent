# ARIA — AI Runtime Intelligence Assistant

> Professional desktop automation engine powered by Groq (LLaMA).  
> Python 3.11+ · Windows · macOS · Linux

---

## Features

| Category | Capabilities |
|---|---|
| **AI** | Multi-turn conversation, exponential-backoff retry, robust JSON action parsing |
| **Projects** | Scaffold Node, Python, React, FastAPI, Flask, Next.js, ML, Data Science |
| **Files** | Create, read, rename, delete files & folders |
| **Browser** | Open YouTube, Google, GitHub, Gmail, Notion, Discord … and search them |
| **System** | CPU / RAM / disk / network monitor, process list, kill processes |
| **Shell** | Run arbitrary shell commands (with confirmation prompt) |
| **Screenshot** | Capture screen to PNG |
| **Clipboard** | Copy text to / paste from clipboard |
| **Session** | Full conversation history saved to `sessions/` JSON |
| **Config** | `.env` + `config.json` with live `set_config` action |
| **UI modes** | Voice input (optional) or text input; Rich terminal or plain fallback |
| **Dry-run** | Preview all actions without executing — toggle with `dry-run` |

---

## Quick Start

### 1. Get the files

```
main.py
requirements.txt
.env          ← you create this (see step 3)
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set your Groq API key

Create a `.env` file in the same folder as `main.py`:

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
```

Get a free key at <https://console.groq.com>.

### 4. Run

```bash
python main.py
```

---

## Optional extras

Install these only if you need the feature:

```bash
# Voice input (all three required together)
pip install SpeechRecognition sounddevice numpy

# Screenshot + clipboard
pip install pyautogui pyperclip
```

---

## Configuration (`config.json`)

Auto-generated on first run. Edit it directly or use the `set_config` action at runtime.

| Key | Default | Description |
|---|---|---|
| `model` | `llama-3.1-8b-instant` | Groq model ID |
| `voice_duration` | `6` | Seconds to record voice |
| `samplerate` | `44100` | Audio sample rate |
| `max_retries` | `3` | API retry attempts |
| `retry_delay` | `2` | Seconds between retries (doubles on each retry) |
| `dry_run` | `false` | Preview mode — actions shown but not executed |
| `log_level` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `log_file` | `aria.log` | Log output file |
| `session_dir` | `sessions` | Where session JSON files are saved |
| `projects_root` | `~/aria_projects` | Root folder for all scaffolded projects |
| `history_limit` | `20` | Max messages kept in AI context window |
| `voice_language` | `en-US` | Language code for voice recognition |

---

## Built-in commands (no AI call)

| Command | Action |
|---|---|
| `help` | Show command list |
| `history` | Print conversation history |
| `config` | Display current config |
| `sysinfo` | Show CPU / RAM / disk info |
| `clear` | Clear conversation history |
| `dry-run` | Toggle dry-run mode on/off |
| `voice` | Switch to voice input |
| `text` | Switch to text input |
| `exit` / `quit` / `bye` | Save session and exit |

---

## Example prompts

```
open youtube
open github
search google for python tutorials
open whatsapp

create python machine learning project called predictor
create a react project called my-portfolio
create a fastapi project called my-api

take a screenshot
what is my CPU usage?
list running processes
kill process chrome

create a file at ~/Desktop/notes.txt with content Hello World
read file ~/Desktop/notes.txt
run command ls -la
```

---

## Project scaffolds

| Type | What gets created |
|---|---|
| `python` | Package layout, `pyproject.toml`, pytest, dotenv |
| `ml` | `src/train.py`, `src/predict.py`, `src/eda.py`, scikit-learn ready |
| `data` | `src/analysis.py`, pandas / matplotlib / seaborn layout |
| `node` | Express server, ESM, `package.json` |
| `react` | Vite + React + Tailwind, router, pages folder |
| `fastapi` | FastAPI app, routers, CORS middleware, health endpoint |
| `flask` | Flask app, CORS, gunicorn-ready |
| `nextjs` | Next.js 14, TypeScript, Tailwind, app router |

---

## Platform notes

| OS | URL / app opening method |
|---|---|
| **Windows** | `webbrowser.open()` for URLs · `os.startfile()` for files/folders |
| **macOS** | `webbrowser.open()` for URLs · `open` command for files/folders |
| **Linux** | `webbrowser.open()` for URLs · `xdg-open` for files/folders |

> **Windows users:** the old `subprocess.Popen(["start", ...])` approach fails because  
> `start` is a cmd.exe built-in, not an executable. The current version uses  
> `webbrowser` and `os.startfile` which work correctly on all Windows versions.

---

## File structure

```
main.py              — main application (single file, no extra modules)
requirements.txt     — Python dependencies
.env                 — your API key (never commit this to git)
config.json          — runtime config (auto-created on first run)
aria.log             — log output
sessions/            — saved conversation JSON files (auto-created)
~/aria_projects/     — all scaffolded projects land here
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `GROQ_API_KEY not set` | Add `GROQ_API_KEY=gsk_...` to your `.env` file |
| `[WinError 2] file not found` on open | Already fixed — update to latest `main.py` |
| `Unknown action: 'unknown'` | Already fixed — parser now handles all LLaMA response formats |
| Voice not working | `pip install SpeechRecognition sounddevice numpy` |
| `pyautogui` / `pyperclip` missing | `pip install pyautogui pyperclip` |
| `psutil` missing | `pip install psutil` |

---

## License

MIT — use freely.
