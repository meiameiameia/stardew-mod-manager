from __future__ import annotations

from pathlib import Path


def default_app_state_file() -> Path:
    return Path.home() / ".config" / "sdvmm" / "app-state.json"
