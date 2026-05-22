"""
Runtime settings store.

All editable content (prompts, config, data files) is read/written here.
Modules call load_prompt() to pick up UI-saved overrides at call time.
Config values are loaded by config.py on import via load_config_overrides().
"""

import json
from pathlib import Path

_BASE        = Path(__file__).parent / "data"
_PROMPTS_DIR = _BASE / "prompts"
_CFG_PATH    = _BASE / "settings.json"


# ── Prompt overrides ──────────────────────────────────────────────────────────

def load_prompt(filename: str, default: str) -> str:
    """Return the saved override prompt if it exists, else the hardcoded default."""
    path = _PROMPTS_DIR / filename
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return default


def save_prompt(filename: str, content: str) -> None:
    _PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (_PROMPTS_DIR / filename).write_text(content.strip(), encoding="utf-8")


def delete_prompt_override(filename: str) -> None:
    """Delete the override file so the module falls back to its hardcoded default."""
    path = _PROMPTS_DIR / filename
    if path.exists():
        path.unlink()


# ── Config overrides ──────────────────────────────────────────────────────────

def load_config_overrides() -> dict:
    try:
        if _CFG_PATH.exists():
            return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config_overrides(data: dict) -> None:
    _BASE.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Data files ────────────────────────────────────────────────────────────────

def load_data_file(relative_path: str) -> str:
    path = _BASE / relative_path
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def save_data_file(relative_path: str, content: str) -> None:
    path = _BASE / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
