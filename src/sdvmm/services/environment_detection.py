from __future__ import annotations

from pathlib import Path

from sdvmm.domain.environment_codes import (
    GAME_PATH_DETECTED,
    INVALID_GAME_PATH,
    MODS_PATH_DETECTED,
    SMAPI_DETECTED,
    SMAPI_NOT_DETECTED,
)
from sdvmm.domain.models import GameEnvironmentStatus


def detect_game_environment(game_path: Path) -> GameEnvironmentStatus:
    normalized_game_path = game_path.expanduser()
    if not normalized_game_path.exists() or not normalized_game_path.is_dir():
        return GameEnvironmentStatus(
            game_path=normalized_game_path,
            mods_path=None,
            smapi_path=None,
            state_codes=(INVALID_GAME_PATH,),
            notes=(f"Invalid game path: {normalized_game_path}",),
        )

    state_codes: list[str] = []
    notes: list[str] = []

    game_evidence_path = _detect_game_evidence_path(normalized_game_path)
    mods_path = derive_mods_path(normalized_game_path)
    if mods_path.exists() and mods_path.is_dir():
        state_codes.append(MODS_PATH_DETECTED)
    else:
        mods_path = None
        notes.append("Mods directory was not detected under selected game path.")

    smapi_path = _detect_smapi_path(normalized_game_path)
    if smapi_path is not None:
        state_codes.append(SMAPI_DETECTED)
    else:
        state_codes.append(SMAPI_NOT_DETECTED)
        notes.append("SMAPI entrypoint was not detected in selected game path.")

    if game_evidence_path is not None or smapi_path is not None:
        state_codes.insert(0, GAME_PATH_DETECTED)
        if game_evidence_path is not None:
            notes.append(f"Game installation evidence found: {game_evidence_path.name}")
        elif smapi_path is not None:
            notes.append(
                "Game installation evidence was inferred from SMAPI entrypoint presence."
            )
    else:
        state_codes.insert(0, INVALID_GAME_PATH)
        notes.append(
            "Directory exists but does not contain deterministic Stardew Valley game evidence."
        )

    return GameEnvironmentStatus(
        game_path=normalized_game_path,
        mods_path=mods_path,
        smapi_path=smapi_path,
        state_codes=tuple(state_codes),
        notes=tuple(notes),
    )


def derive_mods_path(game_path: Path) -> Path:
    return game_path / "Mods"


def _detect_smapi_path(game_path: Path) -> Path | None:
    candidate_names = (
        "StardewModdingAPI",
        "StardewModdingAPI.sh",
        "StardewModdingAPI.exe",
        "StardewModdingAPI.dll",
    )
    for name in candidate_names:
        candidate = game_path / name
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def _detect_game_evidence_path(game_path: Path) -> Path | None:
    evidence_candidates = (
        "Stardew Valley",
        "Stardew Valley.exe",
        "Stardew Valley.dll",
        "StardewValley",
        "StardewValley.exe",
        "StardewValley.dll",
    )
    for name in evidence_candidates:
        candidate = game_path / name
        if candidate.exists() and candidate.is_file():
            return candidate

    return None
