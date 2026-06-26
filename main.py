"""
╔══════════════════════════════════════════════════════════════════╗
║              ARIA - AI Runtime Intelligence Assistant            ║
║              Professional Desktop Automation Engine             ║
╚══════════════════════════════════════════════════════════════════╝

Compatible with Python 3.11+ (recommended: 3.11).

Features:
  • Voice + Text input modes with automatic retry
  • Conversation memory (multi-turn context)
  • Logging to file + console with log levels
  • Plugin-style action registry (easy to extend)
  • Rich project scaffolding (Node, Python, React, FastAPI, Flask)
  • Smart dependency recommendation engine
  • System monitoring (CPU, RAM, disk, network, processes)
  • Browser/app automation with cross-platform support
  • Web search (Google, YouTube, GitHub, DuckDuckGo)
  • File & folder management
  • Screenshot + clipboard actions
  • Config file (.env + config.json) support
  • Graceful shutdown + error recovery
  • Session history saved to JSON
  • Rate limit handling with exponential backoff
  • Dry-run mode (preview actions without executing)

Requirements:
  See requirements.txt — install with:
      pip install -r requirements.txt
"""

# ─────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────

import os
import sys
import json
import time
import uuid
import shutil
import signal
import logging
import platform
import textwrap
import threading
import traceback
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from typing import Any, Dict, List, Optional, Callable, Tuple

# Third-party (graceful import with helpful messages)
def _require(pkg: str, pip_name: str = None, optional: bool = False):
    """Import a package. Prints install hint for required packages; silent for optional."""
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        if not optional:
            name = pip_name or pkg
            print(f"[MISSING]  pip install {name}")
        return None

# Required — prints [MISSING] hint if absent
groq_mod   = _require("groq")
dotenv_mod = _require("dotenv", "python-dotenv")
psutil_mod = _require("psutil")

# Optional — silent if absent; feature degrades gracefully
sr_mod        = _require("speech_recognition", "SpeechRecognition", optional=True)
sd_mod        = _require("sounddevice",        "sounddevice",        optional=True)
np_mod        = _require("numpy",              "numpy",              optional=True)
pyautogui_mod = _require("pyautogui",          "pyautogui",          optional=True)
pyperclip_mod = _require("pyperclip",          "pyperclip",          optional=True)
requests_mod  = _require("requests",           "requests",           optional=True)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.syntax import Syntax
    from rich.text import Text
    from rich import box
    RICH = True
except ImportError:
    RICH = False
    print("[INFO] Install 'rich' for a prettier interface:  pip install rich")

if dotenv_mod:
    dotenv_mod.load_dotenv()

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "model":           "llama-3.1-8b-instant",
    "voice_duration":  6,          # seconds to record
    "samplerate":      44100,
    "max_retries":     3,
    "retry_delay":     2,          # seconds between retries
    "dry_run":         False,      # preview mode
    "log_level":       "INFO",
    "log_file":        "aria.log",
    "session_dir":     "sessions",
    "projects_root":   str(Path.home() / "aria_projects"),
    "history_limit":   20,         # max messages kept in context
    "voice_language":  "en-US",
    "open_cmd": {
        "Windows": "start",
        "Darwin":  "open",
        "Linux":   "xdg-open",
    }
}

def load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        except Exception as e:
            print(f"[WARN] Could not load config.json: {e}")
    return cfg

def save_config(cfg: Dict[str, Any]):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

CONFIG = load_config()

# ─────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────

log_level = getattr(logging, CONFIG.get("log_level", "INFO"), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_file"], encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("ARIA")

# ─────────────────────────────────────────────────────────────────
# RICH CONSOLE
# ─────────────────────────────────────────────────────────────────

console = Console() if RICH else None

def cprint(msg: str, style: str = "", end: str = "\n"):
    if RICH and console:
        console.print(msg, style=style, end=end)
    else:
        print(msg, end=end)

def banner():
    if RICH and console:
        console.print(Panel.fit(
            "[bold cyan]ARIA[/bold cyan] · AI Runtime Intelligence Assistant\n"
            "[dim]Professional Desktop Automation Engine[/dim]",
            border_style="bright_blue",
        ))
    else:
        print("\n" + "=" * 60)
        print("  ARIA · AI Runtime Intelligence Assistant")
        print("  Professional Desktop Automation Engine")
        print("=" * 60 + "\n")

# ─────────────────────────────────────────────────────────────────
# GROQ CLIENT
# ─────────────────────────────────────────────────────────────────

def build_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not set. Add it to your .env file.")
        sys.exit(1)
    if not groq_mod:
        logger.error("groq package missing. Run: pip install groq")
        sys.exit(1)
    return groq_mod.Groq(api_key=api_key)

client = build_groq_client()

# ─────────────────────────────────────────────────────────────────
# SESSION MANAGER
# ─────────────────────────────────────────────────────────────────

class Session:
    """Manages per-run conversation history and persistence."""

    def __init__(self):
        self.id        = str(uuid.uuid4())[:8]
        self.started   = datetime.now().isoformat()
        self.history   : List[Dict]  = []   # [{role, content}]
        self.action_log: List[Dict]  = []
        self.session_dir = Path(CONFIG["session_dir"])
        self.session_dir.mkdir(exist_ok=True)

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        # Keep context window manageable
        limit = CONFIG.get("history_limit", 20)
        if len(self.history) > limit:
            self.history = self.history[-limit:]

    def log_action(self, action: Dict, status: str, detail: str = ""):
        self.action_log.append({
            "ts":     datetime.now().isoformat(),
            "action": action.get("action"),
            "status": status,
            "detail": detail,
        })

    def save(self):
        path = self.session_dir / f"session_{self.id}.json"
        data = {
            "id":         self.id,
            "started":    self.started,
            "ended":      datetime.now().isoformat(),
            "history":    self.history,
            "action_log": self.action_log,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Session saved → {path}")

    def show_history(self):
        if not self.history:
            cprint("[dim]No history yet.[/dim]")
            return
        if RICH and console:
            t = Table(title="Conversation History", box=box.SIMPLE_HEAVY)
            t.add_column("Role",    style="bold")
            t.add_column("Message", no_wrap=False)
            for m in self.history:
                role  = m["role"].upper()
                color = "cyan" if role == "USER" else "green"
                t.add_row(f"[{color}]{role}[/{color}]",
                          textwrap.shorten(m["content"], 120))
            console.print(t)
        else:
            for m in self.history:
                print(f"  [{m['role'].upper()}] {m['content'][:120]}")

session = Session()

# ─────────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are ARIA, a professional AI desktop automation assistant.

CRITICAL: Respond ONLY with a single valid JSON object. No prose. No markdown. No code fences.
Every action object MUST have an "action" key whose value is exactly one of the action names listed below.

REQUIRED OUTPUT FORMAT (copy this structure exactly):
{
  "reply": "Short natural-language reply to the user",
  "actions": [
    { "action": "ACTION_NAME_HERE", ...other fields... }
  ]
}

VALID ACTIONS (use the exact action name string in the "action" field):
  "open_app"       : { "action": "open_app",       "app": "youtube|google|github|notepad|vscode|<exe_path>" }
  "youtube_search" : { "action": "youtube_search",  "query": "<search terms>" }
  "web_search"     : { "action": "web_search",      "engine": "google|duckduckgo|github", "query": "<terms>" }
  "create_file"    : { "action": "create_file",     "path": "<full_path>", "content": "<text>" }
  "create_folder"  : { "action": "create_folder",   "path": "<full_path>" }
  "delete_path"    : { "action": "delete_path",     "path": "<full_path>" }
  "rename_path"    : { "action": "rename_path",     "src": "<old>", "dst": "<new>" }
  "read_file"      : { "action": "read_file",       "path": "<full_path>" }
  "run_command"    : { "action": "run_command",     "cmd": "<shell command>", "cwd": "<optional dir>" }
  "install_deps"   : { "action": "install_deps",    "name": "<project name>" }
  "open_file"      : { "action": "open_file",       "path": "<path>" }
  "create_project" : { "action": "create_project",  "name": "<name>", "type": "node|python|react|fastapi|flask|nextjs|ml|data", "description": "<optional>" }
  "create_website" : { "action": "create_website",  "name": "<name>", "title": "<page title>", "description": "<text>" }
  "system_info"    : { "action": "system_info" }
  "list_processes" : { "action": "list_processes",  "filter": "<optional name>" }
  "kill_process"   : { "action": "kill_process",    "name": "<process name>" }
  "screenshot"     : { "action": "screenshot",      "path": "<optional save path>" }
  "clipboard_copy" : { "action": "clipboard_copy",  "text": "<text to copy>" }
  "clipboard_paste": { "action": "clipboard_paste" }
  "show_history"   : { "action": "show_history" }
  "show_config"    : { "action": "show_config" }
  "set_config"     : { "action": "set_config",      "key": "<cfg key>", "value": "<value>" }

RULES:
  1. The "actions" array may be empty [] if no action is needed.
  2. NEVER wrap actions as {"create_project": {...}} — ALWAYS use {"action": "create_project", ...}.
  3. For multi-step tasks, list all needed actions in order in the array.
  4. Infer project name from the user's description if not explicitly given.
  5. For machine learning or data science projects, use type "ml" or "data".
  6. Always include "reply" with a helpful message.

EXAMPLE for "create python machine learning project called predictor":
{
  "reply": "Creating a Python machine learning project called predictor.",
  "actions": [
    { "action": "create_project", "name": "predictor", "type": "ml", "description": "Machine learning project for prediction tasks" }
  ]
}

EXAMPLE for "install dependencies for predictor" or "download packages for predictor":
{
  "reply": "Installing dependencies for the predictor project.",
  "actions": [
    { "action": "install_deps", "name": "predictor" }
  ]
}

EXAMPLE for "create project called shop and install its dependencies":
{
  "reply": "Creating the shop project and installing its dependencies.",
  "actions": [
    { "action": "create_project", "name": "shop", "type": "python", "description": "Python project" },
    { "action": "install_deps",   "name": "shop" }
  ]
}
"""

# ─────────────────────────────────────────────────────────────────
# VOICE INPUT
# ─────────────────────────────────────────────────────────────────

def listen(retries: int = 2) -> str:
    if not sr_mod or not sd_mod or not np_mod:
        logger.warning("Voice dependencies missing; falling back to text input.")
        return ""

    r   = sr_mod.Recognizer()
    dur = CONFIG.get("voice_duration", 6)
    sr_ = CONFIG.get("samplerate", 44100)
    lang = CONFIG.get("voice_language", "en-US")

    for attempt in range(1, retries + 2):
        try:
            cprint(f"[bold green]🎤 Listening ({dur}s)…[/bold green]")
            recording = sd_mod.rec(int(sr_ * dur), samplerate=sr_, channels=1)
            sd_mod.wait()
            audio = sr_mod.AudioData(
                np_mod.array(recording, dtype=np_mod.float32).tobytes(),
                sr_, 4
            )
            text = r.recognize_google(audio, language=lang)
            cprint(f"[cyan]🎤 You:[/cyan] {text}")
            logger.info(f"Voice input: {text}")
            return text
        except sr_mod.UnknownValueError:
            cprint("[yellow]⚠ Could not understand. Speak clearly and try again.[/yellow]")
        except sr_mod.RequestError as e:
            logger.error(f"Voice recognition service error: {e}")
        except Exception as e:
            logger.error(f"Voice error (attempt {attempt}): {e}")
        if attempt <= retries:
            time.sleep(0.5)

    cprint("[red]❌ Voice failed after retries. Switching to text input.[/red]")
    return get_text()

def get_text() -> str:
    try:
        cprint("[cyan]⌨️  You:[/cyan] ", end="")
        return input()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt

# ─────────────────────────────────────────────────────────────────
# DEPENDENCY RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────

DEPENDENCY_MAP: Dict[str, Dict[str, List[str]]] = {
    "node": {
        "base":       ["express", "cors", "dotenv", "morgan"],
        "jwt":        ["jsonwebtoken", "bcryptjs"],
        "database":   ["mongoose", "pg", "sequelize"],
        "test":       ["jest", "supertest"],
        "websocket":  ["socket.io"],
        "graphql":    ["apollo-server", "graphql"],
        "queue":      ["bull", "ioredis"],
        "email":      ["nodemailer"],
    },
    "python": {
        "base":       ["python-dotenv", "loguru"],
        "ml":         ["scikit-learn", "torch", "transformers"],
        "data":       ["numpy", "pandas", "matplotlib", "seaborn"],
        "api":        ["fastapi", "uvicorn", "pydantic"],
        "flask":      ["flask", "flask-cors", "gunicorn"],
        "db":         ["sqlalchemy", "alembic", "psycopg2-binary"],
        "test":       ["pytest", "pytest-cov", "httpx"],
        "websocket":  ["websockets", "python-socketio"],
        "nlp":        ["spacy", "nltk", "sentence-transformers"],
    },
    "ml": {
        "base":       ["numpy", "pandas", "scikit-learn", "joblib"],
        "deep":       ["torch", "torchvision", "torchaudio"],
        "transformers": ["transformers", "tokenizers", "datasets"],
        "viz":        ["matplotlib", "seaborn", "plotly"],
        "tracking":   ["mlflow", "wandb"],
        "data":       ["scipy", "statsmodels"],
        "nlp":        ["spacy", "nltk", "sentence-transformers"],
        "test":       ["pytest", "pytest-cov"],
    },
    "data": {
        "base":       ["numpy", "pandas", "matplotlib", "seaborn"],
        "analysis":   ["scipy", "statsmodels"],
        "notebook":   ["jupyter", "notebook", "ipykernel"],
        "viz":        ["plotly", "bokeh", "altair"],
        "io":         ["openpyxl", "pyarrow", "sqlalchemy"],
        "test":       ["pytest"],
    },
    "react": {
        "base":       ["axios", "react-router-dom", "react-query"],
        "state":      ["zustand", "redux-toolkit", "@reduxjs/toolkit"],
        "ui":         ["@shadcn/ui", "tailwindcss", "framer-motion"],
        "forms":      ["react-hook-form", "zod", "yup"],
        "test":       ["vitest", "@testing-library/react"],
        "auth":       ["@auth0/auth0-react", "firebase"],
    },
}

def recommend_dependencies(ptype: str, description: str) -> Dict[str, List[str]]:
    d    = description.lower()
    ptype = ptype.lower()
    # Normalise aliases
    if ptype in ("machine_learning", "machine learning"):
        ptype = "ml"
    if ptype in ("data_science", "data science"):
        ptype = "data"

    base  = DEPENDENCY_MAP.get(ptype, {})
    result: Dict[str, List[str]] = {}

    if "base" in base:
        result["core"] = base["base"]

    keywords: Dict[str, List[str]] = {
        # Node
        "jwt":       ["jwt", "auth", "login", "token"],
        "database":  ["database", "db", "mongo", "postgres", "sql"],
        "test":      ["test", "testing", "spec"],
        "websocket": ["websocket", "socket", "realtime", "chat"],
        "graphql":   ["graphql"],
        "queue":     ["queue", "worker", "job"],
        "email":     ["email", "smtp", "mail"],
        # Python / ML / Data
        "ml":         ["ml", "machine learning", "model", "train", "predict"],
        "deep":       ["deep learning", "neural", "torch", "pytorch", "cnn", "lstm"],
        "transformers": ["transformer", "bert", "gpt", "llm", "language model"],
        "data":       ["data", "csv", "analysis", "plot", "chart", "dataframe"],
        "api":        ["api", "rest", "endpoint", "fastapi"],
        "flask":      ["flask", "web", "app"],
        "db":         ["database", "db", "postgres", "sql", "orm"],
        "nlp":        ["nlp", "text", "language", "sentiment", "spacy", "nltk"],
        "tracking":   ["track", "experiment", "mlflow", "wandb"],
        "viz":        ["visual", "plot", "chart", "dashboard", "plotly"],
        "notebook":   ["notebook", "jupyter", "explore"],
        "io":         ["excel", "parquet", "arrow", "sql"],
        # React
        "state":      ["state", "redux", "store"],
        "ui":         ["ui", "component", "tailwind", "design"],
        "forms":      ["form", "validation", "input"],
        "auth":       ["auth", "login", "firebase"],
    }

    for category, triggers in keywords.items():
        if category in base and any(t in d for t in triggers):
            result[category] = base[category]

    return result

# ─────────────────────────────────────────────────────────────────
# PROJECT SCAFFOLDING
# ─────────────────────────────────────────────────────────────────

SCAFFOLDS: Dict[str, Callable] = {}

def scaffold(name: str):
    def decorator(fn: Callable):
        SCAFFOLDS[name] = fn
        return fn  # return fn (not a wrapper) so stacking works
    return decorator

def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")

@scaffold("node")
def scaffold_node(base: Path, project_name: str, desc: str):
    _write(base / "index.js", f"""\
        import express from 'express';
        import cors from 'cors';
        import dotenv from 'dotenv';
        import morgan from 'morgan';

        dotenv.config();
        const app = express();
        const PORT = process.env.PORT || 3000;

        app.use(cors());
        app.use(morgan('dev'));
        app.use(express.json());

        app.get('/health', (_req, res) => res.json({{ status: 'ok' }}));

        app.listen(PORT, () => console.log(`[{project_name}] Running on http://localhost:${{PORT}}`));
    """)
    _write(base / "package.json", json.dumps({
        "name": project_name.lower().replace(" ", "-"),
        "version": "1.0.0",
        "description": desc,
        "type": "module",
        "main": "index.js",
        "scripts": {
            "start": "node index.js",
            "dev":   "nodemon index.js",
            "test":  "jest"
        },
        "engines": {"node": ">=18"}
    }, indent=2))
    _write(base / ".env", "PORT=3000\nNODE_ENV=development\n")
    _write(base / ".gitignore", "node_modules/\n.env\ndist/\n")
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n")

@scaffold("python")
def scaffold_python(base: Path, project_name: str, desc: str):
    snake = project_name.lower().replace(" ", "_").replace("-", "_")
    pkg   = base / snake
    pkg.mkdir(parents=True, exist_ok=True)
    _write(pkg / "__init__.py", f'"""{ desc }"""\n__version__ = "0.1.0"\n')
    _write(pkg / "main.py", f'''\
        """Entry point for {project_name}."""
        import logging
        from dotenv import load_dotenv

        load_dotenv()
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        logger = logging.getLogger(__name__)


        def main():
            logger.info("Starting {project_name}")
            print("Hello from {project_name}!")


        if __name__ == "__main__":
            main()
    ''')
    _write(base / "requirements.txt", "python-dotenv\nloguru\n")
    _write(base / "requirements-dev.txt", "pytest\npytest-cov\nruff\nmypy\n")
    _write(base / ".env", f"APP_ENV=development\nAPP_NAME={project_name}\n")
    _write(base / ".gitignore", "__pycache__/\n*.pyc\n.env\nvenv/\n.venv/\n.pytest_cache/\n")
    _write(base / "pyproject.toml", f'''\
        [build-system]
        requires = ["setuptools>=67"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "{snake}"
        version = "0.1.0"
        description = "{desc}"
        requires-python = ">=3.11"

        [tool.ruff]
        line-length = 100

        [tool.pytest.ini_options]
        testpaths = ["tests"]
    ''')
    (base / "tests").mkdir(exist_ok=True)
    _write(base / "tests" / "__init__.py", "")
    _write(base / "tests" / f"test_{snake}.py", f'''\
        """Tests for {project_name}."""
        from {snake}.main import main


        def test_main(capsys):
            main()
            captured = capsys.readouterr()
            assert "Hello" in captured.out
    ''')
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Setup\n\n```bash\npython -m venv .venv\nsource .venv/bin/activate  # Windows: .venv\\\\Scripts\\\\activate\npip install -r requirements.txt\npython -m {snake}.main\n```\n")

@scaffold("react")
def scaffold_react(base: Path, project_name: str, desc: str):
    (base / "src" / "components").mkdir(parents=True, exist_ok=True)
    (base / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (base / "public").mkdir(exist_ok=True)
    _write(base / "src" / "App.jsx", f'''\
        import {{ BrowserRouter as Router, Routes, Route }} from 'react-router-dom';
        import Home from './pages/Home';

        export default function App() {{
          return (
            <Router>
              <Routes>
                <Route path="/" element={{<Home />}} />
              </Routes>
            </Router>
          );
        }}
    ''')
    _write(base / "src" / "pages" / "Home.jsx", f'''\
        export default function Home() {{
          return (
            <main className="flex min-h-screen items-center justify-center">
              <h1 className="text-4xl font-bold">{project_name}</h1>
            </main>
          );
        }}
    ''')
    _write(base / "src" / "main.jsx", '''\
        import React from 'react';
        import ReactDOM from 'react-dom/client';
        import App from './App';
        import './index.css';

        ReactDOM.createRoot(document.getElementById('root')).render(
          <React.StrictMode><App /></React.StrictMode>
        );
    ''')
    _write(base / "src" / "index.css", "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n")
    _write(base / "package.json", json.dumps({
        "name": project_name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0", "react-router-dom": "^6.22.0"},
        "devDependencies": {
            "vite": "^5.1.0",
            "@vitejs/plugin-react": "^4.2.1",
            "tailwindcss": "^3.4.1",
            "autoprefixer": "^10.4.18",
        }
    }, indent=2))
    _write(base / "vite.config.js", '''\
        import { defineConfig } from 'vite';
        import react from '@vitejs/plugin-react';
        export default defineConfig({ plugins: [react()] });
    ''')
    _write(base / ".gitignore", "node_modules/\ndist/\n.env\n")
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n")

@scaffold("fastapi")
def scaffold_fastapi(base: Path, project_name: str, desc: str):
    snake = project_name.lower().replace(" ", "_").replace("-", "_")
    app_  = base / "app"
    (app_ / "routers").mkdir(parents=True, exist_ok=True)
    (app_ / "models").mkdir(exist_ok=True)
    (app_ / "schemas").mkdir(exist_ok=True)
    _write(app_ / "__init__.py", "")
    _write(app_ / "main.py", f'''\
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from app.routers import health

        app = FastAPI(title="{project_name}", description="{desc}", version="0.1.0")

        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
        app.include_router(health.router)

        if __name__ == "__main__":
            import uvicorn
            uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    ''')
    _write(app_ / "routers" / "__init__.py", "")
    _write(app_ / "routers" / "health.py", '''\
        from fastapi import APIRouter

        router = APIRouter(prefix="/api", tags=["health"])

        @router.get("/health")
        async def health():
            return {"status": "ok"}
    ''')
    _write(base / "requirements.txt", "fastapi\nuvicorn[standard]\npydantic\npython-dotenv\n")
    _write(base / ".env", "APP_ENV=development\nDATABASE_URL=sqlite:///./db.sqlite3\n")
    _write(base / ".gitignore", "__pycache__/\n*.pyc\n.env\nvenv/\n")
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Run\n\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload\n```\n")

# Add flask scaffold (alias to fastapi-style but simpler)
@scaffold("flask")
def scaffold_flask(base: Path, project_name: str, desc: str):
    _write(base / "app.py", f'''\
        from flask import Flask, jsonify
        from flask_cors import CORS
        from dotenv import load_dotenv
        import os

        load_dotenv()
        app = Flask(__name__)
        CORS(app)


        @app.route("/health")
        def health():
            return jsonify(status="ok")


        if __name__ == "__main__":
            port = int(os.getenv("PORT", 5000))
            app.run(debug=True, port=port)
    ''')
    _write(base / "requirements.txt", "flask\nflask-cors\npython-dotenv\ngunicorn\n")
    _write(base / ".env", "PORT=5000\nFLASK_ENV=development\n")
    _write(base / ".gitignore", "__pycache__/\n*.pyc\n.env\nvenv/\n")
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Run\n\n```bash\npip install -r requirements.txt\npython app.py\n```\n")

@scaffold("ml")
@scaffold("machine_learning")
def scaffold_ml(base: Path, project_name: str, desc: str):
    """Machine learning project scaffold with scikit-learn / PyTorch structure."""
    snake = project_name.lower().replace(" ", "_").replace("-", "_")
    (base / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (base / "data" / "processed").mkdir(parents=True, exist_ok=True)
    (base / "models").mkdir(exist_ok=True)
    (base / "notebooks").mkdir(exist_ok=True)
    (base / "src").mkdir(exist_ok=True)

    _write(base / "src" / "__init__.py", "")
    _write(base / "src" / "train.py", f'''\
        """Training pipeline for {project_name}."""
        import logging
        import os

        import numpy as np
        import pandas as pd
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import classification_report, mean_squared_error
        import joblib

        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        logger = logging.getLogger(__name__)


        def load_data(path: str) -> pd.DataFrame:
            """Load dataset from CSV."""
            logger.info(f"Loading data from {{path}}")
            return pd.read_csv(path)


        def preprocess(df: pd.DataFrame):
            """Basic preprocessing: split features/target, scale."""
            X = df.drop(columns=["target"], errors="ignore")
            y = df.get("target", pd.Series(np.zeros(len(df))))
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            scaler = StandardScaler()
            X_train = scaler.fit_transform(X_train)
            X_test  = scaler.transform(X_test)
            return X_train, X_test, y_train, y_test, scaler


        def train(X_train, y_train):
            from sklearn.ensemble import RandomForestClassifier
            model = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
            model.fit(X_train, y_train)
            logger.info("Model trained.")
            return model


        def evaluate(model, X_test, y_test):
            preds = model.predict(X_test)
            logger.info("\\n" + classification_report(y_test, preds, zero_division=0))


        def save_model(model, scaler, path: str = "models/model.joblib"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            joblib.dump({{"model": model, "scaler": scaler}}, path)
            logger.info(f"Saved → {{path}}")


        if __name__ == "__main__":
            import sys
            data_path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/dataset.csv"
            df = load_data(data_path)
            X_train, X_test, y_train, y_test, scaler = preprocess(df)
            model = train(X_train, y_train)
            evaluate(model, X_test, y_test)
            save_model(model, scaler)
    ''')
    _write(base / "src" / "predict.py", f'''\
        """Inference for {project_name}."""
        import joblib
        import numpy as np


        def load(path: str = "models/model.joblib"):
            bundle = joblib.load(path)
            return bundle["model"], bundle["scaler"]


        def predict(features, model_path: str = "models/model.joblib"):
            model, scaler = load(model_path)
            arr = np.array(features).reshape(1, -1)
            arr = scaler.transform(arr)
            return model.predict(arr)[0]


        if __name__ == "__main__":
            print("Replace this with real feature values.")
    ''')
    _write(base / "src" / "eda.py", '''\
        """Exploratory Data Analysis helpers."""
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns
        import os


        def plot_distribution(df: pd.DataFrame, out_dir: str = "notebooks"):
            os.makedirs(out_dir, exist_ok=True)
            for col in df.select_dtypes(include="number").columns:
                fig, ax = plt.subplots()
                sns.histplot(df[col].dropna(), ax=ax, kde=True)
                ax.set_title(f"Distribution of {col}")
                fig.savefig(f"{out_dir}/{col}_dist.png", bbox_inches="tight")
                plt.close(fig)
    ''')
    _write(base / "requirements.txt",
           "numpy\npandas\nscikit-learn\njoblib\nmatplotlib\nseaborn\npython-dotenv\n")
    _write(base / "requirements-dev.txt",
           "jupyter\nnotebook\nipykernel\npytest\npytest-cov\n")
    _write(base / ".env", f"APP_ENV=development\nAPP_NAME={project_name}\n")
    _write(base / ".gitignore",
           "__pycache__/\n*.pyc\n.env\nvenv/\n.venv/\nmodels/*.joblib\ndata/raw/*\ndata/processed/*\n")
    _write(base / "README.md",
           f"# {project_name}\n\n{desc}\n\n"
           "## Setup\n\n```bash\npython -m venv .venv\n"
           "source .venv/bin/activate  # Windows: .venv\\\\Scripts\\\\activate\n"
           "pip install -r requirements.txt\n```\n\n"
           "## Train\n\n```bash\npython src/train.py data/raw/dataset.csv\n```\n\n"
           "## Predict\n\n```bash\npython src/predict.py\n```\n")


@scaffold("data")
@scaffold("data_science")
def scaffold_data(base: Path, project_name: str, desc: str):
    """Data science / analysis project scaffold."""
    (base / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (base / "data" / "processed").mkdir(parents=True, exist_ok=True)
    (base / "reports" / "figures").mkdir(parents=True, exist_ok=True)
    (base / "notebooks").mkdir(exist_ok=True)
    (base / "src").mkdir(exist_ok=True)

    _write(base / "src" / "__init__.py", "")
    _write(base / "src" / "analysis.py", f'''\
        """Core analysis for {project_name}."""
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns
        import os

        REPORTS = "reports/figures"


        def load(path: str) -> pd.DataFrame:
            return pd.read_csv(path)


        def summary(df: pd.DataFrame) -> pd.DataFrame:
            print(df.describe())
            print("\\nMissing values:\\n", df.isnull().sum())
            return df


        def correlation_heatmap(df: pd.DataFrame):
            os.makedirs(REPORTS, exist_ok=True)
            fig, ax = plt.subplots(figsize=(10, 8))
            sns.heatmap(df.select_dtypes("number").corr(), annot=True, ax=ax, fmt=".2f")
            fig.tight_layout()
            path = f"{{REPORTS}}/correlation.png"
            fig.savefig(path)
            plt.close(fig)
            print(f"Saved → {{path}}")


        if __name__ == "__main__":
            import sys
            df = load(sys.argv[1] if len(sys.argv) > 1 else "data/raw/data.csv")
            summary(df)
            correlation_heatmap(df)
    ''')
    _write(base / "requirements.txt",
           "numpy\npandas\nmatplotlib\nseaborn\nscipy\npython-dotenv\n")
    _write(base / "requirements-dev.txt",
           "jupyter\nnotebook\nipykernel\nopenpyxl\n")
    _write(base / ".gitignore",
           "__pycache__/\n*.pyc\n.env\nvenv/\n.venv/\ndata/raw/*\ndata/processed/*\n")
    _write(base / "README.md",
           f"# {project_name}\n\n{desc}\n\n"
           "## Setup\n\n```bash\npython -m venv .venv\n"
           "source .venv/bin/activate\npip install -r requirements.txt\n```\n\n"
           "## Run Analysis\n\n```bash\npython src/analysis.py data/raw/data.csv\n```\n")


@scaffold("nextjs")
def scaffold_nextjs(base: Path, project_name: str, desc: str):
    (base / "app").mkdir(parents=True, exist_ok=True)
    (base / "components").mkdir(exist_ok=True)
    _write(base / "app" / "page.tsx", f'''\
        export default function Home() {{
          return (
            <main className="flex min-h-screen flex-col items-center justify-center p-24">
              <h1 className="text-5xl font-bold">{project_name}</h1>
              <p className="mt-4 text-xl text-gray-500">{desc}</p>
            </main>
          );
        }}
    ''')
    _write(base / "app" / "layout.tsx", f'''\
        import type {{ Metadata }} from 'next';
        import './globals.css';

        export const metadata: Metadata = {{
          title: '{project_name}',
          description: '{desc}',
        }};

        export default function RootLayout({{ children }}: {{ children: React.ReactNode }}) {{
          return (
            <html lang="en">
              <body>{{children}}</body>
            </html>
          );
        }}
    ''')
    _write(base / "app" / "globals.css", "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n")
    _write(base / "package.json", json.dumps({
        "name": project_name.lower().replace(" ", "-"),
        "version": "0.1.0",
        "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        "dependencies": {"next": "14.1.0", "react": "^18", "react-dom": "^18"},
        "devDependencies": {"typescript": "^5", "@types/react": "^18", "tailwindcss": "^3.4.1"}
    }, indent=2))
    _write(base / "README.md", f"# {project_name}\n\n{desc}\n\n## Setup\n\n```bash\nnpm install\nnpm run dev\n```\n")

# ─────────────────────────────────────────────────────────────────
# UTILITY HELPERS
# ─────────────────────────────────────────────────────────────────

def get_open_cmd() -> str:
    return CONFIG["open_cmd"].get(platform.system(), "xdg-open")

def open_url(url: str):
    """Open a URL in the default browser — works on Windows, macOS, Linux."""
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.error(f"webbrowser.open failed for {url}: {e}")

def open_path(path: str):
    """Open a file or folder in the OS default application."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.Popen(["open", path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.error(f"open_path failed for '{path}': {e}")

WEB_APPS = {
    "youtube":    "https://youtube.com",
    "google":     "https://google.com",
    "github":     "https://github.com",
    "gmail":      "https://mail.google.com",
    "drive":      "https://drive.google.com",
    "notion":     "https://notion.so",
    "figma":      "https://figma.com",
    "stackoverflow": "https://stackoverflow.com",
    "chatgpt":    "https://chat.openai.com",
    "reddit":     "https://reddit.com",
    "twitter":    "https://twitter.com",
    "linkedin":   "https://linkedin.com",
    "discord":    "https://discord.com/app",
    "whatsapp":   "https://web.whatsapp.com",
}

DESKTOP_APPS_WINDOWS = {
    "notepad":  "notepad.exe",
    "vscode":   "code",
    "explorer": "explorer.exe",
    "chrome":   "chrome",
    "firefox":  "firefox",
    "calc":     "calc.exe",
    "terminal": "cmd.exe",
    "powershell": "powershell.exe",
}

# ─────────────────────────────────────────────────────────────────
# ACTION REGISTRY
# ─────────────────────────────────────────────────────────────────

ACTIONS: Dict[str, Callable] = {}

def register(name: str):
    def decorator(fn: Callable):
        ACTIONS[name] = fn
        return fn
    return decorator

# ---------- App / Browser ----------

@register("open_app")
def action_open_app(action: Dict, **_):
    app = action.get("app", "").lower()
    if app in WEB_APPS:
        open_url(WEB_APPS[app])
        cprint(f"[green]🌐 Opened {app}[/green]")
    elif app in DESKTOP_APPS_WINDOWS and platform.system() == "Windows":
        subprocess.Popen(DESKTOP_APPS_WINDOWS[app], shell=True)
        cprint(f"[green]🖥️  Launched {app}[/green]")
    else:
        open_path(app)
        cprint(f"[green]🚀 Opened: {app}[/green]")
    logger.info(f"Opened app: {app}")

@register("youtube_search")
@register("play_youtube")
def action_youtube_search(action: Dict, **_):
    query = action.get("query", "")
    url   = "https://www.youtube.com/results?search_query=" + quote(query)
    open_url(url)
    cprint(f"[green]▶️  YouTube search: {query}[/green]")
    logger.info(f"YouTube search: {query}")

@register("web_search")
def action_web_search(action: Dict, **_):
    engine = action.get("engine", "google").lower()
    query  = action.get("query", "")
    urls   = {
        "google":     f"https://www.google.com/search?q={quote(query)}",
        "duckduckgo": f"https://duckduckgo.com/?q={quote(query)}",
        "github":     f"https://github.com/search?q={quote(query)}",
        "npm":        f"https://www.npmjs.com/search?q={quote(query)}",
        "pypi":       f"https://pypi.org/search/?q={quote(query)}",
    }
    url = urls.get(engine, urls["google"])
    open_url(url)
    cprint(f"[green]🔍 {engine.title()} search: {query}[/green]")
    logger.info(f"Web search [{engine}]: {query}")

# ---------- File System ----------

@register("create_file")
def action_create_file(action: Dict, **_):
    path    = Path(action.get("path", ""))
    content = action.get("content", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    cprint(f"[green]📄 Created file: {path}[/green]")
    logger.info(f"Created file: {path}")

@register("create_folder")
def action_create_folder(action: Dict, **_):
    path = Path(action.get("path", ""))
    path.mkdir(parents=True, exist_ok=True)
    cprint(f"[green]📁 Created folder: {path}[/green]")
    logger.info(f"Created folder: {path}")

@register("delete_path")
def action_delete_path(action: Dict, **_):
    path = Path(action.get("path", ""))
    if not path.exists():
        cprint(f"[yellow]⚠ Path not found: {path}[/yellow]")
        return
    confirm = input(f"⚠️  Delete '{path}'? [y/N]: ").strip().lower()
    if confirm != "y":
        cprint("[dim]Skipped.[/dim]")
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    cprint(f"[red]🗑️  Deleted: {path}[/red]")
    logger.info(f"Deleted: {path}")

@register("rename_path")
def action_rename_path(action: Dict, **_):
    src = Path(action.get("src", ""))
    dst = Path(action.get("dst", ""))
    src.rename(dst)
    cprint(f"[green]✏️  Renamed: {src} → {dst}[/green]")
    logger.info(f"Renamed: {src} → {dst}")

@register("read_file")
def action_read_file(action: Dict, **_):
    path = Path(action.get("path", ""))
    if not path.exists():
        cprint(f"[red]❌ File not found: {path}[/red]")
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    if RICH and console:
        ext = path.suffix.lstrip(".")
        console.print(Syntax(content, ext or "text", theme="monokai", line_numbers=True))
    else:
        print(content)
    logger.info(f"Read file: {path}")

@register("open_file")
def action_open_file(action: Dict, **_):
    path = action.get("path", "")
    open_path(path)
    cprint(f"[green]📂 Opened: {path}[/green]")

# ---------- Project Creation ----------

@register("create_project")
def action_create_project(action: Dict, user_input: str = "", **_):
    name  = action.get("name", "my_project")
    ptype = action.get("type", "python").lower()
    desc  = action.get("description", f"A {ptype} project.")
    root  = Path(CONFIG["projects_root"])
    root.mkdir(parents=True, exist_ok=True)   # ensure root exists on first run
    base  = root / name

    if base.exists():
        cprint(f"[yellow]⚠ Project '{name}' already exists at {base}[/yellow]")
        overwrite = input("Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            return

    base.mkdir(parents=True, exist_ok=True)

    scaffold_fn = SCAFFOLDS.get(ptype)
    if scaffold_fn:
        scaffold_fn(base, name, desc)
        cprint(f"[bold green]✅ {ptype.title()} project '{name}' created at {base}[/bold green]")
    else:
        cprint(f"[yellow]⚠ Unknown project type '{ptype}'. Created empty folder.[/yellow]")

    # Show dependency recommendations
    deps = recommend_dependencies(ptype, user_input or desc)
    if deps and RICH and console:
        t = Table(title=f"Recommended Dependencies for {ptype}", box=box.MINIMAL_DOUBLE_HEAD)
        t.add_column("Category", style="bold cyan")
        t.add_column("Packages")
        for cat, pkgs in deps.items():
            t.add_row(cat, ", ".join(pkgs))
        console.print(t)
    elif deps:
        for cat, pkgs in deps.items():
            print(f"  [{cat}] {', '.join(pkgs)}")

    logger.info(f"Created {ptype} project: {name} at {base}")
    open_path(str(base))

@register("create_website")
def action_create_website(action: Dict, **_):
    name  = action.get("name", "my_website")
    title = action.get("title", name.replace("_", " ").title())
    desc  = action.get("description", "")
    root  = Path(CONFIG["projects_root"])
    base  = root / name
    base.mkdir(parents=True, exist_ok=True)

    html = textwrap.dedent(f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: grid; place-items: center; }}
                .hero {{ text-align: center; padding: 2rem; }}
                h1 {{ font-size: clamp(2.5rem, 8vw, 5rem); font-weight: 800; background: linear-gradient(135deg, #6366f1, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
                p  {{ margin-top: 1rem; font-size: 1.25rem; color: #94a3b8; max-width: 600px; margin-inline: auto; }}
                .cta {{ margin-top: 2rem; padding: .75rem 2rem; background: #6366f1; border-radius: 9999px; color: #fff; font-weight: 600; text-decoration: none; }}
                .cta:hover {{ background: #4f46e5; }}
            </style>
        </head>
        <body>
            <div class="hero">
                <h1>{title}</h1>
                <p>{desc}</p>
                <a href="#" class="cta">Get Started</a>
            </div>
        </body>
        </html>
    """)
    index = base / "index.html"
    index.write_text(html, encoding="utf-8")
    cprint(f"[green]🌐 Website created at {index}[/green]")
    open_path(str(index))
    logger.info(f"Created website: {base}")

# ---------- System ----------

@register("system_info")
def action_system_info(**_):
    if not psutil_mod:
        cprint("[red]psutil not installed.[/red]")
        return
    cpu    = psutil_mod.cpu_percent(interval=1)
    mem    = psutil_mod.virtual_memory()
    disk   = psutil_mod.disk_usage("/")
    net    = psutil_mod.net_io_counters()
    uptime = datetime.now() - datetime.fromtimestamp(psutil_mod.boot_time())

    if RICH and console:
        t = Table(title="System Information", box=box.ROUNDED)
        t.add_column("Metric",  style="bold cyan")
        t.add_column("Value",   style="white")
        t.add_column("Detail",  style="dim")
        t.add_row("CPU",       f"{cpu:.1f}%",           f"{psutil_mod.cpu_count(logical=False)} cores")
        t.add_row("RAM",       f"{mem.percent:.1f}%",   f"{mem.used/1e9:.1f} / {mem.total/1e9:.1f} GB")
        t.add_row("Disk (/)",  f"{disk.percent:.1f}%",  f"{disk.used/1e9:.1f} / {disk.total/1e9:.1f} GB")
        t.add_row("Net ↑",     f"{net.bytes_sent/1e6:.1f} MB",  "sent")
        t.add_row("Net ↓",     f"{net.bytes_recv/1e6:.1f} MB",  "received")
        t.add_row("Uptime",    str(uptime).split(".")[0], "")
        console.print(t)
    else:
        print(f"CPU: {cpu:.1f}% | RAM: {mem.percent:.1f}% | Disk: {disk.percent:.1f}%")
    logger.info("System info displayed.")

@register("list_processes")
def action_list_processes(action: Dict, **_):
    if not psutil_mod:
        cprint("[red]psutil not installed.[/red]")
        return
    filter_name = action.get("filter", "").lower()
    procs = [
        p.info for p in psutil_mod.process_iter(["pid", "name", "cpu_percent", "memory_percent"])
        if not filter_name or filter_name in (p.info.get("name") or "").lower()
    ]
    procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
    top = procs[:20]
    if RICH and console:
        t = Table(title="Top Processes", box=box.MINIMAL_HEAVY_HEAD)
        t.add_column("PID",    style="dim", justify="right")
        t.add_column("Name",   style="cyan")
        t.add_column("CPU %",  justify="right")
        t.add_column("MEM %",  justify="right")
        for p in top:
            t.add_row(str(p["pid"]), p["name"] or "?",
                      f'{p["cpu_percent"] or 0:.1f}', f'{p["memory_percent"] or 0:.1f}')
        console.print(t)
    else:
        for p in top:
            print(p["pid"], p["name"], p["cpu_percent"], p["memory_percent"])

@register("kill_process")
def action_kill_process(action: Dict, **_):
    if not psutil_mod:
        return
    name = action.get("name", "")
    killed = 0
    for proc in psutil_mod.process_iter(["pid", "name"]):
        if name.lower() in (proc.info.get("name") or "").lower():
            confirm = input(f"Kill '{proc.info['name']}' (PID {proc.info['pid']})? [y/N]: ").strip().lower()
            if confirm == "y":
                try:
                    proc.kill()
                    killed += 1
                except psutil_mod.NoSuchProcess:
                    pass
    cprint(f"[{'green' if killed else 'yellow'}]{'🔴' if killed else '⚠'} Killed {killed} process(es).[/{'green' if killed else 'yellow'}]")
    logger.info(f"Killed {killed} processes matching '{name}'.")

# ---------- Clipboard / Screenshot ----------

@register("screenshot")
def action_screenshot(action: Dict, **_):
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = action.get("path") or str(Path.home() / f"screenshot_{ts}.png")

    # Method 1: Pillow ImageGrab (works on Windows/macOS without extra deps)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(path)
        cprint(f"[green]📸 Screenshot saved: {path}[/green]")
        logger.info(f"Screenshot: {path}")
        return
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Pillow ImageGrab failed: {e}")

    # Method 2: pyautogui fallback
    if pyautogui_mod:
        try:
            img = pyautogui_mod.screenshot()
            img.save(path)
            cprint(f"[green]📸 Screenshot saved: {path}[/green]")
            logger.info(f"Screenshot: {path}")
            return
        except Exception as e:
            logger.warning(f"pyautogui screenshot failed: {e}")

    # Method 3: Windows-only mss fallback
    try:
        import mss
        with mss.mss() as sct:
            sct.shot(output=path)
        cprint(f"[green]📸 Screenshot saved: {path}[/green]")
        logger.info(f"Screenshot: {path}")
        return
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"mss screenshot failed: {e}")

    cprint("[red]❌ Screenshot failed. Install Pillow:  pip install Pillow[/red]")
    cprint("[dim]   Or try: pip install mss[/dim]")

@register("clipboard_copy")
def action_clipboard_copy(action: Dict, **_):
    if not pyperclip_mod:
        cprint("[red]pyperclip not installed.[/red]")
        return
    text = action.get("text", "")
    pyperclip_mod.copy(text)
    cprint(f"[green]📋 Copied to clipboard ({len(text)} chars)[/green]")

@register("clipboard_paste")
def action_clipboard_paste(**_):
    if not pyperclip_mod:
        cprint("[red]pyperclip not installed.[/red]")
        return
    text = pyperclip_mod.paste()
    cprint(f"[cyan]📋 Clipboard contents:[/cyan]\n{text}")

# ---------- Shell ----------

@register("run_command")
def action_run_command(action: Dict, **_):
    cmd = action.get("cmd", "")
    cwd = action.get("cwd") or None
    cprint(f"[yellow]⚡ Running: {cmd}[/yellow]")
    confirm = input("Execute this command? [y/N]: ").strip().lower()
    if confirm != "y":
        cprint("[dim]Skipped.[/dim]")
        return
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        cprint(f"[red]{result.stderr}[/red]")
    logger.info(f"Command: {cmd} | exit={result.returncode}")

# ---------- Install Dependencies ----------

@register("install_deps")
def action_install_deps(action: Dict, **_):
    """Install dependencies for a named project by finding its requirements file."""
    name = action.get("name", "").strip()
    root = Path(CONFIG["projects_root"])

    # Always ensure the projects root exists
    root.mkdir(parents=True, exist_ok=True)

    # Resolve project folder
    if name:
        project_dir = root / name
    else:
        cprint("[red]❌ No project name given.[/red]")
        return

    if not project_dir.exists():
        # Try fuzzy match inside projects_root
        existing = [d for d in root.iterdir() if d.is_dir()]
        matches  = [d for d in existing if name.lower() in d.name.lower()]
        if matches:
            project_dir = matches[0]
            cprint(f"[dim]Found project at: {project_dir}[/dim]")
        else:
            available = ", ".join(d.name for d in existing) or "none"
            cprint(f"[red]❌ Project '{name}' not found in {root}[/red]")
            cprint(f"[dim]   Available projects: {available}[/dim]")
            cprint(f"[dim]   Tip: create it first — try 'create python project called {name}'[/dim]")
            return

    # Detect installer type
    req_txt     = project_dir / "requirements.txt"
    pkg_json    = project_dir / "package.json"
    pyproject   = project_dir / "pyproject.toml"

    if req_txt.exists():
        cmd = "pip install -r " + str(req_txt)
        label = "Python (pip)"
    elif pyproject.exists():
        cmd = "pip install -e " + str(project_dir)
        label = "Python (pyproject)"
    elif pkg_json.exists():
        cmd = f"npm install"
        label = "Node.js (npm)"
    else:
        cprint(f"[yellow]⚠ No requirements.txt or package.json found in {project_dir}[/yellow]")
        cprint(f"[dim]   Files present: {', '.join(f.name for f in project_dir.iterdir())}[/dim]")
        return

    cprint(f"[bold]📦 Installing dependencies for '[cyan]{name}[/cyan]' ({label})[/bold]")
    cprint(f"[yellow]⚡ Command: {cmd}[/yellow]")
    cprint(f"[dim]   Directory: {project_dir}[/dim]")
    confirm = input("Run install? [y/N]: ").strip().lower()
    if confirm != "y":
        cprint("[dim]Skipped.[/dim]")
        return

    cprint("[dim]Installing… this may take a moment.[/dim]")
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=str(project_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merge stderr into stdout so we see everything
    )

    # Print output line by line
    if result.stdout:
        for line in result.stdout.splitlines():
            if "error" in line.lower() or "failed" in line.lower():
                cprint(f"[red]{line}[/red]")
            elif "warning" in line.lower():
                cprint(f"[yellow]{line}[/yellow]")
            else:
                print(line)

    if result.returncode == 0:
        cprint(f"[bold green]✅ Dependencies installed successfully for '{name}'[/bold green]")
    else:
        cprint(f"[red]❌ Install failed (exit code {result.returncode})[/red]")
    logger.info(f"install_deps '{name}' exit={result.returncode}")

# ---------- Meta ----------

@register("show_history")
def action_show_history(**_):
    session.show_history()

@register("show_config")
def action_show_config(**_):
    if RICH and console:
        t = Table(title="Current Config", box=box.SIMPLE)
        t.add_column("Key",   style="cyan")
        t.add_column("Value", style="white")
        for k, v in CONFIG.items():
            t.add_row(k, str(v))
        console.print(t)
    else:
        print(json.dumps(CONFIG, indent=2))

@register("set_config")
def action_set_config(action: Dict, **_):
    key   = action.get("key", "")
    value = action.get("value")
    if key in CONFIG:
        CONFIG[key] = value
        save_config(CONFIG)
        cprint(f"[green]⚙️  Config updated: {key} = {value}[/green]")
        logger.info(f"Config set: {key}={value}")
    else:
        cprint(f"[red]Unknown config key: {key}[/red]")

# ─────────────────────────────────────────────────────────────────
# AI RESPONSE PARSER
# ─────────────────────────────────────────────────────────────────

def parse_ai_response(raw: str, user_input: str) -> Tuple[str, List[Dict]]:
    """Returns (reply_text, list_of_actions).

    Handles multiple JSON shapes that LLM models may produce:
      1. {"reply": "...", "actions": [{"action": "create_project", ...}]}  ← correct
      2. {"reply": "...", "actions": [{"create_project": {...}}]}           ← nested key
      3. {"reply": "...", "actions": [{"name": "create_project", ...}]}    ← name key
      4. {"reply": "...", "actions": [{"tool": "create_project", ...}]}    ← tool key
    """
    # Strip markdown fences
    clean = raw.strip()
    for fence in ("```json", "```"):
        clean = clean.replace(fence, "")
    clean = clean.strip()

    # Known action names for format-2 detection
    KNOWN_ACTIONS = {
        "open_app", "youtube_search", "play_youtube", "web_search",
        "create_file", "create_folder", "delete_path", "rename_path",
        "read_file", "open_file", "create_project", "create_website",
        "system_info", "list_processes", "kill_process",
        "screenshot", "clipboard_copy", "clipboard_paste",
        "run_command", "show_history", "show_config", "set_config", "install_deps",
    }

    try:
        data = json.loads(clean)
        reply   = data.get("reply", "Done.")
        actions = data.get("actions", [])

        # If actions is a plain dict (single action), wrap it
        if isinstance(actions, dict):
            actions = [actions]

        normalized: List[Dict] = []
        for a in actions:
            if not isinstance(a, dict):
                continue

            # ── Format 1: already has "action" key ──────────────────
            if "action" in a and a["action"] in KNOWN_ACTIONS:
                normalized.append(a)
                continue

            # ── Format 4: uses "name" or "tool" key ─────────────────
            if "action" not in a:
                for alias in ("name", "tool", "type", "command"):
                    if alias in a and a[alias] in KNOWN_ACTIONS:
                        a["action"] = a[alias]
                        normalized.append(a)
                        break
                else:
                    # ── Format 2: action name IS the top-level key ───
                    # e.g. {"create_project": {"name": "predictor", ...}}
                    matched = False
                    for key in list(a.keys()):
                        if key in KNOWN_ACTIONS:
                            inner = a[key]
                            if isinstance(inner, dict):
                                merged = {"action": key}
                                merged.update(inner)
                            else:
                                merged = {"action": key}
                            normalized.append(merged)
                            matched = True
                    if not matched:
                        logger.warning(f"Unrecognised action format, skipping: {a}")
            else:
                # "action" key exists but value not in KNOWN_ACTIONS — log and skip
                logger.warning(f"Unknown action name '{a.get('action')}' in response: {a}")

        return reply, normalized

    except json.JSONDecodeError:
        logger.warning(f"JSON parse failed. Raw:\n{raw[:400]}")

    # ── Keyword-based fallback ──────────────────────────────────────
    u = user_input.lower()
    fallback_reply = "I'll handle that for you."

    if "system" in u and ("info" in u or "status" in u):
        return fallback_reply, [{"action": "system_info"}]
    if "screenshot" in u:
        return fallback_reply, [{"action": "screenshot"}]
    if "youtube" in u or "play" in u or "watch" in u:
        query = u.replace("youtube", "").replace("play", "").replace("watch", "").strip()
        return fallback_reply, [{"action": "youtube_search", "query": query or u}]
    for ptype in ("ml", "data", "node", "python", "react", "fastapi", "flask", "nextjs"):
        if ptype in u and any(w in u for w in ("project", "create", "build", "make", "new")):
            name_guess = "my_project"
            words = u.split()
            for i, w in enumerate(words):
                if w == "called" and i + 1 < len(words):
                    name_guess = words[i + 1].strip(".,!?")
                    break
            return fallback_reply, [{
                "action": "create_project",
                "type": ptype,
                "name": name_guess,
                "description": u,
            }]
    if "machine learning" in u or " ml " in u:
        return fallback_reply, [{"action": "create_project", "type": "ml", "name": "ml_project", "description": u}]
    if any(w in u for w in ("install", "download", "dependencies", "packages", "pip install", "npm install")):
        # Extract project name — look for "for <name>" or "of <name>"
        words = u.split()
        name_guess = ""
        for trigger in ("for", "of"):
            if trigger in words:
                idx = words.index(trigger)
                if idx + 1 < len(words):
                    name_guess = words[idx + 1].strip(".,!?")
                    break
        if name_guess:
            return fallback_reply, [{"action": "install_deps", "name": name_guess}]

    if "google" in u or "search" in u:
        q = u.replace("search", "").replace("google", "").strip()
        return fallback_reply, [{"action": "web_search", "engine": "google", "query": q or u}]

    return "I'm not sure how to handle that. Could you rephrase?", []

# ─────────────────────────────────────────────────────────────────
# GROQ API CALL WITH RETRY + BACKOFF
# ─────────────────────────────────────────────────────────────────

def call_ai(user_input: str) -> Tuple[str, List[Dict]]:
    session.add_message("user", user_input)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + session.history

    max_retries = CONFIG.get("max_retries", 3)
    delay       = CONFIG.get("retry_delay", 2)

    for attempt in range(1, max_retries + 1):
        try:
            if RICH and console:
                with Progress(SpinnerColumn(), TextColumn("[bold cyan]Thinking…[/bold cyan]"),
                              transient=True) as prog:
                    task = prog.add_task("", total=None)
                    res  = client.chat.completions.create(
                        model=CONFIG["model"],
                        messages=messages,
                        temperature=0.1,
                        max_tokens=2048,
                    )
            else:
                print("🧠 Thinking…")
                res = client.chat.completions.create(
                    model=CONFIG["model"],
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2048,
                )

            raw = res.choices[0].message.content
            logger.debug(f"Raw AI response:\n{raw}")

            # Pre-sanitise: extract JSON block even if model adds prose around it
            raw_clean = raw.strip()
            # Strip markdown fences
            for fence in ("```json", "```"):
                raw_clean = raw_clean.replace(fence, "")
            raw_clean = raw_clean.strip()
            # If model output contains a JSON object somewhere, extract it
            brace_start = raw_clean.find("{")
            brace_end   = raw_clean.rfind("}")
            if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                raw_clean = raw_clean[brace_start:brace_end + 1]

            reply, actions = parse_ai_response(raw_clean, user_input)
            session.add_message("assistant", reply)
            return reply, actions

        except Exception as e:
            logger.error(f"AI call failed (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                cprint(f"[yellow]⚠ Retrying in {delay}s…[/yellow]")
                time.sleep(delay)
                delay *= 2

    return "Sorry, I couldn't reach the AI. Please check your connection and API key.", []

# ─────────────────────────────────────────────────────────────────
# COMMAND DISPATCHER
# ─────────────────────────────────────────────────────────────────

def dispatch(actions: List[Dict], user_input: str):
    dry_run = CONFIG.get("dry_run", False)
    if not actions:
        return

    for i, action in enumerate(actions, 1):
        # Resolve action name from multiple possible keys
        a_name = (
            action.get("action")
            or action.get("name")
            or action.get("tool")
            or action.get("type")
            or "unknown"
        )
        cprint(f"\n[bold]Step {i}/{len(actions)}:[/bold] [yellow]{a_name}[/yellow]")

        if dry_run:
            cprint(f"[dim]  (dry-run) {json.dumps(action)}[/dim]")
            session.log_action(action, "dry_run")
            continue

        fn = ACTIONS.get(a_name)
        if not fn:
            # Show available actions in error to help with debugging
            available = ", ".join(sorted(ACTIONS.keys()))
            cprint(f"[red]  ❌ Unknown action: '{a_name}'[/red]")
            cprint(f"[dim]  Available: {available}[/dim]")
            logger.warning(f"Unknown action '{a_name}'. Full action dict: {action}")
            session.log_action(action, "unknown_action")
            continue

        try:
            fn(action=action, user_input=user_input)
            session.log_action(action, "success")
        except Exception as e:
            cprint(f"[red]  ❌ Error executing '{a_name}': {e}[/red]")
            logger.error(f"Action '{a_name}' failed: {traceback.format_exc()}")
            session.log_action(action, "error", str(e))

# ─────────────────────────────────────────────────────────────────
# BUILT-IN COMMANDS (no AI needed)
# ─────────────────────────────────────────────────────────────────

BUILTINS: Dict[str, Callable] = {}

def builtin(keyword: str):
    def decorator(fn: Callable):
        BUILTINS[keyword] = fn
        return fn
    return decorator

@builtin("help")
def cmd_help():
    lines = [
        ("help",         "Show this help message"),
        ("history",      "Show conversation history"),
        ("config",       "Show current configuration"),
        ("dry-run",      "Toggle dry-run (preview) mode"),
        ("voice",        "Switch to voice input"),
        ("text",         "Switch to text input"),
        ("clear",        "Clear conversation history"),
        ("sysinfo",      "Show system information"),
        ("exit / quit",  "Exit ARIA"),
    ]
    if RICH and console:
        t = Table(title="ARIA Commands", box=box.SIMPLE)
        t.add_column("Command", style="bold cyan")
        t.add_column("Description")
        for cmd, desc in lines:
            t.add_row(cmd, desc)
        console.print(t)
    else:
        for cmd, desc in lines:
            print(f"  {cmd:<20} {desc}")

@builtin("history")
def cmd_history():
    session.show_history()

@builtin("config")
def cmd_config():
    action_show_config()

@builtin("sysinfo")
def cmd_sysinfo():
    action_system_info()

@builtin("clear")
def cmd_clear():
    session.history.clear()
    cprint("[green]✅ History cleared.[/green]")

# ─────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────

def shutdown(sig=None, frame=None):
    cprint("\n[bold cyan]👋 Shutting down ARIA…[/bold cyan]")
    session.save()
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────

def main():
    banner()

    cprint(f"[dim]Session ID: {session.id} | Model: {CONFIG['model']} | "
           f"Projects: {CONFIG['projects_root']}[/dim]")

    if CONFIG.get("dry_run"):
        cprint("[bold yellow]⚠ DRY-RUN MODE — actions will be previewed, not executed.[/bold yellow]")

    # Input mode selection
    cprint("\n[bold]Input mode:[/bold]  [1] Voice   [2] Text (default)")
    mode_choice = input("Select [1/2]: ").strip()
    voice_mode  = mode_choice == "1"

    if voice_mode and not all([sr_mod, sd_mod, np_mod]):
        cprint("[yellow]⚠ Voice dependencies missing. Falling back to text mode.[/yellow]")
        voice_mode = False

    cprint(f"\n[green]✅ ARIA ready · {'Voice' if voice_mode else 'Text'} mode[/green]")
    cprint("[dim]Type 'help' for commands, 'exit' to quit.[/dim]\n")

    while True:
        try:
            # --- Get user input ---
            user_input = listen() if voice_mode else get_text()
            user_input = user_input.strip()

            if not user_input:
                continue

            # --- Built-in commands ---
            cmd = user_input.lower().strip()

            if cmd in ("exit", "quit", "bye"):
                shutdown()

            if cmd == "voice":
                voice_mode = True
                cprint("[green]🎤 Switched to voice mode.[/green]")
                continue

            if cmd == "text":
                voice_mode = False
                cprint("[green]⌨️  Switched to text mode.[/green]")
                continue

            if cmd == "dry-run":
                CONFIG["dry_run"] = not CONFIG.get("dry_run", False)
                state = "ON" if CONFIG["dry_run"] else "OFF"
                cprint(f"[yellow]⚙️  Dry-run: {state}[/yellow]")
                continue

            if cmd in BUILTINS:
                BUILTINS[cmd]()
                continue

            # --- AI pipeline ---
            reply, actions = call_ai(user_input)

            # Print reply
            if RICH and console:
                console.print(Panel(reply, title="[bold green]ARIA[/bold green]", border_style="green"))
            else:
                print(f"\n🤖 ARIA: {reply}\n")

            # Execute actions
            dispatch(actions, user_input)

            cprint("\n[dim]─────────────────────────────────────[/dim]")

        except KeyboardInterrupt:
            shutdown()
        except Exception as e:
            logger.error(f"Unexpected error: {traceback.format_exc()}")
            cprint(f"[red]❌ Unexpected error: {e}[/red]")
            cprint("[dim]The session is still active. Keep going or type 'exit'.[/dim]")


if __name__ == "__main__":
    main()
