from __future__ import annotations

from typing import Literal

EnvironmentState = Literal[
    "game_path_detected",
    "mods_path_detected",
    "smapi_detected",
    "smapi_not_detected",
    "invalid_game_path",
]

GAME_PATH_DETECTED: EnvironmentState = "game_path_detected"
MODS_PATH_DETECTED: EnvironmentState = "mods_path_detected"
SMAPI_DETECTED: EnvironmentState = "smapi_detected"
SMAPI_NOT_DETECTED: EnvironmentState = "smapi_not_detected"
INVALID_GAME_PATH: EnvironmentState = "invalid_game_path"

