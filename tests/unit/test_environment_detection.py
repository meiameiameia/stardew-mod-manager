from __future__ import annotations

from pathlib import Path

from sdvmm.services.environment_detection import detect_game_environment, derive_mods_path


def test_detect_game_environment_with_mods_and_smapi(tmp_path: Path) -> None:
    game_path = tmp_path / "Stardew Valley"
    mods_path = game_path / "Mods"
    game_path.mkdir()
    (game_path / "Stardew Valley").write_text("binary", encoding="utf-8")
    mods_path.mkdir()
    smapi_path = game_path / "StardewModdingAPI"
    smapi_path.write_text("#!/bin/sh\necho smapi\n", encoding="utf-8")

    status = detect_game_environment(game_path)

    assert "game_path_detected" in status.state_codes
    assert "mods_path_detected" in status.state_codes
    assert "smapi_detected" in status.state_codes
    assert status.mods_path == mods_path
    assert status.smapi_path == smapi_path


def test_detect_game_environment_without_smapi(tmp_path: Path) -> None:
    game_path = tmp_path / "Stardew Valley"
    mods_path = game_path / "Mods"
    game_path.mkdir()
    (game_path / "Stardew Valley").write_text("binary", encoding="utf-8")
    mods_path.mkdir()

    status = detect_game_environment(game_path)

    assert "game_path_detected" in status.state_codes
    assert "mods_path_detected" in status.state_codes
    assert "smapi_not_detected" in status.state_codes
    assert status.smapi_path is None


def test_detect_game_environment_rejects_invalid_path(tmp_path: Path) -> None:
    status = detect_game_environment(tmp_path / "missing-game-path")

    assert status.state_codes == ("invalid_game_path",)
    assert status.mods_path is None
    assert status.smapi_path is None


def test_detect_game_environment_rejects_existing_directory_without_game_evidence(
    tmp_path: Path,
) -> None:
    game_path = tmp_path / "RandomFolder"
    game_path.mkdir()

    status = detect_game_environment(game_path)

    assert "invalid_game_path" in status.state_codes
    assert "game_path_detected" not in status.state_codes
    assert status.mods_path is None


def test_detect_game_environment_reports_mods_as_partial_state_without_game_evidence(
    tmp_path: Path,
) -> None:
    game_path = tmp_path / "RandomFolder"
    mods_path = game_path / "Mods"
    game_path.mkdir()
    mods_path.mkdir()

    status = detect_game_environment(game_path)

    assert "invalid_game_path" in status.state_codes
    assert "mods_path_detected" in status.state_codes
    assert status.mods_path == mods_path


def test_derive_mods_path_uses_game_path_root(tmp_path: Path) -> None:
    game_path = tmp_path / "Stardew Valley"
    assert derive_mods_path(game_path) == game_path / "Mods"
