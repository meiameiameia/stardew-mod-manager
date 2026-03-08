from __future__ import annotations

from pathlib import Path

from sdvmm.domain.models import AppConfig, AppConfigValidationResult, PathValidationIssue


def validate_app_config_paths(config: AppConfig) -> AppConfigValidationResult:
    issues: list[PathValidationIssue] = []

    issues.extend(_validate_required_directory(config.game_path, "game_path"))
    issues.extend(_validate_required_directory(config.mods_path, "mods_path"))

    if config.app_data_path.exists() and not config.app_data_path.is_dir():
        issues.append(
            PathValidationIssue(
                field="app_data_path",
                message="app_data_path exists but is not a directory",
            )
        )

    return AppConfigValidationResult(is_valid=not issues, issues=tuple(issues))


def _validate_required_directory(path: Path, field_name: str) -> list[PathValidationIssue]:
    issues: list[PathValidationIssue] = []

    if not path.exists():
        issues.append(
            PathValidationIssue(
                field=field_name,
                message=f"{field_name} does not exist: {path}",
            )
        )
        return issues

    if not path.is_dir():
        issues.append(
            PathValidationIssue(
                field=field_name,
                message=f"{field_name} is not a directory: {path}",
            )
        )

    return issues
