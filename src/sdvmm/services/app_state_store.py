from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

from sdvmm.domain.models import AppConfig

APP_STATE_VERSION = 1


class AppStateStoreError(ValueError):
    """Raised when app-state file content is invalid."""


def load_app_config(state_file: Path) -> AppConfig | None:
    if not state_file.exists():
        return None

    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise AppStateStoreError(f"Invalid JSON in app-state file: {exc.msg}") from exc
    except OSError as exc:
        raise AppStateStoreError(f"Could not read app-state file: {exc}") from exc

    if not isinstance(raw, dict):
        raise AppStateStoreError("App-state root must be a JSON object")

    version = raw.get("version")
    if version != APP_STATE_VERSION:
        raise AppStateStoreError(
            f"Unsupported app-state version: {version!r}; expected {APP_STATE_VERSION}"
        )

    app_config = raw.get("app_config")
    if not isinstance(app_config, dict):
        raise AppStateStoreError("app_config must be an object")

    game_path = _require_non_empty_string(app_config, "game_path")
    mods_path = _require_non_empty_string(app_config, "mods_path")
    app_data_path = _require_non_empty_string(app_config, "app_data_path")

    return AppConfig(
        game_path=Path(game_path),
        mods_path=Path(mods_path),
        app_data_path=Path(app_data_path),
    )


def save_app_config(state_file: Path, config: AppConfig) -> None:
    payload = {
        "version": APP_STATE_VERSION,
        "app_config": {
            "game_path": str(config.game_path),
            "mods_path": str(config.mods_path),
            "app_data_path": str(config.app_data_path),
        },
    }

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_non_empty_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AppStateStoreError(f"app_config.{key} must be a non-empty string")
    return value
