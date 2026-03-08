from __future__ import annotations

from pathlib import Path

from sdvmm.domain.models import AppConfig
from sdvmm.services.path_validation import validate_app_config_paths


def test_app_config_validation_reports_missing_directories(tmp_path: Path) -> None:
    config = AppConfig(
        game_path=tmp_path / "missing-game",
        mods_path=tmp_path / "missing-mods",
        app_data_path=tmp_path / "appdata",
    )

    result = validate_app_config_paths(config)

    assert result.is_valid is False
    assert [issue.field for issue in result.issues] == ["game_path", "mods_path"]


def test_app_config_validation_accepts_existing_directories(tmp_path: Path) -> None:
    game_path = tmp_path / "game"
    mods_path = tmp_path / "mods"
    app_data_path = tmp_path / "appdata"
    game_path.mkdir()
    mods_path.mkdir()

    config = AppConfig(game_path=game_path, mods_path=mods_path, app_data_path=app_data_path)
    result = validate_app_config_paths(config)

    assert result.is_valid is True
    assert result.issues == ()
