from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal
import zipfile

from sdvmm.domain.models import (
    AppConfig,
    ModUpdateReport,
    ModsInventory,
    PackageInspectionResult,
    SandboxInstallPlan,
    SandboxInstallResult,
)
from sdvmm.services.app_state_store import (
    AppStateStoreError,
    load_app_config,
    save_app_config,
)
from sdvmm.services.mod_scanner import scan_mods_directory
from sdvmm.services.package_inspector import inspect_zip_package
from sdvmm.services.sandbox_installer import (
    SandboxInstallError,
    build_sandbox_install_plan as build_sandbox_install_plan_service,
    execute_sandbox_install_plan as execute_sandbox_install_plan_service,
)
from sdvmm.services.update_metadata import check_updates_for_inventory


class AppShellError(ValueError):
    """Recoverable UI-facing error for config and scan actions."""


@dataclass(frozen=True, slots=True)
class StartupConfigState:
    config: AppConfig | None
    message: str | None


ScanTargetKind = Literal["configured_real_mods", "sandbox_mods"]
SCAN_TARGET_CONFIGURED_REAL_MODS: ScanTargetKind = "configured_real_mods"
SCAN_TARGET_SANDBOX_MODS: ScanTargetKind = "sandbox_mods"


@dataclass(frozen=True, slots=True)
class ScanResult:
    target_kind: ScanTargetKind
    scan_path: Path
    inventory: ModsInventory


@dataclass(frozen=True, slots=True)
class InstallTargetSafetyDecision:
    allowed: bool
    message: str | None


class AppShellService:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file

    @property
    def state_file(self) -> Path:
        return self._state_file

    def load_startup_config(self) -> StartupConfigState:
        try:
            config = load_app_config(self._state_file)
        except AppStateStoreError as exc:
            return StartupConfigState(config=None, message=f"Could not load saved config: {exc}")

        if config is None:
            return StartupConfigState(
                config=None,
                message="No saved configuration found. Set a Mods directory and save config.",
            )

        mods_path = config.mods_path
        if not mods_path.exists() or not mods_path.is_dir():
            return StartupConfigState(
                config=config,
                message=f"Saved Mods path is not accessible: {mods_path}",
            )

        return StartupConfigState(config=config, message=None)

    def save_mods_directory(
        self,
        mods_dir_text: str,
        existing_config: AppConfig | None,
    ) -> AppConfig:
        mods_path = self._parse_and_validate_mods_path(mods_dir_text)
        config = self._build_config(mods_path=mods_path, existing_config=existing_config)

        try:
            save_app_config(state_file=self._state_file, config=config)
        except OSError as exc:
            raise AppShellError(f"Could not save configuration: {exc}") from exc

        return config

    def scan(self, mods_dir_text: str) -> ModsInventory:
        mods_path = self._parse_and_validate_mods_path(mods_dir_text)

        try:
            return scan_mods_directory(mods_path)
        except OSError as exc:
            raise AppShellError(f"Could not scan Mods directory: {exc}") from exc

    def scan_with_target(
        self,
        *,
        scan_target: ScanTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
    ) -> ScanResult:
        if scan_target == SCAN_TARGET_CONFIGURED_REAL_MODS:
            scan_path = self._parse_and_validate_mods_path(configured_mods_path_text)
        elif scan_target == SCAN_TARGET_SANDBOX_MODS:
            scan_path = self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
        else:
            raise AppShellError(f"Unknown scan target: {scan_target}")

        try:
            inventory = scan_mods_directory(scan_path)
        except OSError as exc:
            raise AppShellError(f"Could not scan selected target: {exc}") from exc

        return ScanResult(target_kind=scan_target, scan_path=scan_path, inventory=inventory)

    def inspect_zip(self, package_path_text: str) -> PackageInspectionResult:
        package_path = self._parse_and_validate_zip_path(package_path_text)

        try:
            return inspect_zip_package(package_path)
        except zipfile.BadZipFile as exc:
            raise AppShellError(f"File is not a valid zip package: {package_path}") from exc
        except OSError as exc:
            raise AppShellError(f"Could not inspect package: {exc}") from exc

    def check_updates(self, inventory: ModsInventory) -> ModUpdateReport:
        try:
            return check_updates_for_inventory(inventory)
        except OSError as exc:
            raise AppShellError(f"Could not check remote metadata: {exc}") from exc

    def build_sandbox_install_plan(
        self,
        package_path_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        *,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
    ) -> SandboxInstallPlan:
        package_path = self._parse_and_validate_zip_path(package_path_text)
        sandbox_mods_path = self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
        safety = self.evaluate_install_target_safety(
            sandbox_mods_path=sandbox_mods_path,
            configured_real_mods_path=configured_real_mods_path,
        )
        if not safety.allowed:
            assert safety.message is not None
            raise AppShellError(safety.message)

        sandbox_archive_path = self._parse_and_validate_sandbox_archive_path(
            sandbox_archive_path_text=sandbox_archive_path_text,
            sandbox_mods_path=sandbox_mods_path,
        )

        try:
            return build_sandbox_install_plan_service(
                package_path=package_path,
                sandbox_mods_path=sandbox_mods_path,
                sandbox_archive_path=sandbox_archive_path,
                allow_overwrite=allow_overwrite,
            )
        except (SandboxInstallError, zipfile.BadZipFile) as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Could not build sandbox install plan: {exc}") from exc

    def execute_sandbox_install_plan(self, plan: SandboxInstallPlan) -> SandboxInstallResult:
        try:
            return execute_sandbox_install_plan_service(plan)
        except SandboxInstallError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Sandbox install failed: {exc}") from exc

    def evaluate_install_target_safety(
        self,
        *,
        sandbox_mods_path: Path,
        configured_real_mods_path: Path | None,
    ) -> InstallTargetSafetyDecision:
        if configured_real_mods_path is None:
            return InstallTargetSafetyDecision(allowed=True, message=None)

        if _paths_deterministically_match(sandbox_mods_path, configured_real_mods_path):
            return InstallTargetSafetyDecision(
                allowed=False,
                message=(
                    "Sandbox install target matches configured real Mods path. "
                    "This stage blocks installs to that destination."
                ),
            )

        return InstallTargetSafetyDecision(allowed=True, message=None)

    def _build_config(self, mods_path: Path, existing_config: AppConfig | None) -> AppConfig:
        if existing_config is not None:
            return AppConfig(
                game_path=existing_config.game_path,
                mods_path=mods_path,
                app_data_path=existing_config.app_data_path,
            )

        return AppConfig(
            game_path=mods_path.parent,
            mods_path=mods_path,
            app_data_path=self._state_file.parent,
        )

    @staticmethod
    def _parse_and_validate_mods_path(mods_dir_text: str) -> Path:
        raw_value = mods_dir_text.strip()
        if not raw_value:
            raise AppShellError("Mods directory is required")

        mods_path = Path(raw_value).expanduser()
        if not mods_path.exists():
            raise AppShellError(f"Mods directory does not exist: {mods_path}")
        if not mods_path.is_dir():
            raise AppShellError(f"Mods path is not a directory: {mods_path}")

        return mods_path

    @staticmethod
    def _parse_and_validate_zip_path(package_path_text: str) -> Path:
        raw_value = package_path_text.strip()
        if not raw_value:
            raise AppShellError("Zip package path is required")

        package_path = Path(raw_value).expanduser()
        if not package_path.exists():
            raise AppShellError(f"Zip package does not exist: {package_path}")
        if not package_path.is_file():
            raise AppShellError(f"Zip package path is not a file: {package_path}")
        if package_path.suffix.lower() != ".zip":
            raise AppShellError(f"File is not a .zip package: {package_path}")

        return package_path

    @staticmethod
    def _parse_and_validate_sandbox_mods_path(sandbox_mods_path_text: str) -> Path:
        raw_value = sandbox_mods_path_text.strip()
        if not raw_value:
            raise AppShellError("Sandbox Mods directory is required")

        sandbox_mods_path = Path(raw_value).expanduser()
        if not sandbox_mods_path.exists():
            raise AppShellError(f"Sandbox Mods directory does not exist: {sandbox_mods_path}")
        if not sandbox_mods_path.is_dir():
            raise AppShellError(
                f"Sandbox Mods directory path is not a directory: {sandbox_mods_path}"
            )

        return sandbox_mods_path

    @staticmethod
    def _parse_and_validate_sandbox_archive_path(
        sandbox_archive_path_text: str,
        sandbox_mods_path: Path,
    ) -> Path:
        raw_value = sandbox_archive_path_text.strip()
        archive_path = (
            (sandbox_mods_path / ".sdvmm-archive")
            if not raw_value
            else Path(raw_value).expanduser()
        )

        if archive_path.exists() and not archive_path.is_dir():
            raise AppShellError(f"Sandbox archive path is not a directory: {archive_path}")

        parent = archive_path.parent
        if not parent.exists() or not parent.is_dir():
            raise AppShellError(
                f"Sandbox archive parent directory is not accessible: {parent}"
            )

        return archive_path


def _paths_deterministically_match(path_a: Path, path_b: Path) -> bool:
    left = path_a.expanduser()
    right = path_b.expanduser()

    try:
        if left.exists() and right.exists() and left.samefile(right):
            return True
    except OSError:
        pass

    left_resolved = left.resolve(strict=False)
    right_resolved = right.resolve(strict=False)
    if left_resolved == right_resolved:
        return True

    left_text = str(left_resolved)
    right_text = str(right_resolved)
    if os.name == "nt":
        return left_text.casefold() == right_text.casefold()

    return left_text == right_text
