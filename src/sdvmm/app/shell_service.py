from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from collections.abc import Iterable
from collections import Counter
import re
import shutil
import subprocess
import tempfile
from typing import Literal
from uuid import uuid4
import zipfile

from sdvmm.domain.models import (
    ArchivedModEntry,
    ArchiveCleanupPlan,
    ArchiveCleanupResult,
    ArchiveDeletePlan,
    ArchiveDeleteResult,
    ArchiveRetentionGroup,
    ArchiveRestorePlan,
    ArchiveRestoreResult,
    AppConfig,
    AppUpdateStatus,
    BackupBundleInspectionItem,
    BackupBundleInspectionResult,
    CinderleafManagedMigrationEntry,
    CinderleafManagedMigrationResult,
    CinderleafManagedPaths,
    RestoreImportExecutionReview,
    RestoreImportExecutionResult,
    RestoreImportPlanningConfigEntry,
    RestoreImportPlanningItem,
    RestoreImportPlanningItemState,
    RestoreImportPlanningModEntry,
    RestoreImportPlanningResult,
    DependencyPreflightFinding,
    DownloadsIntakeResult,
    DownloadsWatchPollResult,
    GameEnvironmentStatus,
    InstalledMod,
    InstallExecutionActionCount,
    InstallExecutionReview,
    InstallExecutionSummary,
    InstallOperationEntryRecord,
    InstallOperationHistory,
    InstallOperationRecord,
    InstallRecoveryExecutionReview,
    InstallRecoveryExecutionResult,
    InstallRecoveryInspectionResult,
    InstallRecoveryExecutionReviewEntry,
    InstallRecoveryExecutionReviewSummary,
    InstallRecoveryPlan,
    InstallRecoveryPlanEntry,
    InstallRecoveryPlanSummary,
    RecoveryExecutionHistory,
    RecoveryExecutionRecord,
    SandboxModProfile,
    SandboxModProfileCatalog,
    SandboxModProfileEntry,
    ModDiscoveryEntry,
    ModDiscoveryResult,
    ModsCompareEntry,
    ModsCompareResult,
    ModRemovalPlan,
    ModRemovalResult,
    ModRollbackPlan,
    ModRollbackResult,
    ModUpdateReport,
    UpdateSourceIntentOverlay,
    UpdateSourceIntentRecord,
    UpdateSourceIntentState,
    ModsInventory,
    NexusIntegrationStatus,
    PackageInspectionBatchEntry,
    PackageInspectionBatchResult,
    PackageInspectionResult,
    PackageModEntry,
    SmapiLogReport,
    SmapiUpdateStatus,
    SandboxInstallPlan,
    SandboxInstallPlanEntry,
    SandboxInstallResult,
    SmapiContextLogCaptureResult,
)
from sdvmm.domain.nexus_codes import (
    NEXUS_CONFIGURED,
    NEXUS_NOT_CONFIGURED,
)
from sdvmm.domain.install_codes import BLOCKED, INSTALL_NEW, OVERWRITE_WITH_ARCHIVE
from sdvmm.domain.dependency_codes import (
    MISSING_REQUIRED_DEPENDENCY,
    OPTIONAL_DEPENDENCY_MISSING,
    SATISFIED,
    UNRESOLVED_DEPENDENCY_CONTEXT,
)
from sdvmm.domain.scan_codes import DIRECT_MOD, MULTI_MOD_CONTAINER, NESTED_MOD_CONTAINER
from sdvmm.domain.unique_id import canonicalize_unique_id
from sdvmm.services.app_state_store import (
    AppStateStoreError,
    append_install_operation_record,
    append_recovery_execution_record,
    install_operation_history_file,
    load_install_operation_history,
    load_real_mod_profile_catalog,
    load_recovery_execution_history,
    load_app_config,
    load_sandbox_mod_profile_catalog,
    real_mod_profile_catalog_file,
    recovery_execution_history_file,
    save_real_mod_profile_catalog,
    sandbox_mod_profile_catalog_file,
    save_app_config,
    save_sandbox_mod_profile_catalog,
    load_update_source_intent_overlay,
    save_update_source_intent_overlay,
    update_source_intent_overlay_file,
    write_json_file_atomic,
    write_text_file_atomic,
)
from sdvmm.services.mod_scanner import scan_mods_directory
from sdvmm.services.package_inspector import inspect_zip_package
from sdvmm.services.downloads_intake import (
    initialize_known_zip_paths,
    inspect_downloads_intake_package,
    poll_watched_directory,
)
from sdvmm.services.manifest_parser import parse_manifest_file
from sdvmm.services.environment_detection import detect_game_environment as detect_game_environment_service
from sdvmm.services.environment_detection import derive_mods_path
from sdvmm.app.paths import platform_default_stardew_save_directory
from sdvmm.services.dependency_preflight import (
    evaluate_installed_dependencies,
    evaluate_package_dependencies,
    summarize_missing_required_dependencies,
)
from sdvmm.services.sandbox_installer import (
    SandboxFileLockError,
    SandboxInstallError,
    _build_archive_destination as _build_archive_destination_service,
    _ensure_archive_root as _ensure_archive_root_service,
    _overwrite_target_with_archive as _overwrite_target_with_archive_service,
    build_sandbox_install_plan as build_sandbox_install_plan_service,
    execute_sandbox_install_plan as execute_sandbox_install_plan_service,
    remove_mod_to_archive as remove_mod_to_archive_service,
)
from sdvmm.services.archive_manager import (
    allocate_archive_destination,
    ArchiveManagerError,
    delete_archived_mod_entry,
    list_archived_mod_entries,
    rollback_installed_mod_from_archive,
    restore_archived_mod_entry,
)
from sdvmm.services.update_metadata import (
    NEXUS_API_KEY_ENV,
    check_nexus_connection,
    check_updates_for_inventory,
    mask_api_key,
    normalize_nexus_api_key,
)
from sdvmm.services.remote_requirements import evaluate_remote_requirements_for_package_mods
from sdvmm.services.mod_discovery import (
    DiscoveryServiceError,
    search_discoverable_mods,
)
from sdvmm.services.game_launcher import (
    GameLaunchError,
    LaunchCommand,
    launch_game_process,
    resolve_launch_command,
)
from sdvmm.services.app_update import (
    check_app_update_status as check_app_update_status_service,
    default_app_update_page_url,
)
from sdvmm.services.smapi_update import (
    check_smapi_update_status as check_smapi_update_status_service,
    default_smapi_update_page_url,
)
from sdvmm.services.update_metadata import compare_versions
from sdvmm.services.smapi_log import (
    capture_cinderleaf_context_log as capture_cinderleaf_context_log_service,
    check_smapi_log_troubleshooting as check_smapi_log_troubleshooting_service,
    cinderleaf_smapi_context_directory,
    cinderleaf_smapi_latest_log_path as cinderleaf_smapi_latest_log_path_service,
)


class AppShellError(ValueError):
    """Recoverable UI-facing error for config and scan actions."""

    def __init__(self, message: str, *, detail_message: str | None = None) -> None:
        super().__init__(message)
        self.detail_message = detail_message or message


@dataclass(frozen=True, slots=True)
class StartupConfigState:
    config: AppConfig | None
    message: str | None


@dataclass(frozen=True, slots=True)
class SessionConfigPersistenceResult:
    persisted: bool
    config: AppConfig | None
    message: str | None = None


ScanTargetKind = Literal["configured_real_mods", "sandbox_mods"]
SCAN_TARGET_CONFIGURED_REAL_MODS: ScanTargetKind = "configured_real_mods"
SCAN_TARGET_SANDBOX_MODS: ScanTargetKind = "sandbox_mods"
InstallTargetKind = ScanTargetKind
INSTALL_TARGET_CONFIGURED_REAL_MODS: InstallTargetKind = SCAN_TARGET_CONFIGURED_REAL_MODS
INSTALL_TARGET_SANDBOX_MODS: InstallTargetKind = SCAN_TARGET_SANDBOX_MODS
_DEFAULT_REAL_ARCHIVE_DIRNAME = ".sdvmm-real-archive"
_DEFAULT_SANDBOX_ARCHIVE_DIRNAME = ".sdvmm-sandbox-archive"
_LEGACY_ARCHIVE_DIRNAME = ".sdvmm-archive"
ArchiveSourceKind = Literal["real_archive", "sandbox_archive"]
ARCHIVE_SOURCE_REAL: ArchiveSourceKind = "real_archive"
ARCHIVE_SOURCE_SANDBOX: ArchiveSourceKind = "sandbox_archive"
ARCHIVE_RETENTION_KEEP_LATEST_COUNT = 3
BACKUP_BUNDLE_FORMAT = "cinderleaf-local-backup"
LEGACY_BACKUP_BUNDLE_FORMATS = {"sdvmm-local-backup", BACKUP_BUNDLE_FORMAT}
DEFAULT_REAL_PROFILE_ID = "default"
DEFAULT_REAL_PROFILE_NAME = "Default"
DEFAULT_SANDBOX_PROFILE_ID = "default"
DEFAULT_SANDBOX_PROFILE_NAME = "Default"
_PROFILES_DIRNAME = "Profiles"
_SANDBOX_PROFILE_GROUP_DIRNAME = "Sandbox Mods"
_REAL_PROFILE_GROUP_DIRNAME = "Real Mods"
_SANDBOX_PROFILE_MODS_DIRNAME = "Mods"


@dataclass(frozen=True, slots=True)
class ScanResult:
    target_kind: ScanTargetKind
    scan_path: Path
    inventory: ModsInventory


@dataclass(frozen=True, slots=True)
class SandboxModProfileCreateResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult
    linked_mod_count: int


@dataclass(frozen=True, slots=True)
class SandboxModProfileSelectResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult


@dataclass(frozen=True, slots=True)
class SandboxModProfileDeleteResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult | None = None


@dataclass(frozen=True, slots=True)
class RealModProfileCreateResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult
    linked_mod_count: int


@dataclass(frozen=True, slots=True)
class RealModProfileSelectResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult


@dataclass(frozen=True, slots=True)
class RealModProfileDeleteResult:
    profile: SandboxModProfile
    profiles: SandboxModProfileCatalog
    scan_result: ScanResult | None = None


@dataclass(frozen=True, slots=True)
class _ProfileEntryState:
    folder_name: str
    entry_path: Path
    enabled: bool
    mods: tuple[InstalledMod, ...]


@dataclass(frozen=True, slots=True)
class SteamPrelaunchResult:
    state: Literal[
        "disabled",
        "already_running",
        "start_attempted",
        "start_failed",
        "state_unknown",
    ]
    message: str


@dataclass(frozen=True, slots=True)
class LaunchStartResult:
    mode: str
    game_path: Path
    executable_path: Path
    pid: int
    mods_path_override: Path | None = None
    steam_prelaunch_state: Literal[
        "disabled",
        "already_running",
        "start_attempted",
        "start_failed",
        "state_unknown",
    ] = "state_unknown"
    steam_prelaunch_message: str = ""


@dataclass(frozen=True, slots=True)
class SandboxDevLaunchReadiness:
    ready: bool
    message: str
    game_path: Path | None = None
    sandbox_mods_path: Path | None = None
    executable_path: Path | None = None


@dataclass(frozen=True, slots=True)
class SandboxModsSyncReadiness:
    ready: bool
    message: str
    real_mods_path: Path | None = None
    sandbox_mods_path: Path | None = None
    selected_count: int = 0


@dataclass(frozen=True, slots=True)
class SandboxModsSyncResult:
    real_mods_path: Path
    sandbox_mods_path: Path
    source_mod_paths: tuple[Path, ...]
    synced_target_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SandboxModsPromotionReadiness:
    ready: bool
    message: str
    real_mods_path: Path | None = None
    sandbox_mods_path: Path | None = None
    archive_path: Path | None = None
    selected_count: int = 0
    replace_count: int = 0


@dataclass(frozen=True, slots=True)
class SandboxModsPromotionPreview:
    plan: SandboxInstallPlan
    review: InstallExecutionReview
    real_mods_path: Path
    sandbox_mods_path: Path
    archive_path: Path
    source_mod_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SandboxModsPromotionResult:
    destination_kind: InstallTargetKind
    real_mods_path: Path
    sandbox_mods_path: Path
    archive_path: Path
    source_mod_paths: tuple[Path, ...]
    promoted_target_paths: tuple[Path, ...]
    archived_target_paths: tuple[Path, ...]
    replaced_target_paths: tuple[Path, ...]
    scan_context_path: Path
    inventory: ModsInventory


@dataclass(frozen=True, slots=True)
class InstallTargetSafetyDecision:
    allowed: bool
    message: str | None
    requires_explicit_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class IntakeUpdateCorrelation:
    intake: DownloadsIntakeResult
    actionable: bool
    matched_update_available_unique_ids: tuple[str, ...]
    matched_guided_update_unique_ids: tuple[str, ...]
    comparison_target_kind: ScanTargetKind | None
    comparison_target_label: str
    comparison_state: Literal[
        "target_inventory_unavailable",
        "not_installed_in_target",
        "newer_than_installed",
        "same_version_installed",
        "older_than_installed",
        "version_comparison_unavailable",
        "mixed_version_state",
    ]
    actionable_as_update: bool
    summary: str
    next_step: str


@dataclass(frozen=True, slots=True)
class IntakeVersionComparison:
    package_name: str
    package_unique_id: str
    package_version: str
    installed_name: str | None
    installed_unique_id: str | None
    installed_version: str | None
    state: Literal["not_installed", "newer", "same", "older", "unavailable"]


@dataclass(frozen=True, slots=True)
class DiscoveryContextCorrelation:
    entry: ModDiscoveryEntry
    installed_match_unique_id: str | None
    update_state: str | None
    provider_relation: str
    provider_relation_note: str | None
    context_summary: str
    next_step: str


@dataclass(frozen=True, slots=True)
class BackupBundleExportItem:
    key: str
    label: str
    kind: Literal["file", "directory"]
    status: Literal["copied", "not_present", "not_configured", "configured_missing"]
    relative_path: Path
    source_path: Path | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class BackupBundleExportSelection:
    include_manager_state: bool = True
    include_managed_mods: bool = True
    include_archives: bool = True
    include_save_files: bool = False


@dataclass(frozen=True, slots=True)
class BackupBundleExportResult:
    bundle_path: Path
    manifest_path: Path
    summary_path: Path
    created_at_utc: str
    items: tuple[BackupBundleExportItem, ...]
    bundle_storage_kind: Literal["directory", "zip"] = "directory"


@dataclass(frozen=True, slots=True)
class _BackupBundleSourceResolution:
    path: Path | None
    missing_status: Literal["not_present", "not_configured", "configured_missing"]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedModConfigSnapshot:
    item: BackupBundleExportItem
    temp_root: Path | None = None


@dataclass(slots=True)
class _PreparedBackupBundleZipContent:
    artifact_path: Path
    content_root_path: Path
    temp_dir: tempfile.TemporaryDirectory[str]
    signature: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _RestoreImportPlanningLocalTargets:
    app_state_path: Path
    install_history_path: Path
    recovery_history_path: Path
    update_source_intent_overlay_path: Path
    real_mods_path: Path | None
    sandbox_mods_path: Path | None
    real_archive_path: Path | None
    sandbox_archive_path: Path | None
    bundle_config: AppConfig | None
    bundle_config_warning: str | None = None


@dataclass(frozen=True, slots=True)
class _RestoreImportExecutableModAction:
    bundle_item_key: str
    unique_id: str
    source_path: Path
    destination_path: Path
    action_kind: Literal["restore_missing", "archive_replace"]
    archive_root: Path | None = None
    archive_destination_path: Path | None = None
    replace_config_count: int = 0


@dataclass(frozen=True, slots=True)
class _RestoreImportExecutableConfigAction:
    bundle_item_key: str
    relative_path: Path
    source_path: Path
    destination_path: Path


@dataclass(frozen=True, slots=True)
class _RestoreImportExecutionAnalysis:
    mod_actions: tuple[_RestoreImportExecutableModAction, ...]
    config_actions: tuple[_RestoreImportExecutableConfigAction, ...]
    replace_mod_count: int
    replace_config_count: int
    covered_config_count: int
    review_entry_count: int
    blocked_entry_count: int
    deferred_item_count: int
    warnings: tuple[str, ...]


_ACTIONABLE_INTAKE_CLASSIFICATIONS = {
    "new_install_candidate",
    "update_replace_candidate",
    "multi_mod_package",
}
_ARCHIVE_SUFFIX_SEQUENCE_PATTERN = re.compile(r"^(?P<target>.+)__sdvmm_archive_(?P<sequence>[0-9]{3,})$")


class AppShellService:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._prepared_backup_bundle_zip_content: dict[Path, _PreparedBackupBundleZipContent] = {}

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

    def load_install_operation_history(self) -> InstallOperationHistory:
        try:
            return load_install_operation_history(self._install_operation_history_file)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not load install history: {exc}") from exc

    def load_recovery_execution_history(self) -> RecoveryExecutionHistory:
        try:
            return load_recovery_execution_history(self._recovery_execution_history_file)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not load recovery history: {exc}") from exc

    def load_update_source_intent_overlay(self) -> UpdateSourceIntentOverlay:
        try:
            return load_update_source_intent_overlay(self._update_source_intent_overlay_file)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not load update-source intent overlay: {exc}") from exc

    def get_update_source_intent(self, unique_id: str) -> UpdateSourceIntentRecord | None:
        canonical_unique_id = _require_canonical_unique_id(unique_id)
        overlay = self.load_update_source_intent_overlay()
        return next(
            (
                record
                for record in overlay.records
                if record.normalized_unique_id == canonical_unique_id
            ),
            None,
        )

    def set_update_source_intent(
        self,
        unique_id: str,
        intent_state: UpdateSourceIntentState,
        *,
        manual_provider: str | None = None,
        manual_source_key: str | None = None,
        manual_source_page_url: str | None = None,
    ) -> UpdateSourceIntentOverlay:
        normalized_unique_id = _require_canonical_unique_id(unique_id)
        display_unique_id = unique_id.strip()
        record = UpdateSourceIntentRecord(
            unique_id=display_unique_id,
            normalized_unique_id=normalized_unique_id,
            intent_state=intent_state,
            manual_provider=_normalize_optional_text(manual_provider),
            manual_source_key=_normalize_optional_text(manual_source_key),
            manual_source_page_url=_normalize_optional_text(manual_source_page_url),
        )
        overlay = self.load_update_source_intent_overlay()
        updated = UpdateSourceIntentOverlay(
            records=_upsert_update_source_intent_record(overlay.records, record)
        )
        try:
            save_update_source_intent_overlay(self._update_source_intent_overlay_file, updated)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not save update-source intent overlay: {exc}") from exc
        return updated

    def clear_update_source_intent(self, unique_id: str) -> UpdateSourceIntentOverlay:
        normalized_unique_id = _require_canonical_unique_id(unique_id)
        overlay = self.load_update_source_intent_overlay()
        updated_records = tuple(
            record
            for record in overlay.records
            if record.normalized_unique_id != normalized_unique_id
        )
        updated = UpdateSourceIntentOverlay(records=updated_records)
        try:
            save_update_source_intent_overlay(self._update_source_intent_overlay_file, updated)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not save update-source intent overlay: {exc}") from exc
        return updated

    def export_backup_bundle(
        self,
        *,
        destination_root_text: str,
        bundle_storage_kind: Literal["directory", "zip"] = "directory",
        artifact_selection: BackupBundleExportSelection | None = None,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        existing_config: AppConfig | None,
    ) -> BackupBundleExportResult:
        destination_text = destination_root_text.strip()
        if bundle_storage_kind not in {"directory", "zip"}:
            raise AppShellError("Backup export format is not supported.")
        if not destination_text:
            if bundle_storage_kind == "zip":
                raise AppShellError("Select a destination .zip path for the backup export first.")
            raise AppShellError("Select a destination folder for the backup export first.")

        selection = artifact_selection or BackupBundleExportSelection()

        destination_path = Path(destination_text).expanduser()
        if bundle_storage_kind == "directory":
            if not destination_path.exists() or not destination_path.is_dir():
                raise AppShellError(
                    f"Backup export destination is not accessible: {destination_path}"
                )
            final_bundle_path = self._allocate_backup_bundle_path(destination_path)
            export_work_root = final_bundle_path
            export_work_root_parent: Path | None = None
        else:
            if destination_path.suffix.casefold() != ".zip":
                destination_path = destination_path.with_suffix(".zip")
            destination_parent = destination_path.parent
            if not destination_parent.exists() or not destination_parent.is_dir():
                raise AppShellError(
                    f"Backup zip export destination is not accessible: {destination_parent}"
                )
            if destination_path.exists():
                raise AppShellError(
                    f"Backup zip export destination already exists: {destination_path}"
                )
            export_work_root_parent = Path(
                tempfile.mkdtemp(prefix="cinderleaf-backup-export-", dir=str(destination_parent))
            )
            export_work_root = self._allocate_backup_bundle_path(export_work_root_parent)
            final_bundle_path = destination_path

        export_config = self._build_validated_operational_config(
            game_path_text=game_path_text,
            mods_dir_text=mods_dir_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
            real_archive_path_text=real_archive_path_text,
            nexus_api_key_text=nexus_api_key_text,
            scan_target=scan_target,
            install_target=install_target,
            existing_config=existing_config,
        )

        real_mods_source = self._resolve_existing_export_source(
            export_config.mods_path,
            field_label="Real Mods directory",
        )
        sandbox_mods_source = self._resolve_existing_export_source(
            export_config.sandbox_mods_path,
            field_label="Sandbox Mods directory",
        )
        real_archive_source = self._resolve_existing_export_source(
            export_config.real_archive_path,
            field_label="Real Mods archive root",
        )
        sandbox_archive_source = self._resolve_existing_export_source(
            export_config.sandbox_archive_path,
            field_label="Sandbox archive root",
        )
        real_profile_catalog_source = self._resolve_existing_export_source(
            self._real_mod_profile_catalog_file,
            field_label="Real Mods profile catalog",
        )
        sandbox_profile_catalog_source = self._resolve_existing_export_source(
            self._sandbox_mod_profile_catalog_file,
            field_label="Sandbox Mods profile catalog",
        )
        stardew_save_root = platform_default_stardew_save_directory()
        stardew_save_source = _BackupBundleSourceResolution(
            path=stardew_save_root,
            missing_status="not_present",
            note=(
                None
                if stardew_save_root.exists()
                else f"No Stardew save folder was found at {stardew_save_root}."
            ),
        )
        real_profile_catalog_item = self._backup_bundle_item_plan(
            key="real_mod_profiles",
            label="Real Mods profile catalog",
            kind="file",
            resolution=real_profile_catalog_source,
            relative_path=Path("manager-state") / self._real_mod_profile_catalog_file.name,
            selected=selection.include_manager_state,
        )
        sandbox_profile_catalog_item = self._backup_bundle_item_plan(
            key="sandbox_mod_profiles",
            label="Sandbox Mods profile catalog",
            kind="file",
            resolution=sandbox_profile_catalog_source,
            relative_path=Path("manager-state") / self._sandbox_mod_profile_catalog_file.name,
            selected=selection.include_manager_state,
        )
        prepared_real_mod_configs = self._prepare_mod_config_snapshot_export_item(
            key="real_mod_configs",
            label="Real Mods config snapshot",
            mods_source=real_mods_source,
            excluded_paths=_non_null_paths((export_config.real_archive_path,)),
            relative_path=Path("mod-config") / "real-mods",
            selected=selection.include_managed_mods,
        )
        prepared_sandbox_mod_configs = self._prepare_mod_config_snapshot_export_item(
            key="sandbox_mod_configs",
            label="Sandbox Mods config snapshot",
            mods_source=sandbox_mods_source,
            excluded_paths=_non_null_paths((export_config.sandbox_archive_path,)),
            relative_path=Path("mod-config") / "sandbox-mods",
            selected=selection.include_managed_mods,
        )
        save_files_item = self._backup_bundle_item_plan(
            key="stardew_save_files",
            label="Stardew save files",
            kind="directory",
            resolution=stardew_save_source,
            relative_path=Path("saves") / "stardew-valley",
            selected=selection.include_save_files,
        )
        temp_snapshot_roots = tuple(
            snapshot.temp_root
            for snapshot in (prepared_real_mod_configs, prepared_sandbox_mod_configs)
            if snapshot.temp_root is not None
        )

        manifest_path = (
            export_work_root / "manifest.json"
            if bundle_storage_kind == "directory"
            else _bundle_zip_member_pseudo_path(final_bundle_path, "manifest.json")
        )
        summary_path = (
            export_work_root / "README.txt"
            if bundle_storage_kind == "directory"
            else _bundle_zip_member_pseudo_path(final_bundle_path, "README.txt")
        )
        created_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        plan = (
            self._backup_bundle_item_plan(
                key="app_state",
                label="App state/config",
                kind="file",
                resolution=_BackupBundleSourceResolution(
                    path=self._state_file,
                    missing_status="not_present",
                    note="Generated from the current export configuration snapshot.",
                ),
                relative_path=Path("manager-state") / self._state_file.name,
                selected=selection.include_manager_state,
            ),
            self._backup_bundle_item_plan(
                key="install_history",
                label="Install history",
                kind="file",
                resolution=_BackupBundleSourceResolution(
                    path=self._install_operation_history_file,
                    missing_status="not_present",
                    note="No install history has been recorded yet.",
                ),
                relative_path=Path("manager-state") / self._install_operation_history_file.name,
                selected=selection.include_manager_state,
            ),
            self._backup_bundle_item_plan(
                key="recovery_history",
                label="Recovery history",
                kind="file",
                resolution=_BackupBundleSourceResolution(
                    path=self._recovery_execution_history_file,
                    missing_status="not_present",
                    note="No recovery history has been recorded yet.",
                ),
                relative_path=Path("manager-state") / self._recovery_execution_history_file.name,
                selected=selection.include_manager_state,
            ),
            self._backup_bundle_item_plan(
                key="update_source_intent_overlay",
                label="Update-source intent overlay",
                kind="file",
                resolution=_BackupBundleSourceResolution(
                    path=self._update_source_intent_overlay_file,
                    missing_status="not_present",
                    note="No persisted update-source intent overlay exists yet.",
                ),
                relative_path=Path("manager-state") / self._update_source_intent_overlay_file.name,
                selected=selection.include_manager_state,
            ),
            self._backup_bundle_item_plan(
                key="real_mods",
                label="Real Mods directory",
                kind="directory",
                resolution=real_mods_source,
                relative_path=Path("mods") / "real-mods",
                selected=selection.include_managed_mods,
            ),
            self._backup_bundle_item_plan(
                key="sandbox_mods",
                label="Sandbox Mods directory",
                kind="directory",
                resolution=sandbox_mods_source,
                relative_path=Path("mods") / "sandbox-mods",
                selected=selection.include_managed_mods,
            ),
            prepared_real_mod_configs.item,
            prepared_sandbox_mod_configs.item,
            self._backup_bundle_item_plan(
                key="real_archive",
                label="Real Mods archive root",
                kind="directory",
                resolution=real_archive_source,
                relative_path=Path("archives") / "real-archive",
                selected=selection.include_archives,
            ),
            self._backup_bundle_item_plan(
                key="sandbox_archive",
                label="Sandbox archive root",
                kind="directory",
                resolution=sandbox_archive_source,
                relative_path=Path("archives") / "sandbox-archive",
                selected=selection.include_archives,
            ),
            real_profile_catalog_item,
            sandbox_profile_catalog_item,
            save_files_item,
        )

        if not any(item.status == "copied" for item in plan):
            raise AppShellError(
                "No selected artifacts are available to export yet. Choose an available artifact group first."
            )

        try:
            export_work_root.mkdir(parents=True, exist_ok=False)
            if selection.include_manager_state:
                save_app_config(
                    export_work_root / "manager-state" / self._state_file.name,
                    export_config,
                )
            for item in plan:
                if item.key == "app_state":
                    continue
                self._copy_backup_bundle_item(bundle_path=export_work_root, item=item)
            summary_text = build_backup_bundle_export_text(
                BackupBundleExportResult(
                    bundle_path=final_bundle_path,
                    manifest_path=manifest_path,
                    summary_path=summary_path,
                    created_at_utc=created_at_utc,
                    items=plan,
                    bundle_storage_kind=bundle_storage_kind,
                )
            )
            write_json_file_atomic(
                export_work_root / "manifest.json",
                self._serialize_backup_bundle_manifest(
                    bundle_path=export_work_root,
                    created_at_utc=created_at_utc,
                    items=plan,
                ),
            )
            write_text_file_atomic(export_work_root / "README.txt", summary_text)
            if bundle_storage_kind == "zip":
                self._create_backup_bundle_zip(
                    source_bundle_path=export_work_root,
                    destination_zip_path=final_bundle_path,
                )
        except (AppStateStoreError, OSError) as exc:
            if bundle_storage_kind == "directory":
                shutil.rmtree(export_work_root, ignore_errors=True)
            else:
                shutil.rmtree(export_work_root_parent, ignore_errors=True)
                if final_bundle_path.exists():
                    final_bundle_path.unlink(missing_ok=True)
            raise AppShellError(f"Could not create backup bundle: {exc}") from exc
        finally:
            for temp_root in temp_snapshot_roots:
                shutil.rmtree(temp_root, ignore_errors=True)
            if bundle_storage_kind == "zip" and export_work_root_parent is not None:
                shutil.rmtree(export_work_root_parent, ignore_errors=True)

        return BackupBundleExportResult(
            bundle_path=final_bundle_path,
            manifest_path=manifest_path,
            summary_path=summary_path,
            created_at_utc=created_at_utc,
            items=plan,
            bundle_storage_kind=bundle_storage_kind,
        )

    def inspect_backup_bundle(
        self,
        *,
        bundle_path_text: str,
    ) -> BackupBundleInspectionResult:
        if not bundle_path_text.strip():
            raise AppShellError("Select a backup bundle first.")
        bundle_path = Path(bundle_path_text.strip()).expanduser()
        if not bundle_path.exists():
            raise AppShellError(f"Backup bundle is not accessible: {bundle_path}")
        if bundle_path.is_dir():
            bundle_storage_kind: Literal["directory", "zip"] = "directory"
            content_root_path = bundle_path
            manifest_path = content_root_path / "manifest.json"
            summary_path = content_root_path / "README.txt"
        elif bundle_path.is_file() and bundle_path.suffix.casefold() == ".zip":
            bundle_storage_kind = "zip"
            manifest_path = _bundle_zip_member_pseudo_path(bundle_path, "manifest.json")
            summary_path = _bundle_zip_member_pseudo_path(bundle_path, "README.txt")
            try:
                prepared_zip = self._prepare_zip_backup_bundle_content(bundle_path)
            except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                return _invalid_backup_bundle_inspection_result(
                    bundle_path=bundle_path,
                    manifest_path=manifest_path,
                    summary_path=summary_path,
                    message="Backup bundle zip is invalid or unreadable.",
                    warnings=(f"Zip bundle could not be opened safely: {exc}",),
                    bundle_storage_kind="zip",
                )
            content_root_path = prepared_zip.content_root_path
            manifest_path = content_root_path / "manifest.json"
            summary_path = content_root_path / "README.txt"
        else:
            raise AppShellError(f"Backup bundle is not accessible: {bundle_path}")

        if not manifest_path.exists() or not manifest_path.is_file():
            return _invalid_backup_bundle_inspection_result(
                bundle_path=bundle_path,
                manifest_path=manifest_path,
                summary_path=summary_path,
                message="Backup bundle is structurally invalid: manifest.json is missing.",
                warnings=("Required manifest file is missing.",),
                bundle_storage_kind=bundle_storage_kind,
            )

        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return _invalid_backup_bundle_inspection_result(
                bundle_path=bundle_path,
                manifest_path=manifest_path,
                summary_path=summary_path,
                message="Backup bundle is structurally invalid: manifest.json is not valid JSON.",
                warnings=(f"Manifest JSON could not be parsed: {exc}",),
                bundle_storage_kind=bundle_storage_kind,
            )
        except OSError as exc:
            raise AppShellError(f"Could not inspect backup bundle: {exc}") from exc

        return _build_backup_bundle_inspection_result(
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            summary_path=summary_path,
            raw_manifest=raw_manifest,
            bundle_storage_kind=bundle_storage_kind,
            content_root_path=content_root_path,
        )

    def plan_restore_import_from_backup_bundle(
        self,
        *,
        bundle_path_text: str,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        existing_config: AppConfig | None,
    ) -> RestoreImportPlanningResult:
        del watched_downloads_path_text
        del secondary_watched_downloads_path_text
        del nexus_api_key_text
        del scan_target
        del install_target

        inspection = self.inspect_backup_bundle(bundle_path_text=bundle_path_text)
        local_targets = self._build_restore_import_planning_local_targets(
            game_path_text=game_path_text,
            mods_dir_text=mods_dir_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            real_archive_path_text=real_archive_path_text,
            existing_config=existing_config,
            inspection=inspection,
        )
        return _build_restore_import_planning_result(
            inspection=inspection,
            local_targets=local_targets,
        )

    def review_restore_import_execution(
        self,
        planning_result: RestoreImportPlanningResult,
    ) -> RestoreImportExecutionReview:
        return _build_restore_import_execution_review(planning_result)

    def execute_restore_import(
        self,
        planning_result: RestoreImportPlanningResult,
        *,
        confirm_execution: bool = False,
    ) -> RestoreImportExecutionResult:
        review = self.review_restore_import_execution(planning_result)
        if not review.allowed:
            raise AppShellError(review.message)
        if review.requires_explicit_confirmation and not confirm_execution:
            raise AppShellError("Explicit confirmation is required before restore/import execution.")

        mod_actions, config_actions, execution_warnings = _build_restore_import_execution_actions(
            planning_result
        )

        archived_target_paths: list[Path] = []
        archived_target_restores: list[tuple[Path, Path]] = []
        restored_mod_paths: list[Path] = []
        restored_config_paths: list[Path] = []
        try:
            for action in mod_actions:
                if action.action_kind == "archive_replace":
                    if (
                        action.archive_root is None
                        or action.archive_destination_path is None
                    ):
                        raise AppShellError(
                            f"Restore/import replace action is missing archive context for {action.destination_path}."
                        )
                    if not action.destination_path.exists() or not action.destination_path.is_dir():
                        raise AppShellError(
                            "Restore/import replace target is no longer available for archive-aware replacement: "
                            f"{action.destination_path}"
                        )
                    _ensure_archive_root_service(action.archive_root)
                    action.destination_path.rename(action.archive_destination_path)
                    archived_target_paths.append(action.archive_destination_path)
                    archived_target_restores.append(
                        (action.archive_destination_path, action.destination_path)
                    )
                elif action.destination_path.exists():
                    raise AppShellError(
                        f"Restore/import target already exists unexpectedly: {action.destination_path}"
                    )
                action.destination_path.parent.mkdir(parents=True, exist_ok=True)
                restored_mod_paths.append(action.destination_path)
                shutil.copytree(action.source_path, action.destination_path)

            for action in config_actions:
                if action.destination_path.exists():
                    raise AppShellError(
                        "Restore/import config target already exists unexpectedly: "
                        f"{action.destination_path}"
                    )
                action.destination_path.parent.mkdir(parents=True, exist_ok=True)
                restored_config_paths.append(action.destination_path)
                shutil.copy2(action.source_path, action.destination_path)
        except (AppShellError, OSError) as exc:
            rollback_warnings = _rollback_restore_import_paths(
                archived_target_restores=tuple(archived_target_restores),
                restored_mod_paths=tuple(restored_mod_paths),
                restored_config_paths=tuple(restored_config_paths),
            )
            message = f"Restore/import execution failed: {exc}"
            if rollback_warnings:
                message += " Rollback also reported issues: " + " | ".join(rollback_warnings)
            raise AppShellError(message) from exc

        return RestoreImportExecutionResult(
            bundle_path=planning_result.bundle_path,
            restored_mod_paths=tuple(restored_mod_paths),
            restored_config_paths=tuple(restored_config_paths),
            restored_mod_count=len(restored_mod_paths),
            restored_config_count=len(restored_config_paths),
            archived_target_paths=tuple(archived_target_paths),
            replaced_mod_count=review.replace_mod_count,
            replaced_config_count=review.replace_config_count,
            covered_config_count=review.covered_config_count,
            skipped_review_entry_count=review.review_entry_count,
            skipped_blocked_entry_count=review.blocked_entry_count,
            deferred_item_count=review.deferred_item_count,
            message=_build_restore_import_execution_summary_message(
                restored_mod_count=len(restored_mod_paths),
                restored_config_count=len(restored_config_paths),
                replaced_mod_count=review.replace_mod_count,
                replaced_config_count=review.replace_config_count,
                covered_config_count=review.covered_config_count,
                review_entry_count=review.review_entry_count,
                blocked_entry_count=review.blocked_entry_count,
                deferred_item_count=review.deferred_item_count,
            ),
            warnings=execution_warnings,
        )

    def inspect_install_recovery_by_operation_id(
        self,
        operation_id: str,
    ) -> InstallRecoveryInspectionResult:
        requested_operation_id = operation_id.strip()
        if not requested_operation_id:
            raise AppShellError("Install operation ID is required.")

        history = self.load_install_operation_history()
        operation = next(
            (
                item
                for item in history.operations
                if item.operation_id is not None and item.operation_id == requested_operation_id
            ),
            None,
        )
        if operation is None:
            raise AppShellError(
                f"Install operation ID not found: {requested_operation_id}"
            )

        recovery_plan = self.derive_install_operation_recovery_plan(operation)
        recovery_review = self.review_install_recovery_execution(recovery_plan)
        linked_recovery_history = tuple(
            record
            for record in self.load_recovery_execution_history().operations
            if record.related_install_operation_id == requested_operation_id
        )
        return InstallRecoveryInspectionResult(
            operation=operation,
            recovery_plan=recovery_plan,
            recovery_review=recovery_review,
            linked_recovery_history=linked_recovery_history,
        )

    def derive_install_operation_recovery_plan(
        self,
        operation: InstallOperationRecord,
    ) -> InstallRecoveryPlan:
        entries = tuple(
            _derive_install_operation_recovery_entry(operation, entry)
            for entry in operation.entries
        )
        warnings = tuple(entry.message for entry in entries if not entry.recoverable)
        recoverable_entry_count = sum(1 for entry in entries if entry.recoverable)
        non_recoverable_entry_count = len(entries) - recoverable_entry_count
        return InstallRecoveryPlan(
            operation=operation,
            entries=entries,
            summary=InstallRecoveryPlanSummary(
                total_recovery_entry_count=len(entries),
                recoverable_entry_count=recoverable_entry_count,
                non_recoverable_entry_count=non_recoverable_entry_count,
                involves_archive_restore=any(
                    entry.action == "restore_from_archive" and entry.recoverable
                    for entry in entries
                ),
                warnings=warnings,
            ),
        )

    def review_install_recovery_execution(
        self,
        plan: InstallRecoveryPlan,
    ) -> InstallRecoveryExecutionReview:
        entries = tuple(_review_install_recovery_entry(entry) for entry in plan.entries)
        executable_entry_count = sum(1 for entry in entries if entry.executable)
        non_executable_entry_count = len(entries) - executable_entry_count
        stale_entry_count = sum(
            1
            for entry in entries
            if entry.decision_code in {"removal_target_missing", "restore_archive_missing"}
        )
        warnings = tuple(entry.message for entry in entries if not entry.executable)
        allowed = non_executable_entry_count == 0
        if allowed:
            message = (
                f"Recovery plan is ready: {executable_entry_count} "
                f"{_entry_count_label(executable_entry_count)} can be executed."
            )
        else:
            message = (
                f"Recovery plan is blocked: {non_executable_entry_count} "
                f"{_entry_count_label(non_executable_entry_count)} cannot be executed safely."
            )
        return InstallRecoveryExecutionReview(
            plan=plan,
            allowed=allowed,
            decision_code=("recovery_ready" if allowed else "recovery_blocked"),
            message=message,
            entries=entries,
            summary=InstallRecoveryExecutionReviewSummary(
                total_entry_count=len(entries),
                executable_entry_count=executable_entry_count,
                non_executable_entry_count=non_executable_entry_count,
                stale_entry_count=stale_entry_count,
                involves_archive_restore=any(
                    review_entry.plan_entry.action == "restore_from_archive"
                    and review_entry.executable
                    for review_entry in entries
                ),
                warnings=warnings,
            ),
        )

    def execute_install_recovery_review(
        self,
        review: InstallRecoveryExecutionReview,
    ) -> InstallRecoveryExecutionResult:
        if not review.allowed:
            self._record_recovery_execution_attempt(
                review=review,
                outcome_status="failed",
                removed_target_paths=tuple(),
                restored_target_paths=tuple(),
                failure_message=review.message,
                critical=False,
            )
            raise AppShellError(review.message)

        removed_target_paths: list[Path] = []
        restored_target_paths: list[Path] = []
        destination_mods_path = review.plan.operation.destination_mods_path
        destination_kind = review.plan.operation.destination_kind
        archive_path = review.plan.operation.archive_path

        try:
            for entry_review in review.entries:
                if not entry_review.executable:
                    raise AppShellError(entry_review.message)

                plan_entry = entry_review.plan_entry
                try:
                    if plan_entry.action == "remove_installed_target":
                        _remove_recovery_target(plan_entry.target_path)
                        removed_target_paths.append(plan_entry.target_path)
                        continue

                    if plan_entry.action == "restore_from_archive":
                        if plan_entry.archive_path is None:
                            raise AppShellError(
                                f"Archive source is missing for restoring {plan_entry.name}."
                            )
                        restored_target = restore_archived_mod_entry(
                            archive_root=archive_path,
                            archived_path=plan_entry.archive_path,
                            destination_mods_root=destination_mods_path,
                            destination_folder_name=plan_entry.target_path.name,
                        )
                        restored_target_paths.append(restored_target)
                        continue
                except ArchiveManagerError as exc:
                    raise AppShellError(f"Recovery execution failed: {exc}") from exc
                except OSError as exc:
                    raise AppShellError(f"Recovery execution failed: {exc}") from exc

                raise AppShellError(
                    f"Recovery execution failed: unsupported action {plan_entry.action!r}."
                )

            try:
                inventory = scan_mods_directory(
                    destination_mods_path,
                    excluded_paths=(archive_path, destination_mods_path / _LEGACY_ARCHIVE_DIRNAME),
                )
            except OSError as exc:
                raise AppShellError(f"Recovery execution scan failed: {exc}") from exc

            result = InstallRecoveryExecutionResult(
                review=review,
                executed_entry_count=len(review.entries),
                removed_target_paths=tuple(removed_target_paths),
                restored_target_paths=tuple(restored_target_paths),
                destination_kind=destination_kind,
                destination_mods_path=destination_mods_path,
                scan_context_path=destination_mods_path,
                inventory=inventory,
            )
        except AppShellError as exc:
            outcome_status = "failed_partial" if (removed_target_paths or restored_target_paths) else "failed"
            self._record_recovery_execution_attempt(
                review=review,
                outcome_status=outcome_status,
                removed_target_paths=tuple(removed_target_paths),
                restored_target_paths=tuple(restored_target_paths),
                failure_message=str(exc),
                critical=bool(removed_target_paths or restored_target_paths),
            )
            raise

        self._record_recovery_execution_attempt(
            review=review,
            outcome_status="completed",
            removed_target_paths=result.removed_target_paths,
            restored_target_paths=result.restored_target_paths,
            failure_message=None,
            critical=True,
        )
        return result

    def build_install_execution_summary(
        self,
        plan: SandboxInstallPlan,
    ) -> InstallExecutionSummary:
        action_order = (INSTALL_NEW, OVERWRITE_WITH_ARCHIVE, BLOCKED)
        action_totals = Counter(entry.action for entry in plan.entries)
        action_counts = tuple(
            InstallExecutionActionCount(action=action, count=action_totals.get(action, 0))
            for action in action_order
        )
        review_warnings = _collect_install_execution_review_warnings(plan)
        requires_explicit_confirmation = (
            plan.destination_kind == INSTALL_TARGET_CONFIGURED_REAL_MODS
        )
        return InstallExecutionSummary(
            destination_kind=plan.destination_kind,
            destination_mods_path=plan.sandbox_mods_path,
            archive_path=plan.sandbox_archive_path,
            total_entry_count=len(plan.entries),
            action_counts=action_counts,
            has_existing_targets_to_replace=any(
                entry.target_exists and entry.action == OVERWRITE_WITH_ARCHIVE
                for entry in plan.entries
            ),
            has_archive_writes=any(entry.archive_path is not None for entry in plan.entries),
            requires_explicit_confirmation=requires_explicit_confirmation,
            review_warnings=review_warnings,
        )

    def review_install_execution(
        self,
        plan: SandboxInstallPlan,
    ) -> InstallExecutionReview:
        summary = self.build_install_execution_summary(plan)
        blocked_count = next(
            (item.count for item in summary.action_counts if item.action == BLOCKED),
            0,
        )

        if blocked_count > 0:
            entry_label = "entry" if blocked_count == 1 else "entries"
            return InstallExecutionReview(
                summary=summary,
                allowed=False,
                requires_explicit_approval=False,
                decision_code="blocked_entries_present",
                message=(
                    f"Install plan is blocked: {blocked_count} {entry_label} cannot be executed. "
                    "Resolve blocked entries before running install."
                ),
            )

        if summary.requires_explicit_confirmation:
            return InstallExecutionReview(
                summary=summary,
                allowed=True,
                requires_explicit_approval=True,
                decision_code="real_approval_required",
                message=_build_real_install_review_message(summary),
            )

        return InstallExecutionReview(
            summary=summary,
            allowed=True,
            requires_explicit_approval=False,
            decision_code="sandbox_allowed",
            message=_build_sandbox_install_review_message(summary),
        )

    def save_mods_directory(
        self,
        mods_dir_text: str,
        existing_config: AppConfig | None,
    ) -> AppConfig:
        mods_path = self._parse_and_validate_mods_path(mods_dir_text)
        game_path = existing_config.game_path if existing_config is not None else mods_path.parent
        config = self._build_config(
            game_path=game_path,
            mods_path=mods_path,
            existing_config=existing_config,
        )

        try:
            save_app_config(state_file=self._state_file, config=config)
        except OSError as exc:
            raise AppShellError(f"Could not save configuration: {exc}") from exc

        return config

    def save_operational_config(
        self,
        *,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        steam_auto_start_enabled: bool = True,
        existing_config: AppConfig | None,
    ) -> AppConfig:
        config = self._build_validated_operational_config(
            game_path_text=game_path_text,
            mods_dir_text=mods_dir_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
            real_archive_path_text=real_archive_path_text,
            nexus_api_key_text=nexus_api_key_text,
            scan_target=scan_target,
            install_target=install_target,
            steam_auto_start_enabled=steam_auto_start_enabled,
            existing_config=existing_config,
        )

        try:
            save_app_config(state_file=self._state_file, config=config)
        except OSError as exc:
            raise AppShellError(f"Could not save configuration: {exc}") from exc

        return config

    def resolve_configured_folder_for_open(
        self,
        *,
        field_label: str,
        path_text: str,
    ) -> Path:
        raw_value = path_text.strip()
        if not raw_value:
            raise AppShellError(f"{field_label} is not configured.")

        path = Path(raw_value).expanduser()
        if not path.exists():
            raise AppShellError(f"{field_label} does not exist: {path}")
        if not path.is_dir():
            raise AppShellError(f"{field_label} is not a folder: {path}")
        return path

    def _build_validated_operational_config(
        self,
        *,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        steam_auto_start_enabled: bool = True,
        existing_config: AppConfig | None,
    ) -> AppConfig:
        if scan_target not in {SCAN_TARGET_CONFIGURED_REAL_MODS, SCAN_TARGET_SANDBOX_MODS}:
            raise AppShellError(f"Unknown scan target: {scan_target}")
        if install_target not in {INSTALL_TARGET_CONFIGURED_REAL_MODS, INSTALL_TARGET_SANDBOX_MODS}:
            raise AppShellError(f"Unknown install target: {install_target}")

        game_path = self._resolve_game_path(game_path_text, existing_config)
        mods_path = self._resolve_mods_path(mods_dir_text, game_path)

        sandbox_mods_path = self._parse_optional_directory(sandbox_mods_path_text)
        sandbox_archive_path: Path | None = None
        if sandbox_mods_path is not None:
            sandbox_archive_path = self._parse_and_validate_sandbox_archive_path(
                sandbox_archive_path_text=sandbox_archive_path_text,
                sandbox_mods_path=sandbox_mods_path,
            )
        elif sandbox_archive_path_text.strip():
            archive_path = Path(sandbox_archive_path_text.strip()).expanduser()
            if archive_path.exists() and not archive_path.is_dir():
                raise AppShellError(f"Sandbox archive path is not a directory: {archive_path}")
            if not archive_path.parent.exists() or not archive_path.parent.is_dir():
                raise AppShellError(
                    f"Sandbox archive parent directory is not accessible: {archive_path.parent}"
                )
            sandbox_archive_path = archive_path

        watched_downloads_path = self._parse_optional_directory(watched_downloads_path_text)
        secondary_watched_downloads_path = self._parse_optional_directory(
            secondary_watched_downloads_path_text
        )
        if secondary_watched_downloads_path == watched_downloads_path:
            secondary_watched_downloads_path = None
        real_archive_path = self._parse_and_validate_archive_path(
            archive_path_text=real_archive_path_text,
            destination_mods_path=mods_path,
            field_label="Real Mods archive path",
            default_archive_dir_name=_DEFAULT_REAL_ARCHIVE_DIRNAME,
        )
        nexus_api_key = self._resolve_nexus_api_key(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
            allow_environment_fallback=False,
        )

        config = self._build_config(
            game_path=game_path,
            mods_path=mods_path,
            existing_config=existing_config,
        )
        config = AppConfig(
            game_path=game_path,
            mods_path=config.mods_path,
            app_data_path=config.app_data_path,
            sandbox_mods_path=sandbox_mods_path,
            sandbox_archive_path=sandbox_archive_path,
            real_archive_path=real_archive_path,
            watched_downloads_path=watched_downloads_path,
            secondary_watched_downloads_path=secondary_watched_downloads_path,
            nexus_api_key=nexus_api_key,
            scan_target=scan_target,
            install_target=install_target,
            steam_auto_start_enabled=steam_auto_start_enabled,
        )
        return config

    def persist_session_config_if_valid(
        self,
        *,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        steam_auto_start_enabled: bool = True,
        existing_config: AppConfig | None,
    ) -> SessionConfigPersistenceResult:
        has_session_input = any(
            field.strip()
            for field in (
                game_path_text,
                mods_dir_text,
                sandbox_mods_path_text,
                sandbox_archive_path_text,
                watched_downloads_path_text,
                secondary_watched_downloads_path_text,
                real_archive_path_text,
                nexus_api_key_text,
            )
        )
        if not has_session_input and existing_config is None:
            return SessionConfigPersistenceResult(
                persisted=False,
                config=None,
                message="No operational configuration is available to persist yet.",
            )

        try:
            config = self.save_operational_config(
                game_path_text=game_path_text,
                mods_dir_text=mods_dir_text,
                sandbox_mods_path_text=sandbox_mods_path_text,
                sandbox_archive_path_text=sandbox_archive_path_text,
                watched_downloads_path_text=watched_downloads_path_text,
                secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
                real_archive_path_text=real_archive_path_text,
                nexus_api_key_text=nexus_api_key_text,
                scan_target=scan_target,
                install_target=install_target,
                steam_auto_start_enabled=steam_auto_start_enabled,
                existing_config=existing_config,
            )
        except AppShellError as exc:
            return SessionConfigPersistenceResult(
                persisted=False,
                config=existing_config,
                message=str(exc),
            )

        return SessionConfigPersistenceResult(persisted=True, config=config)

    def detect_game_environment(self, game_path_text: str) -> GameEnvironmentStatus:
        game_path = self._parse_game_path_text(game_path_text)
        return detect_game_environment_service(game_path)

    def launch_game_vanilla(
        self,
        *,
        game_path_text: str,
        existing_config: AppConfig | None = None,
        steam_auto_start_enabled: bool | None = None,
    ) -> LaunchStartResult:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        steam_prelaunch = self._prepare_steam_prelaunch_for_game_launch(
            enabled=self._resolve_steam_auto_start_enabled(
                requested_value=steam_auto_start_enabled,
                existing_config=existing_config,
            )
        )
        try:
            command = resolve_launch_command(game_path=game_path, mode="vanilla")
            pid = launch_game_process(command)
        except GameLaunchError as exc:
            raise AppShellError(str(exc)) from exc
        return LaunchStartResult(
            mode="vanilla",
            game_path=game_path,
            executable_path=command.executable_path,
            pid=pid,
            steam_prelaunch_state=steam_prelaunch.state,
            steam_prelaunch_message=steam_prelaunch.message,
        )

    def launch_game_smapi(
        self,
        *,
        game_path_text: str,
        configured_mods_path_text: str = "",
        existing_config: AppConfig | None = None,
        steam_auto_start_enabled: bool | None = None,
    ) -> LaunchStartResult:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        command = self._resolve_real_smapi_launch_command(
            game_path=game_path,
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        steam_prelaunch = self._prepare_steam_prelaunch_for_game_launch(
            enabled=self._resolve_steam_auto_start_enabled(
                requested_value=steam_auto_start_enabled,
                existing_config=existing_config,
            )
        )
        try:
            pid = launch_game_process(command)
        except GameLaunchError as exc:
            raise AppShellError(str(exc)) from exc
        return LaunchStartResult(
            mode="smapi",
            game_path=game_path,
            executable_path=command.executable_path,
            pid=pid,
            mods_path_override=_launch_command_mods_override(command),
            steam_prelaunch_state=steam_prelaunch.state,
            steam_prelaunch_message=steam_prelaunch.message,
        )

    def get_sandbox_dev_launch_readiness(
        self,
        *,
        game_path_text: str,
        sandbox_mods_path_text: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> SandboxDevLaunchReadiness:
        try:
            game_path, sandbox_mods_path, command = self._resolve_sandbox_dev_launch_context(
                game_path_text=game_path_text,
                sandbox_mods_path_text=sandbox_mods_path_text,
                configured_mods_path_text=configured_mods_path_text,
                existing_config=existing_config,
            )
        except AppShellError as exc:
            return SandboxDevLaunchReadiness(ready=False, message=str(exc))

        return SandboxDevLaunchReadiness(
            ready=True,
            message=(
                "Ready to launch sandbox dev with SMAPI using the configured sandbox Mods path."
            ),
            game_path=game_path,
            sandbox_mods_path=sandbox_mods_path,
            executable_path=command.executable_path,
        )

    def launch_game_sandbox_dev(
        self,
        *,
        game_path_text: str,
        sandbox_mods_path_text: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None = None,
        steam_auto_start_enabled: bool | None = None,
    ) -> LaunchStartResult:
        game_path, sandbox_mods_path, command = self._resolve_sandbox_dev_launch_context(
            game_path_text=game_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        steam_prelaunch = self._prepare_steam_prelaunch_for_game_launch(
            enabled=self._resolve_steam_auto_start_enabled(
                requested_value=steam_auto_start_enabled,
                existing_config=existing_config,
            )
        )
        try:
            pid = launch_game_process(command)
        except GameLaunchError as exc:
            raise AppShellError(str(exc)) from exc
        return LaunchStartResult(
            mode="sandbox_dev_smapi",
            game_path=game_path,
            executable_path=command.executable_path,
            pid=pid,
            mods_path_override=sandbox_mods_path,
            steam_prelaunch_state=steam_prelaunch.state,
            steam_prelaunch_message=steam_prelaunch.message,
        )

    def cinderleaf_smapi_log_directory(
        self,
        *,
        game_path_text: str,
        context_label: str,
        existing_config: AppConfig | None = None,
    ) -> Path:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        return cinderleaf_smapi_context_directory(
            game_path=game_path,
            context_label=context_label,
        )

    def cinderleaf_smapi_latest_log_path(
        self,
        *,
        game_path_text: str,
        context_label: str,
        existing_config: AppConfig | None = None,
    ) -> Path:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        return cinderleaf_smapi_latest_log_path_service(
            game_path=game_path,
            context_label=context_label,
        )

    def capture_cinderleaf_smapi_context_log(
        self,
        *,
        game_path_text: str,
        context_label: str,
        existing_config: AppConfig | None = None,
    ) -> SmapiContextLogCaptureResult:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        return capture_cinderleaf_context_log_service(
            game_path=game_path,
            context_label=context_label,
        )

    def resolve_cinderleaf_managed_paths(
        self,
        *,
        game_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> CinderleafManagedPaths:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        root = game_path / "Cinderleaf"
        return CinderleafManagedPaths(
            game_path=game_path,
            sandbox_mods_path=root / "Sandbox Mods",
            sandbox_archive_path=root / "Sandbox Archive",
            real_archive_path=root / "Real Mods Archive",
            real_logs_path=root / "Logs" / "Real",
            sandbox_logs_path=root / "Logs" / "Sandbox",
        )

    def prepare_cinderleaf_managed_folder_for_open(
        self,
        *,
        game_path_text: str,
        folder_key: Literal[
            "sandbox_mods",
            "sandbox_archive",
            "real_archive",
            "real_logs",
            "sandbox_logs",
        ],
        existing_config: AppConfig | None = None,
    ) -> Path:
        managed_paths = self.resolve_cinderleaf_managed_paths(
            game_path_text=game_path_text,
            existing_config=existing_config,
        )
        target_path = {
            "sandbox_mods": managed_paths.sandbox_mods_path,
            "sandbox_archive": managed_paths.sandbox_archive_path,
            "real_archive": managed_paths.real_archive_path,
            "real_logs": managed_paths.real_logs_path,
            "sandbox_logs": managed_paths.sandbox_logs_path,
        }[folder_key]
        try:
            target_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AppShellError(
                f"Could not prepare managed folder for opening: {target_path} ({exc})"
            ) from exc
        if not target_path.exists() or not target_path.is_dir():
            raise AppShellError(f"Managed folder is not accessible: {target_path}")
        return target_path

    def migrate_cinderleaf_managed_folders(
        self,
        *,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        real_archive_path_text: str = "",
        nexus_api_key_text: str = "",
        scan_target: ScanTargetKind,
        install_target: InstallTargetKind = INSTALL_TARGET_SANDBOX_MODS,
        steam_auto_start_enabled: bool = True,
        existing_config: AppConfig | None,
    ) -> CinderleafManagedMigrationResult:
        managed_paths = self.resolve_cinderleaf_managed_paths(
            game_path_text=game_path_text,
            existing_config=existing_config,
        )
        resolved_game_path = managed_paths.game_path
        resolved_mods_path = self._resolve_mods_path(mods_dir_text, resolved_game_path)

        path_specs = (
            (
                "sandbox_mods",
                "Sandbox Mods",
                self._effective_optional_path_text(
                    sandbox_mods_path_text,
                    existing_config.sandbox_mods_path if existing_config is not None else None,
                ),
                managed_paths.sandbox_mods_path,
            ),
            (
                "sandbox_archive",
                "Sandbox Archive",
                self._effective_optional_path_text(
                    sandbox_archive_path_text,
                    existing_config.sandbox_archive_path if existing_config is not None else None,
                ),
                managed_paths.sandbox_archive_path,
            ),
            (
                "real_archive",
                "Real Mods Archive",
                self._effective_optional_path_text(
                    real_archive_path_text,
                    existing_config.real_archive_path if existing_config is not None else None,
                ),
                managed_paths.real_archive_path,
            ),
        )

        entries: list[CinderleafManagedMigrationEntry] = []
        planned_moves: list[tuple[str, str, Path, Path]] = []
        blocked_entries: list[CinderleafManagedMigrationEntry] = []

        for key, label, source_text, target_path in path_specs:
            source_path = Path(source_text).expanduser() if source_text else None
            if source_path is None:
                entries.append(
                    CinderleafManagedMigrationEntry(
                        key=key,
                        label=label,
                        source_path=None,
                        target_path=target_path,
                        outcome="skipped",
                        detail="Not configured, so there is nothing to migrate.",
                    )
                )
                continue

            if source_path.resolve(strict=False) == target_path.resolve(strict=False):
                entries.append(
                    CinderleafManagedMigrationEntry(
                        key=key,
                        label=label,
                        source_path=source_path,
                        target_path=target_path,
                        outcome="skipped",
                        detail="Already using the Cinderleaf-managed path.",
                    )
                )
                continue

            if not source_path.exists():
                entries.append(
                    CinderleafManagedMigrationEntry(
                        key=key,
                        label=label,
                        source_path=source_path,
                        target_path=target_path,
                        outcome="skipped",
                        detail="Configured source folder does not exist, so migration was skipped.",
                    )
                )
                continue

            if not source_path.is_dir():
                blocked_entry = CinderleafManagedMigrationEntry(
                    key=key,
                    label=label,
                    source_path=source_path,
                    target_path=target_path,
                    outcome="blocked",
                    detail="Configured source path is not a folder.",
                )
                entries.append(blocked_entry)
                blocked_entries.append(blocked_entry)
                continue

            if _is_path_within_or_equal(target_path, source_path) or _is_path_within_or_equal(
                source_path,
                target_path,
            ):
                blocked_entry = CinderleafManagedMigrationEntry(
                    key=key,
                    label=label,
                    source_path=source_path,
                    target_path=target_path,
                    outcome="blocked",
                    detail="Source and target overlap, so migration was not started.",
                )
                entries.append(blocked_entry)
                blocked_entries.append(blocked_entry)
                continue

            if target_path.exists():
                blocked_entry = CinderleafManagedMigrationEntry(
                    key=key,
                    label=label,
                    source_path=source_path,
                    target_path=target_path,
                    outcome="blocked",
                    detail="Target folder already exists, so migration was not started.",
                )
                entries.append(blocked_entry)
                blocked_entries.append(blocked_entry)
                continue

            planned_moves.append((key, label, source_path, target_path))

        if blocked_entries:
            return CinderleafManagedMigrationResult(
                config=existing_config,
                managed_paths=managed_paths,
                entries=tuple(entries),
                message="Migration did not start because one or more target folders need attention first.",
            )

        if not planned_moves:
            return CinderleafManagedMigrationResult(
                config=existing_config,
                managed_paths=managed_paths,
                entries=tuple(entries),
                message="No configured Cinderleaf-managed folders needed migration.",
            )

        created_targets: list[Path] = []
        migrated_entries_by_key: dict[str, CinderleafManagedMigrationEntry] = {}
        try:
            for key, label, source_path, target_path in planned_moves:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_path, target_path)
                created_targets.append(target_path)
                if not self._copied_directory_matches(source_path, target_path):
                    raise AppShellError(
                        f"Migration verification failed for {label}: {source_path} -> {target_path}"
                    )
                migrated_entries_by_key[key] = CinderleafManagedMigrationEntry(
                    key=key,
                    label=label,
                    source_path=source_path,
                    target_path=target_path,
                    outcome="migrated",
                    detail=f"Copied into {target_path} and verified before config update.",
                )

            effective_game_path_text = self._effective_required_path_text(
                game_path_text,
                resolved_game_path,
            )
            effective_mods_path_text = self._effective_required_path_text(
                mods_dir_text,
                resolved_mods_path,
            )
            migrated_config = self.save_operational_config(
                game_path_text=effective_game_path_text,
                mods_dir_text=effective_mods_path_text,
                sandbox_mods_path_text=(
                    str(managed_paths.sandbox_mods_path)
                    if "sandbox_mods" in migrated_entries_by_key
                    else self._effective_optional_path_text(
                        sandbox_mods_path_text,
                        existing_config.sandbox_mods_path
                        if existing_config is not None
                        else None,
                    )
                ),
                sandbox_archive_path_text=(
                    str(managed_paths.sandbox_archive_path)
                    if "sandbox_archive" in migrated_entries_by_key
                    else self._effective_optional_path_text(
                        sandbox_archive_path_text,
                        existing_config.sandbox_archive_path
                        if existing_config is not None
                        else None,
                    )
                ),
                watched_downloads_path_text=self._effective_optional_path_text(
                    watched_downloads_path_text,
                    existing_config.watched_downloads_path if existing_config is not None else None,
                ),
                secondary_watched_downloads_path_text=self._effective_optional_path_text(
                    secondary_watched_downloads_path_text,
                    existing_config.secondary_watched_downloads_path
                    if existing_config is not None
                    else None,
                ),
                real_archive_path_text=(
                    str(managed_paths.real_archive_path)
                    if "real_archive" in migrated_entries_by_key
                    else self._effective_optional_path_text(
                        real_archive_path_text,
                        existing_config.real_archive_path if existing_config is not None else None,
                    )
                ),
                nexus_api_key_text=nexus_api_key_text,
                scan_target=scan_target,
                install_target=install_target,
                steam_auto_start_enabled=steam_auto_start_enabled,
                existing_config=existing_config,
            )
        except Exception:
            for target_path in reversed(created_targets):
                if target_path.exists():
                    shutil.rmtree(target_path, ignore_errors=True)
            raise

        cleanup_warnings: list[str] = []
        existing_entries_by_key = {entry.key: entry for entry in entries}
        final_entries: list[CinderleafManagedMigrationEntry] = []
        for key, label, _source_text, _target_path in path_specs:
            entry = migrated_entries_by_key.get(key) or existing_entries_by_key.get(key)
            if entry is not None:
                final_entries.append(entry)
        for key, label, source_path, target_path in planned_moves:
            if key not in migrated_entries_by_key:
                continue
            try:
                shutil.rmtree(source_path)
            except OSError as exc:
                cleanup_warnings.append(
                    f"{label}: copied and config updated, but old source folder could not be removed ({exc})."
                )

        message = (
            f"Moved {len(migrated_entries_by_key)} Cinderleaf-managed folder(s) under {managed_paths.game_path / 'Cinderleaf'}."
        )
        if cleanup_warnings:
            message += " Old source cleanup needs manual follow-up for at least one folder."
        return CinderleafManagedMigrationResult(
            config=migrated_config,
            managed_paths=managed_paths,
            entries=tuple(final_entries),
            message=message,
            cleanup_warnings=tuple(cleanup_warnings),
        )

    def _resolve_steam_auto_start_enabled(
        self,
        *,
        requested_value: bool | None,
        existing_config: AppConfig | None,
    ) -> bool:
        if requested_value is not None:
            return requested_value
        if existing_config is not None:
            return existing_config.steam_auto_start_enabled
        return True

    def _prepare_steam_prelaunch_for_game_launch(self, *, enabled: bool) -> SteamPrelaunchResult:
        if not enabled:
            return SteamPrelaunchResult(
                state="disabled",
                message=(
                    "Steam auto-start assistance is off; game launch continued without Steam "
                    "prelaunch."
                ),
            )
        steam_running = self._detect_steam_running_best_effort()
        if steam_running is True:
            return SteamPrelaunchResult(
                state="already_running",
                message="Steam was already running.",
            )
        if steam_running is None:
            return SteamPrelaunchResult(
                state="state_unknown",
                message="Steam running status could not be confirmed; game launch continued anyway.",
            )
        try:
            self._attempt_steam_start_best_effort()
        except OSError as exc:
            return SteamPrelaunchResult(
                state="start_failed",
                message=(
                    "Steam was not running; start was attempted but could not be completed "
                    f"({exc}). Game launch continued anyway."
                ),
            )
        return SteamPrelaunchResult(
            state="start_attempted",
            message="Steam was not running; start was attempted and game launch continued anyway.",
        )

    def _detect_steam_running_best_effort(self) -> bool | None:
        if os.name != "nt":
            return None
        try:
            completed = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    "IMAGENAME eq steam.exe",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        stdout = completed.stdout.casefold()
        if "steam.exe" in stdout:
            return True
        return False

    def is_process_running(self, pid: int) -> bool | None:
        return self._is_process_running_best_effort(pid)

    def _attempt_steam_start_best_effort(self) -> None:
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise OSError("automatic Steam start is unavailable on this platform")
        os.startfile("steam://open/main")

    @staticmethod
    def _is_process_running_best_effort(pid: int) -> bool | None:
        if os.name != "nt":
            return None
        try:
            completed = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"PID eq {pid}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        stdout = completed.stdout.casefold()
        if f'"{pid}"' in stdout:
            return True
        if "no tasks are running" in stdout or "no instance running" in stdout:
            return False
        return False

    def get_sandbox_mods_sync_readiness(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None = None,
    ) -> SandboxModsSyncReadiness:
        try:
            real_mods_path, sandbox_mods_path, source_paths = self._resolve_sandbox_mod_sync_context(
                configured_mods_path_text=configured_mods_path_text,
                sandbox_mods_path_text=sandbox_mods_path_text,
                selected_mod_folder_paths_text=selected_mod_folder_paths_text,
                existing_config=existing_config,
            )
        except AppShellError as exc:
            return SandboxModsSyncReadiness(ready=False, message=str(exc))

        return SandboxModsSyncReadiness(
            ready=True,
            message=(
                f"Ready to sync {len(source_paths)} selected mod(s) "
                "from real Mods into sandbox Mods."
            ),
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            selected_count=len(source_paths),
        )

    def sync_installed_mods_to_sandbox(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None = None,
    ) -> SandboxModsSyncResult:
        real_mods_path, sandbox_mods_path, source_paths = self._resolve_sandbox_mod_sync_context(
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            selected_mod_folder_paths_text=selected_mod_folder_paths_text,
            existing_config=existing_config,
        )
        synced_target_paths: list[Path] = []
        for source_path in source_paths:
            target_path = sandbox_mods_path / source_path.name
            shutil.copytree(source_path, target_path)
            synced_target_paths.append(target_path)

        return SandboxModsSyncResult(
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            source_mod_paths=source_paths,
            synced_target_paths=tuple(synced_target_paths),
        )

    def set_sandbox_mod_enabled_state(
        self,
        *,
        sandbox_mods_path_text: str,
        mod_folder_path_text: str,
        enabled: bool,
        profile_id: str | None = None,
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> ScanResult:
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required before toggling sandbox mods.")
        sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)
        catalog = self.load_sandbox_mod_profiles()
        requested_profile_id = (
            profile_id.strip() if isinstance(profile_id, str) and profile_id.strip() else None
        )
        profile_root, updated_catalog, profile = self._resolve_selected_sandbox_profile_path(
            catalog=catalog,
            sandbox_mods_path=sandbox_mods_path,
            requested_profile_id=requested_profile_id,
        )
        if updated_catalog != catalog:
            self._save_normalized_sandbox_profile_catalog(updated_catalog)
        if profile.is_default:
            raise AppShellError(
                "Default sandbox profile mirrors the canonical sandbox library. "
                "Create or select a custom profile to change enabled mods."
            )

        mod_folder_path = Path(os.path.abspath(os.path.normpath(str(Path(mod_folder_path_text).expanduser()))))
        profile_inventory = self._scan_sandbox_inventory_for_profiles(
            sandbox_mods_path=profile_root,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        canonical_inventory = self._scan_sandbox_inventory_for_profiles(
            sandbox_mods_path=sandbox_mods_path,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        entry_state = _profile_entry_state_for_mod(
            inventory=profile_inventory,
            root=profile_root,
            mod_folder_path=mod_folder_path,
        ) or _profile_entry_state_for_mod(
            inventory=canonical_inventory,
            root=sandbox_mods_path,
            mod_folder_path=mod_folder_path,
        )
        if entry_state is None:
            raise AppShellError("Only top-level sandbox profile entries can be toggled right now.")
        folder_name = entry_state.folder_name
        canonical_mod_path = sandbox_mods_path / folder_name
        if not canonical_mod_path.exists():
            raise AppShellError(
                "Sandbox profile toggle is blocked because the canonical mod folder is missing: "
                f"{canonical_mod_path}"
            )

        profile_mod_path = profile_root / folder_name
        performed_action: Literal["created", "removed"] | None = None
        try:
            if enabled:
                if profile_mod_path.exists():
                    raise AppShellError(f"Sandbox mod is already enabled in profile: {folder_name}")
                _create_directory_link(profile_mod_path, canonical_mod_path)
                performed_action = "created"
            else:
                if not profile_mod_path.exists():
                    raise AppShellError(
                        f"Sandbox mod is already disabled in profile: {folder_name}"
                    )
                _remove_directory_link(profile_mod_path)
                performed_action = "removed"

            scan_result, rescan_catalog, _ = self._scan_selected_sandbox_profile(
                sandbox_mods_path=sandbox_mods_path,
                sandbox_archive_path_text=sandbox_archive_path_text,
                existing_config=existing_config,
                catalog=updated_catalog,
                requested_profile_id=profile.profile_id,
            )
        except (OSError, AppShellError) as exc:
            rollback_error: OSError | None = None
            try:
                if performed_action == "created" and profile_mod_path.exists():
                    _remove_directory_link(profile_mod_path)
                elif performed_action == "removed" and not profile_mod_path.exists():
                    _create_directory_link(profile_mod_path, canonical_mod_path)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
            message = f"Could not {'enable' if enabled else 'disable'} sandbox profile mod: {exc}"
            if rollback_error is not None:
                message += f" Rollback also failed: {rollback_error}"
            raise AppShellError(message) from exc

        if rescan_catalog != updated_catalog:
            self._save_normalized_sandbox_profile_catalog(rescan_catalog)
        return scan_result

    def set_real_mod_enabled_state(
        self,
        *,
        configured_mods_path_text: str,
        mod_folder_path_text: str,
        enabled: bool,
        profile_id: str | None = None,
        existing_config: AppConfig | None = None,
    ) -> ScanResult:
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            raise AppShellError("Configured real Mods directory is required before toggling real profile mods.")
        catalog = self.load_real_mod_profiles()
        requested_profile_id = (
            profile_id.strip() if isinstance(profile_id, str) and profile_id.strip() else None
        )
        profile_root, updated_catalog, profile = self._resolve_selected_real_profile_path(
            catalog=catalog,
            real_mods_path=real_mods_path,
            requested_profile_id=requested_profile_id,
        )
        if updated_catalog != catalog:
            self._save_normalized_real_profile_catalog(updated_catalog)
        if profile.is_default:
            raise AppShellError(
                "Default real profile mirrors the canonical real Mods library. "
                "Create or select a custom profile to change enabled mods."
            )

        mod_folder_path = Path(os.path.abspath(os.path.normpath(str(Path(mod_folder_path_text).expanduser()))))
        profile_inventory = self._scan_real_inventory_for_profiles(
            real_mods_path=profile_root,
            existing_config=existing_config,
        )
        canonical_inventory = self._scan_real_inventory_for_profiles(
            real_mods_path=real_mods_path,
            existing_config=existing_config,
        )
        entry_state = _profile_entry_state_for_mod(
            inventory=profile_inventory,
            root=profile_root,
            mod_folder_path=mod_folder_path,
        ) or _profile_entry_state_for_mod(
            inventory=canonical_inventory,
            root=real_mods_path,
            mod_folder_path=mod_folder_path,
        )
        if entry_state is None:
            raise AppShellError("Only top-level real profile entries can be toggled right now.")

        folder_name = entry_state.folder_name
        canonical_mod_path = real_mods_path / folder_name
        if not canonical_mod_path.exists():
            raise AppShellError(
                "Real profile toggle is blocked because the canonical mod folder is missing: "
                f"{canonical_mod_path}"
            )

        profile_mod_path = profile_root / folder_name
        performed_action: str | None = None
        try:
            if enabled:
                if profile_mod_path.exists():
                    raise AppShellError(f"Real mod is already enabled in profile: {folder_name}")
                _create_directory_link(profile_mod_path, canonical_mod_path)
                performed_action = "created"
            else:
                if not profile_mod_path.exists():
                    raise AppShellError(f"Real mod is already disabled in profile: {folder_name}")
                _remove_directory_link(profile_mod_path)
                performed_action = "removed"

            scan_result, rescan_catalog, _ = self._scan_selected_real_profile(
                real_mods_path=real_mods_path,
                existing_config=existing_config,
                catalog=updated_catalog,
                requested_profile_id=profile.profile_id,
            )
        except (OSError, AppShellError) as exc:
            rollback_error: OSError | None = None
            try:
                if performed_action == "created" and profile_mod_path.exists():
                    _remove_directory_link(profile_mod_path)
                elif performed_action == "removed" and not profile_mod_path.exists():
                    _create_directory_link(profile_mod_path, canonical_mod_path)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
            message = f"Could not {'enable' if enabled else 'disable'} real profile mod: {exc}"
            if rollback_error is not None:
                message += f" Rollback also failed: {rollback_error}"
            raise AppShellError(message) from exc

        if rescan_catalog != updated_catalog:
            self._save_normalized_real_profile_catalog(rescan_catalog)
        return scan_result

    def load_sandbox_mod_profiles(self) -> SandboxModProfileCatalog:
        try:
            catalog = load_sandbox_mod_profile_catalog(self._sandbox_mod_profile_catalog_file)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not load sandbox mod profiles: {exc}") from exc
        normalized_catalog = _normalize_sandbox_mod_profile_catalog(catalog)
        if normalized_catalog != catalog:
            try:
                save_sandbox_mod_profile_catalog(
                    self._sandbox_mod_profile_catalog_file,
                    normalized_catalog,
                )
            except AppStateStoreError as exc:
                raise AppShellError(f"Could not normalize sandbox mod profiles: {exc}") from exc
        return normalized_catalog

    def create_sandbox_mod_profile(
        self,
        *,
        name: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxModProfileCreateResult:
        profile_name = _normalize_sandbox_profile_name(name)
        if profile_name.casefold() == DEFAULT_SANDBOX_PROFILE_NAME.casefold():
            raise AppShellError(
                f"'{DEFAULT_SANDBOX_PROFILE_NAME}' is reserved for the canonical sandbox library."
            )
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required before creating profiles.")
        sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)

        catalog = self.load_sandbox_mod_profiles()
        if any(profile.name.casefold() == profile_name.casefold() for profile in catalog.profiles):
            raise AppShellError(f"A sandbox profile named '{profile_name}' already exists.")

        profile = SandboxModProfile(
            profile_id=uuid4().hex,
            name=profile_name,
            storage_dir_name=uuid4().hex,
        )
        try:
            linked_mod_count = self._materialize_profile_from_canonical_library(
                profile=profile,
                sandbox_mods_path=sandbox_mods_path,
            )
        except OSError as exc:
            raise AppShellError(f"Could not create sandbox profile: {exc}") from exc

        updated_catalog = SandboxModProfileCatalog(
            profiles=_upsert_sandbox_mod_profile(catalog.profiles, profile),
            active_profile_id=profile.profile_id,
        )
        try:
            save_sandbox_mod_profile_catalog(
                self._sandbox_mod_profile_catalog_file,
                updated_catalog,
            )
        except AppStateStoreError as exc:
            self._remove_materialized_profile_root(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            )
            raise AppShellError(f"Could not save sandbox mod profiles: {exc}") from exc

        scan_result, _, _ = self._scan_selected_sandbox_profile(
            sandbox_mods_path=sandbox_mods_path,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
            catalog=updated_catalog,
            requested_profile_id=profile.profile_id,
        )
        return SandboxModProfileCreateResult(
            profile=profile,
            profiles=updated_catalog,
            scan_result=scan_result,
            linked_mod_count=linked_mod_count,
        )

    def select_sandbox_mod_profile(
        self,
        *,
        profile_id: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxModProfileSelectResult:
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required before selecting profiles.")
        sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)
        catalog = self.load_sandbox_mod_profiles()
        scan_result, updated_catalog, profile = self._scan_selected_sandbox_profile(
            sandbox_mods_path=sandbox_mods_path,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
            catalog=catalog,
            requested_profile_id=profile_id,
        )
        if updated_catalog != catalog:
            try:
                save_sandbox_mod_profile_catalog(
                    self._sandbox_mod_profile_catalog_file,
                    updated_catalog,
                )
            except AppStateStoreError as exc:
                raise AppShellError(f"Could not update sandbox profile selection: {exc}") from exc
        return SandboxModProfileSelectResult(
            profile=profile,
            profiles=updated_catalog,
            scan_result=scan_result,
        )

    def delete_sandbox_mod_profile(
        self,
        *,
        profile_id: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxModProfileDeleteResult:
        requested_profile_id = profile_id.strip()
        if not requested_profile_id:
            raise AppShellError("Select a sandbox profile first.")

        existing_profiles = self.load_sandbox_mod_profiles()
        profile = next(
            (
                candidate
                for candidate in existing_profiles.profiles
                if candidate.profile_id == requested_profile_id
            ),
            None,
        )
        if profile is None:
            raise AppShellError("Selected sandbox profile no longer exists.")
        if profile.is_default:
            raise AppShellError("Default sandbox profile cannot be deleted.")

        updated_profiles = SandboxModProfileCatalog(
            profiles=tuple(
                candidate
                for candidate in existing_profiles.profiles
                if candidate.profile_id != requested_profile_id
            ),
            active_profile_id=(
                DEFAULT_SANDBOX_PROFILE_ID
                if existing_profiles.active_profile_id == requested_profile_id
                else existing_profiles.active_profile_id
            ),
        )
        try:
            save_sandbox_mod_profile_catalog(
                self._sandbox_mod_profile_catalog_file,
                updated_profiles,
            )
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not delete sandbox mod profile: {exc}") from exc

        scan_result: ScanResult | None = None
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is not None:
            self._remove_materialized_profile_root(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            )

        if sandbox_mods_path is not None:
            sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)
            scan_result, updated_profiles, _ = self._scan_selected_sandbox_profile(
                sandbox_mods_path=sandbox_mods_path,
                sandbox_archive_path_text=sandbox_archive_path_text,
                existing_config=existing_config,
                catalog=updated_profiles,
                requested_profile_id=updated_profiles.active_profile_id or DEFAULT_SANDBOX_PROFILE_ID,
            )
            try:
                save_sandbox_mod_profile_catalog(
                    self._sandbox_mod_profile_catalog_file,
                    updated_profiles,
                )
            except AppStateStoreError as exc:
                raise AppShellError(
                    f"Sandbox profile was deleted, but the fallback selection could not be saved: {exc}"
                ) from exc

        return SandboxModProfileDeleteResult(
            profile=profile,
            profiles=updated_profiles,
            scan_result=scan_result,
        )

    def load_real_mod_profiles(self) -> SandboxModProfileCatalog:
        try:
            catalog = load_real_mod_profile_catalog(self._real_mod_profile_catalog_file)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not load real mod profiles: {exc}") from exc
        normalized_catalog = _normalize_real_mod_profile_catalog(catalog)
        if normalized_catalog != catalog:
            try:
                save_real_mod_profile_catalog(
                    self._real_mod_profile_catalog_file,
                    normalized_catalog,
                )
            except AppStateStoreError as exc:
                raise AppShellError(f"Could not normalize real mod profiles: {exc}") from exc
        return normalized_catalog

    def create_real_mod_profile(
        self,
        *,
        name: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> RealModProfileCreateResult:
        profile_name = _normalize_sandbox_profile_name(name)
        if profile_name.casefold() == DEFAULT_REAL_PROFILE_NAME.casefold():
            raise AppShellError(
                f"'{DEFAULT_REAL_PROFILE_NAME}' is reserved for the canonical real Mods library."
            )
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            raise AppShellError("Configured real Mods directory is required before creating profiles.")

        catalog = self.load_real_mod_profiles()
        if any(profile.name.casefold() == profile_name.casefold() for profile in catalog.profiles):
            raise AppShellError(f"A real profile named '{profile_name}' already exists.")

        profile = SandboxModProfile(
            profile_id=uuid4().hex,
            name=profile_name,
            storage_dir_name=uuid4().hex,
        )
        try:
            linked_mod_count = self._materialize_real_profile_from_canonical_library(
                profile=profile,
                real_mods_path=real_mods_path,
            )
        except OSError as exc:
            raise AppShellError(f"Could not create real profile: {exc}") from exc

        updated_catalog = SandboxModProfileCatalog(
            profiles=_upsert_sandbox_mod_profile(catalog.profiles, profile),
            active_profile_id=profile.profile_id,
        )
        try:
            save_real_mod_profile_catalog(
                self._real_mod_profile_catalog_file,
                updated_catalog,
            )
        except AppStateStoreError as exc:
            self._remove_materialized_real_profile_root(
                profile,
                real_mods_path=real_mods_path,
            )
            raise AppShellError(f"Could not save real mod profiles: {exc}") from exc

        scan_result, _, _ = self._scan_selected_real_profile(
            real_mods_path=real_mods_path,
            existing_config=existing_config,
            catalog=updated_catalog,
            requested_profile_id=profile.profile_id,
        )
        return RealModProfileCreateResult(
            profile=profile,
            profiles=updated_catalog,
            scan_result=scan_result,
            linked_mod_count=linked_mod_count,
        )

    def select_real_mod_profile(
        self,
        *,
        profile_id: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> RealModProfileSelectResult:
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            raise AppShellError("Configured real Mods directory is required before selecting profiles.")
        catalog = self.load_real_mod_profiles()
        scan_result, updated_catalog, profile = self._scan_selected_real_profile(
            real_mods_path=real_mods_path,
            existing_config=existing_config,
            catalog=catalog,
            requested_profile_id=profile_id,
        )
        if updated_catalog != catalog:
            try:
                save_real_mod_profile_catalog(
                    self._real_mod_profile_catalog_file,
                    updated_catalog,
                )
            except AppStateStoreError as exc:
                raise AppShellError(f"Could not update real profile selection: {exc}") from exc
        return RealModProfileSelectResult(
            profile=profile,
            profiles=updated_catalog,
            scan_result=scan_result,
        )

    def delete_real_mod_profile(
        self,
        *,
        profile_id: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> RealModProfileDeleteResult:
        requested_profile_id = profile_id.strip()
        if not requested_profile_id:
            raise AppShellError("Select a real profile first.")

        existing_profiles = self.load_real_mod_profiles()
        profile = next(
            (
                candidate
                for candidate in existing_profiles.profiles
                if candidate.profile_id == requested_profile_id
            ),
            None,
        )
        if profile is None:
            raise AppShellError("Selected real profile no longer exists.")
        if profile.is_default:
            raise AppShellError("Default real profile cannot be deleted.")

        updated_profiles = SandboxModProfileCatalog(
            profiles=tuple(
                candidate
                for candidate in existing_profiles.profiles
                if candidate.profile_id != requested_profile_id
            ),
            active_profile_id=(
                DEFAULT_REAL_PROFILE_ID
                if existing_profiles.active_profile_id == requested_profile_id
                else existing_profiles.active_profile_id
            ),
        )
        try:
            save_real_mod_profile_catalog(
                self._real_mod_profile_catalog_file,
                updated_profiles,
            )
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not delete real mod profile: {exc}") from exc

        scan_result: ScanResult | None = None
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is not None:
            self._remove_materialized_real_profile_root(
                profile,
                real_mods_path=real_mods_path,
            )
            scan_result, updated_profiles, _ = self._scan_selected_real_profile(
                real_mods_path=real_mods_path,
                existing_config=existing_config,
                catalog=updated_profiles,
                requested_profile_id=updated_profiles.active_profile_id or DEFAULT_REAL_PROFILE_ID,
            )
            try:
                save_real_mod_profile_catalog(
                    self._real_mod_profile_catalog_file,
                    updated_profiles,
                )
            except AppStateStoreError as exc:
                raise AppShellError(
                    f"Real profile was deleted, but the fallback selection could not be saved: {exc}"
                ) from exc

        return RealModProfileDeleteResult(
            profile=profile,
            profiles=updated_profiles,
            scan_result=scan_result,
        )

    def _scan_sandbox_inventory_for_profiles(
        self,
        *,
        sandbox_mods_path: Path,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None,
    ) -> ModsInventory:
        excluded_paths = self._resolve_scan_excluded_paths(
            scan_target=SCAN_TARGET_SANDBOX_MODS,
            scan_path=sandbox_mods_path,
            configured_archive_text=sandbox_archive_path_text,
            configured_archive_fallback=(
                existing_config.sandbox_archive_path if existing_config is not None else None
            ),
        )
        try:
            return scan_mods_directory(sandbox_mods_path, excluded_paths=excluded_paths)
        except OSError as exc:
            raise AppShellError(f"Could not scan sandbox Mods for profiles: {exc}") from exc

    def _scan_real_inventory_for_profiles(
        self,
        *,
        real_mods_path: Path,
        existing_config: AppConfig | None,
    ) -> ModsInventory:
        excluded_paths = self._resolve_scan_excluded_paths(
            scan_target=SCAN_TARGET_CONFIGURED_REAL_MODS,
            scan_path=real_mods_path,
            configured_archive_text="",
            configured_archive_fallback=(
                existing_config.real_archive_path if existing_config is not None else None
            ),
        )
        try:
            return scan_mods_directory(real_mods_path, excluded_paths=excluded_paths)
        except OSError as exc:
            raise AppShellError(f"Could not scan real Mods for profiles: {exc}") from exc

    def _scan_selected_sandbox_profile(
        self,
        *,
        sandbox_mods_path: Path,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None,
        catalog: SandboxModProfileCatalog,
        requested_profile_id: str | None = None,
    ) -> tuple[ScanResult, SandboxModProfileCatalog, SandboxModProfile]:
        updated_catalog = catalog
        selected_profile_id = requested_profile_id or catalog.active_profile_id or DEFAULT_SANDBOX_PROFILE_ID
        profile = next(
            (candidate for candidate in catalog.profiles if candidate.profile_id == selected_profile_id),
            None,
        )
        if profile is None:
            raise AppShellError("Selected sandbox profile no longer exists.")

        if updated_catalog.active_profile_id != profile.profile_id:
            updated_catalog = replace(updated_catalog, active_profile_id=profile.profile_id)

        if profile.is_default:
            inventory = self._scan_sandbox_inventory_for_profiles(
                sandbox_mods_path=sandbox_mods_path,
                sandbox_archive_path_text=sandbox_archive_path_text,
                existing_config=existing_config,
            )
            return (
                ScanResult(
                    target_kind=SCAN_TARGET_SANDBOX_MODS,
                    scan_path=sandbox_mods_path,
                    inventory=inventory,
                ),
                updated_catalog,
                profile,
            )

        profile, updated_catalog = self._materialize_sandbox_profile_if_needed(
            catalog=updated_catalog,
            profile=profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        profile_root = self._sandbox_mod_profile_mods_path(
            profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        profile_inventory = self._scan_sandbox_inventory_for_profiles(
            sandbox_mods_path=profile_root,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        canonical_inventory = self._scan_sandbox_inventory_for_profiles(
            sandbox_mods_path=sandbox_mods_path,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        profile_state_by_folder, _ = _build_profile_entry_state_maps(
            inventory=profile_inventory,
            root=profile_root,
        )
        canonical_state_by_folder, _ = _build_profile_entry_state_maps(
            inventory=canonical_inventory,
            root=sandbox_mods_path,
        )
        disabled_rows = tuple(
            mod
            for key, state in sorted(canonical_state_by_folder.items())
            if key not in profile_state_by_folder
            for mod in state.mods
        )
        inventory = replace(
            profile_inventory,
            disabled_mods=disabled_rows,
            scan_entry_findings=_merge_profile_scan_entry_findings(
                profile_inventory,
                canonical_inventory,
            ),
        )
        return (
            ScanResult(
                target_kind=SCAN_TARGET_SANDBOX_MODS,
                scan_path=profile_root,
                inventory=inventory,
            ),
            updated_catalog,
            profile,
        )

    def _scan_selected_real_profile(
        self,
        *,
        real_mods_path: Path,
        existing_config: AppConfig | None,
        catalog: SandboxModProfileCatalog,
        requested_profile_id: str | None = None,
    ) -> tuple[ScanResult, SandboxModProfileCatalog, SandboxModProfile]:
        updated_catalog = catalog
        selected_profile_id = requested_profile_id or catalog.active_profile_id or DEFAULT_REAL_PROFILE_ID
        profile = next(
            (candidate for candidate in catalog.profiles if candidate.profile_id == selected_profile_id),
            None,
        )
        if profile is None:
            raise AppShellError("Selected real profile no longer exists.")

        if updated_catalog.active_profile_id != profile.profile_id:
            updated_catalog = replace(updated_catalog, active_profile_id=profile.profile_id)

        if profile.is_default:
            inventory = self._scan_real_inventory_for_profiles(
                real_mods_path=real_mods_path,
                existing_config=existing_config,
            )
            return (
                ScanResult(
                    target_kind=SCAN_TARGET_CONFIGURED_REAL_MODS,
                    scan_path=real_mods_path,
                    inventory=inventory,
                ),
                updated_catalog,
                profile,
            )

        profile, updated_catalog = self._materialize_real_profile_if_needed(
            catalog=updated_catalog,
            profile=profile,
            real_mods_path=real_mods_path,
        )
        profile_root = self._real_mod_profile_mods_path(
            profile,
            real_mods_path=real_mods_path,
        )
        profile_inventory = self._scan_real_inventory_for_profiles(
            real_mods_path=profile_root,
            existing_config=existing_config,
        )
        canonical_inventory = self._scan_real_inventory_for_profiles(
            real_mods_path=real_mods_path,
            existing_config=existing_config,
        )
        profile_state_by_folder, _ = _build_profile_entry_state_maps(
            inventory=profile_inventory,
            root=profile_root,
        )
        canonical_state_by_folder, _ = _build_profile_entry_state_maps(
            inventory=canonical_inventory,
            root=real_mods_path,
        )
        disabled_rows = tuple(
            mod
            for key, state in sorted(canonical_state_by_folder.items())
            if key not in profile_state_by_folder
            for mod in state.mods
        )
        inventory = replace(
            profile_inventory,
            disabled_mods=disabled_rows,
            scan_entry_findings=_merge_profile_scan_entry_findings(
                profile_inventory,
                canonical_inventory,
            ),
        )
        return (
            ScanResult(
                target_kind=SCAN_TARGET_CONFIGURED_REAL_MODS,
                scan_path=profile_root,
                inventory=inventory,
            ),
            updated_catalog,
            profile,
        )

    def _resolve_selected_sandbox_profile_path(
        self,
        *,
        catalog: SandboxModProfileCatalog,
        sandbox_mods_path: Path,
        requested_profile_id: str | None,
    ) -> tuple[Path, SandboxModProfileCatalog, SandboxModProfile]:
        selected_profile_id = requested_profile_id or catalog.active_profile_id or DEFAULT_SANDBOX_PROFILE_ID
        profile = next(
            (candidate for candidate in catalog.profiles if candidate.profile_id == selected_profile_id),
            None,
        )
        if profile is None:
            raise AppShellError("Selected sandbox profile no longer exists.")

        updated_catalog = catalog
        if updated_catalog.active_profile_id != profile.profile_id:
            updated_catalog = replace(updated_catalog, active_profile_id=profile.profile_id)

        if profile.is_default:
            return sandbox_mods_path, updated_catalog, profile

        profile, updated_catalog = self._materialize_sandbox_profile_if_needed(
            catalog=updated_catalog,
            profile=profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        return (
            self._sandbox_mod_profile_mods_path(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            ),
            updated_catalog,
            profile,
        )

    def _resolve_selected_real_profile_path(
        self,
        *,
        catalog: SandboxModProfileCatalog,
        real_mods_path: Path,
        requested_profile_id: str | None,
    ) -> tuple[Path, SandboxModProfileCatalog, SandboxModProfile]:
        selected_profile_id = requested_profile_id or catalog.active_profile_id or DEFAULT_REAL_PROFILE_ID
        profile = next(
            (candidate for candidate in catalog.profiles if candidate.profile_id == selected_profile_id),
            None,
        )
        if profile is None:
            raise AppShellError("Selected real profile no longer exists.")

        updated_catalog = catalog
        if updated_catalog.active_profile_id != profile.profile_id:
            updated_catalog = replace(updated_catalog, active_profile_id=profile.profile_id)

        if profile.is_default:
            return real_mods_path, updated_catalog, profile

        profile, updated_catalog = self._materialize_real_profile_if_needed(
            catalog=updated_catalog,
            profile=profile,
            real_mods_path=real_mods_path,
        )
        return (
            self._real_mod_profile_mods_path(
                profile,
                real_mods_path=real_mods_path,
            ),
            updated_catalog,
            profile,
        )

    def _prepare_canonical_sandbox_profile_library(self, sandbox_mods_path: Path) -> Path:
        canonical_root = sandbox_mods_path.expanduser().resolve(strict=False)
        pending_renames: list[tuple[Path, Path]] = []
        for child in canonical_root.iterdir():
            if not child.is_dir():
                continue
            if not child.name.startswith("."):
                continue
            if child.name in {
                _DEFAULT_SANDBOX_ARCHIVE_DIRNAME,
                _DEFAULT_REAL_ARCHIVE_DIRNAME,
                _LEGACY_ARCHIVE_DIRNAME,
            }:
                continue
            normalized_name = child.name[1:]
            if not normalized_name:
                continue
            target_path = child.with_name(normalized_name)
            if target_path.exists():
                raise AppShellError(
                    "Sandbox profile migration is blocked because a canonical folder already exists: "
                    f"{target_path}"
                )
            pending_renames.append((child, target_path))

        for source_path, target_path in pending_renames:
            try:
                source_path.rename(target_path)
            except OSError as exc:
                raise AppShellError(
                    f"Could not normalize canonical sandbox mod folder {source_path.name}: {exc}"
                ) from exc
        return canonical_root

    def _materialize_sandbox_profile_if_needed(
        self,
        *,
        catalog: SandboxModProfileCatalog,
        profile: SandboxModProfile,
        sandbox_mods_path: Path,
    ) -> tuple[SandboxModProfile, SandboxModProfileCatalog]:
        if profile.storage_dir_name:
            profile_root = self._sandbox_mod_profile_mods_path(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            )
            profile_root.mkdir(parents=True, exist_ok=True)
            return profile, catalog

        if not profile.entries:
            raise AppShellError(
                f"Sandbox profile '{profile.name}' cannot be used because it has no stored state."
            )

        materialized_profile = replace(
            profile,
            storage_dir_name=uuid4().hex,
            entries=tuple(),
        )
        profile_root = self._sandbox_mod_profile_mods_path(
            materialized_profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        profile_root.mkdir(parents=True, exist_ok=True)
        performed_links: list[Path] = []
        try:
            for entry in profile.entries:
                if not entry.enabled:
                    continue
                canonical_path = sandbox_mods_path / entry.folder_name
                if not canonical_path.exists():
                    continue
                link_path = profile_root / entry.folder_name
                if link_path.exists():
                    continue
                _create_directory_link(link_path, canonical_path)
                performed_links.append(link_path)
        except OSError as exc:
            for link_path in reversed(performed_links):
                try:
                    if link_path.exists():
                        _remove_directory_link(link_path)
                except OSError:
                    pass
            raise AppShellError(f"Could not materialize sandbox profile '{profile.name}': {exc}") from exc

        updated_catalog = replace(
            catalog,
            profiles=tuple(
                materialized_profile if candidate.profile_id == profile.profile_id else candidate
                for candidate in catalog.profiles
            ),
        )
        return materialized_profile, updated_catalog

    def _materialize_real_profile_if_needed(
        self,
        *,
        catalog: SandboxModProfileCatalog,
        profile: SandboxModProfile,
        real_mods_path: Path,
    ) -> tuple[SandboxModProfile, SandboxModProfileCatalog]:
        if profile.storage_dir_name:
            profile_root = self._real_mod_profile_mods_path(
                profile,
                real_mods_path=real_mods_path,
            )
            profile_root.mkdir(parents=True, exist_ok=True)
            return profile, catalog

        if not profile.entries:
            raise AppShellError(
                f"Real profile '{profile.name}' cannot be used because it has no stored state."
            )

        materialized_profile = replace(
            profile,
            storage_dir_name=uuid4().hex,
            entries=tuple(),
        )
        profile_root = self._real_mod_profile_mods_path(
            materialized_profile,
            real_mods_path=real_mods_path,
        )
        profile_root.mkdir(parents=True, exist_ok=True)
        performed_links: list[Path] = []
        try:
            for entry in profile.entries:
                if not entry.enabled:
                    continue
                canonical_path = real_mods_path / entry.folder_name
                if not canonical_path.exists():
                    continue
                link_path = profile_root / entry.folder_name
                if link_path.exists():
                    continue
                _create_directory_link(link_path, canonical_path)
                performed_links.append(link_path)
        except OSError as exc:
            for link_path in reversed(performed_links):
                try:
                    if link_path.exists():
                        _remove_directory_link(link_path)
                except OSError:
                    pass
            raise AppShellError(f"Could not materialize real profile '{profile.name}': {exc}") from exc

        updated_catalog = replace(
            catalog,
            profiles=tuple(
                materialized_profile if candidate.profile_id == profile.profile_id else candidate
                for candidate in catalog.profiles
            ),
        )
        return materialized_profile, updated_catalog

    def _materialize_profile_from_canonical_library(
        self,
        *,
        profile: SandboxModProfile,
        sandbox_mods_path: Path,
    ) -> int:
        self._prepare_sandbox_profile_group_dirs(sandbox_mods_path)
        profile_root = self._sandbox_mod_profile_mods_path(
            profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        if profile_root.exists():
            raise OSError(f"Profile root already exists: {profile_root}")
        profile_root.mkdir(parents=True, exist_ok=False)
        linked_count = 0
        try:
            for child in sorted(sandbox_mods_path.iterdir(), key=lambda path: path.name.casefold()):
                if not child.is_dir():
                    continue
                link_path = profile_root / child.name
                _create_directory_link(link_path, child)
                linked_count += 1
        except OSError:
            self._remove_materialized_profile_root(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            )
            raise
        return linked_count

    def _materialize_real_profile_from_canonical_library(
        self,
        *,
        profile: SandboxModProfile,
        real_mods_path: Path,
    ) -> int:
        self._prepare_sandbox_profile_group_dirs(real_mods_path)
        profile_root = self._real_mod_profile_mods_path(
            profile,
            real_mods_path=real_mods_path,
        )
        if profile_root.exists():
            raise OSError(f"Profile root already exists: {profile_root}")
        profile_root.mkdir(parents=True, exist_ok=False)
        linked_count = 0
        try:
            for child in sorted(real_mods_path.iterdir(), key=lambda path: path.name.casefold()):
                if not child.is_dir():
                    continue
                link_path = profile_root / child.name
                _create_directory_link(link_path, child)
                linked_count += 1
        except OSError:
            self._remove_materialized_real_profile_root(
                profile,
                real_mods_path=real_mods_path,
            )
            raise
        return linked_count

    def _remove_materialized_profile_root(
        self,
        profile: SandboxModProfile,
        *,
        sandbox_mods_path: Path,
    ) -> None:
        if not profile.storage_dir_name:
            return
        profile_root = self._sandbox_mod_profile_mods_path(
            profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        if profile_root.exists():
            for child in list(profile_root.iterdir()):
                if child.is_dir():
                    _remove_directory_link(child)
                else:
                    child.unlink(missing_ok=True)
            profile_root.rmdir()
        container = self._sandbox_mod_profile_root_dir(
            profile,
            sandbox_mods_path=sandbox_mods_path,
        )
        if container.exists():
            container.rmdir()

    def _remove_materialized_real_profile_root(
        self,
        profile: SandboxModProfile,
        *,
        real_mods_path: Path,
    ) -> None:
        if not profile.storage_dir_name:
            return
        profile_root = self._real_mod_profile_mods_path(
            profile,
            real_mods_path=real_mods_path,
        )
        if profile_root.exists():
            for child in list(profile_root.iterdir()):
                if child.is_dir():
                    _remove_directory_link(child)
                else:
                    child.unlink(missing_ok=True)
            profile_root.rmdir()
        container = self._real_mod_profile_root_dir(
            profile,
            real_mods_path=real_mods_path,
        )
        if container.exists():
            container.rmdir()

    def _prepare_sandbox_profile_group_dirs(self, sandbox_mods_path: Path) -> None:
        profiles_root = self._cinderleaf_profiles_root_dir(sandbox_mods_path)
        (profiles_root / _SANDBOX_PROFILE_GROUP_DIRNAME).mkdir(parents=True, exist_ok=True)
        (profiles_root / _REAL_PROFILE_GROUP_DIRNAME).mkdir(parents=True, exist_ok=True)

    def _cinderleaf_profiles_root_dir(self, sandbox_mods_path: Path) -> Path:
        canonical_root = sandbox_mods_path.expanduser().resolve(strict=False)
        if (
            canonical_root.name.casefold() == _SANDBOX_PROFILE_GROUP_DIRNAME.casefold()
            and canonical_root.parent.name.casefold() == "cinderleaf"
        ):
            cinderleaf_root = canonical_root.parent
        else:
            cinderleaf_root = canonical_root.parent / "Cinderleaf"
        return cinderleaf_root / _PROFILES_DIRNAME

    def _sandbox_mod_profile_root_dir(
        self,
        profile: SandboxModProfile,
        *,
        sandbox_mods_path: Path,
    ) -> Path:
        if not profile.storage_dir_name:
            raise AppShellError(f"Sandbox profile '{profile.name}' does not have a storage root yet.")
        return (
            self._cinderleaf_profiles_root_dir(sandbox_mods_path)
            / _SANDBOX_PROFILE_GROUP_DIRNAME
            / profile.storage_dir_name
        )

    def _sandbox_mod_profile_mods_path(
        self,
        profile: SandboxModProfile,
        *,
        sandbox_mods_path: Path,
    ) -> Path:
        return (
            self._sandbox_mod_profile_root_dir(
                profile,
                sandbox_mods_path=sandbox_mods_path,
            )
            / _SANDBOX_PROFILE_MODS_DIRNAME
        )

    def _real_mod_profile_root_dir(
        self,
        profile: SandboxModProfile,
        *,
        real_mods_path: Path,
    ) -> Path:
        if not profile.storage_dir_name:
            raise AppShellError(f"Real profile '{profile.name}' does not have a storage root yet.")
        return (
            self._cinderleaf_profiles_root_dir(real_mods_path)
            / _REAL_PROFILE_GROUP_DIRNAME
            / profile.storage_dir_name
        )

    def _real_mod_profile_mods_path(
        self,
        profile: SandboxModProfile,
        *,
        real_mods_path: Path,
    ) -> Path:
        return (
            self._real_mod_profile_root_dir(
                profile,
                real_mods_path=real_mods_path,
            )
            / _SANDBOX_PROFILE_MODS_DIRNAME
        )

    def _save_normalized_sandbox_profile_catalog(
        self,
        catalog: SandboxModProfileCatalog,
    ) -> None:
        try:
            save_sandbox_mod_profile_catalog(self._sandbox_mod_profile_catalog_file, catalog)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not save sandbox mod profiles: {exc}") from exc

    def _save_normalized_real_profile_catalog(
        self,
        catalog: SandboxModProfileCatalog,
    ) -> None:
        try:
            save_real_mod_profile_catalog(self._real_mod_profile_catalog_file, catalog)
        except AppStateStoreError as exc:
            raise AppShellError(f"Could not save real mod profiles: {exc}") from exc

    def get_sandbox_mods_promotion_readiness(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None = None,
    ) -> SandboxModsPromotionReadiness:
        try:
            preview = self.build_sandbox_mods_promotion_preview(
                configured_mods_path_text=configured_mods_path_text,
                sandbox_mods_path_text=sandbox_mods_path_text,
                real_archive_path_text=real_archive_path_text,
                selected_mod_folder_paths_text=selected_mod_folder_paths_text,
                existing_config=existing_config,
            )
        except AppShellError as exc:
            return SandboxModsPromotionReadiness(ready=False, message=str(exc))

        replace_count = sum(
            1 for entry in preview.plan.entries if entry.action == OVERWRITE_WITH_ARCHIVE
        )
        if not preview.review.allowed:
            return SandboxModsPromotionReadiness(
                ready=False,
                message=preview.review.message,
                real_mods_path=preview.real_mods_path,
                sandbox_mods_path=preview.sandbox_mods_path,
                archive_path=preview.archive_path,
                selected_count=len(preview.source_mod_paths),
                replace_count=replace_count,
            )

        if replace_count > 0:
            message = (
                f"Review required: {len(preview.source_mod_paths)} selected mod(s) include "
                f"{replace_count} archive-aware live replacement(s) for REAL Mods."
            )
        else:
            message = (
                f"Ready to review {len(preview.source_mod_paths)} selected mod(s) "
                "for promotion into the configured real Mods path."
            )

        return SandboxModsPromotionReadiness(
            ready=True,
            message=message,
            real_mods_path=preview.real_mods_path,
            sandbox_mods_path=preview.sandbox_mods_path,
            archive_path=preview.archive_path,
            selected_count=len(preview.source_mod_paths),
            replace_count=replace_count,
        )

    def build_sandbox_mods_promotion_preview(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None = None,
    ) -> SandboxModsPromotionPreview:
        real_mods_path, sandbox_mods_path, archive_path, source_paths, source_inventory = (
            self._resolve_sandbox_mod_promotion_context(
                configured_mods_path_text=configured_mods_path_text,
                sandbox_mods_path_text=sandbox_mods_path_text,
                real_archive_path_text=real_archive_path_text,
                selected_mod_folder_paths_text=selected_mod_folder_paths_text,
                existing_config=existing_config,
            )
        )
        plan = self._build_sandbox_mods_promotion_plan(
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            archive_path=archive_path,
            source_paths=source_paths,
            source_inventory=source_inventory,
        )
        review = self.review_install_execution(plan)
        return SandboxModsPromotionPreview(
            plan=plan,
            review=review,
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            archive_path=archive_path,
            source_mod_paths=source_paths,
        )

    def promote_installed_mods_from_sandbox_to_real(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None = None,
    ) -> SandboxModsPromotionResult:
        preview = self.build_sandbox_mods_promotion_preview(
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            selected_mod_folder_paths_text=selected_mod_folder_paths_text,
            existing_config=existing_config,
        )
        return self.execute_sandbox_mods_promotion_preview(preview)

    def execute_sandbox_mods_promotion_preview(
        self,
        preview: SandboxModsPromotionPreview,
    ) -> SandboxModsPromotionResult:
        if not preview.review.allowed:
            raise AppShellError(preview.review.message)

        _ensure_archive_root_service(preview.archive_path)
        staging_root = (
            preview.real_mods_path / f".sdvmm-promotion-stage-{uuid4().hex[:10]}"
        )
        applied_entries: list[SandboxInstallPlanEntry] = []
        installed_targets: list[Path] = []
        archived_targets: list[Path] = []
        replaced_targets: list[Path] = []
        try:
            staging_root.mkdir(parents=False, exist_ok=False)

            for entry in preview.plan.entries:
                staged_target = staging_root / entry.target_path.name
                shutil.copytree(Path(entry.source_root_path), staged_target)

            for entry in preview.plan.entries:
                staged_target = staging_root / entry.target_path.name
                if entry.action == INSTALL_NEW:
                    try:
                        staged_target.rename(entry.target_path)
                    except OSError as exc:
                        raise AppShellError(
                            "Sandbox promotion failed while creating a new REAL Mods target: "
                            f"{entry.target_path}: {exc}"
                        ) from exc
                    installed_targets.append(entry.target_path)
                    applied_entries.append(entry)
                    continue

                if entry.action == OVERWRITE_WITH_ARCHIVE:
                    if entry.archive_path is None:
                        raise AppShellError(
                            "Sandbox promotion preview is invalid: overwrite entry is missing "
                            f"archive path for {entry.target_path}."
                        )
                    try:
                        _overwrite_target_with_archive_service(
                            staged_target=staged_target,
                            target_path=entry.target_path,
                            archive_path=entry.archive_path,
                        )
                    except SandboxInstallError as exc:
                        raise AppShellError(f"Sandbox promotion failed: {exc}") from exc
                    installed_targets.append(entry.target_path)
                    archived_targets.append(entry.archive_path)
                    replaced_targets.append(entry.target_path)
                    applied_entries.append(entry)
                    continue

                raise AppShellError(
                    f"Sandbox promotion preview contains a blocked entry: {entry.target_path}"
                )
            inventory = scan_mods_directory(
                preview.real_mods_path,
                excluded_paths=(
                    preview.archive_path,
                    preview.real_mods_path / _LEGACY_ARCHIVE_DIRNAME,
                ),
            )
            result = SandboxInstallResult(
                plan=preview.plan,
                installed_targets=tuple(
                    sorted(installed_targets, key=lambda path: path.name.lower())
                ),
                archived_targets=tuple(
                    sorted(archived_targets, key=lambda path: path.name.lower())
                ),
                scan_context_path=preview.real_mods_path,
                inventory=inventory,
                destination_kind=INSTALL_TARGET_CONFIGURED_REAL_MODS,
            )
            self._record_completed_install_operation(plan=preview.plan, result=result)
        except (AppShellError, SandboxInstallError, OSError) as exc:
            if not applied_entries:
                raise _normalize_sandbox_promotion_error(exc) from exc

            rollback_errors = self._rollback_sandbox_mods_promotion_entries(
                tuple(applied_entries)
            )
            (
                remaining_entries,
                remaining_installed_targets,
                remaining_archived_targets,
            ) = self._remaining_sandbox_mods_promotion_state(tuple(applied_entries))
            if not remaining_entries:
                raise AppShellError(
                    f"{_normalize_sandbox_promotion_error(exc)} "
                    "Promotion rollback restored prior REAL Mods state."
                ) from exc

            partial_plan = replace(
                preview.plan,
                entries=remaining_entries,
                plan_warnings=preview.plan.plan_warnings
                + (
                    "Partial sandbox promotion failure left remaining live changes after rollback.",
                    "Recovery inspection depends on this recorded partial promotion state.",
                ),
            )
            partial_record_error: AppShellError | None = None
            try:
                self._record_install_operation_state(
                    plan=partial_plan,
                    installed_targets=remaining_installed_targets,
                    archived_targets=remaining_archived_targets,
                )
            except AppShellError as record_exc:
                partial_record_error = record_exc

            rollback_detail = ""
            if rollback_errors:
                rollback_detail = " Rollback details: " + "; ".join(rollback_errors)

            if partial_record_error is None:
                raise AppShellError(
                    f"{_normalize_sandbox_promotion_error(exc)} "
                    "Promotion rollback could not fully restore prior REAL Mods state. "
                    "Remaining live changes were recorded in install history for recovery inspection."
                    f"{rollback_detail}"
                ) from exc

            raise AppShellError(
                f"{_normalize_sandbox_promotion_error(exc)} "
                "Promotion rollback could not fully restore prior REAL Mods state, and "
                "recording partial install history failed. Manual recovery is required. "
                f"Recording error: {partial_record_error}.{rollback_detail}"
            ) from exc
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)

        return SandboxModsPromotionResult(
            destination_kind=INSTALL_TARGET_CONFIGURED_REAL_MODS,
            real_mods_path=preview.real_mods_path,
            sandbox_mods_path=preview.sandbox_mods_path,
            archive_path=preview.archive_path,
            source_mod_paths=preview.source_mod_paths,
            promoted_target_paths=result.installed_targets,
            archived_target_paths=result.archived_targets,
            replaced_target_paths=tuple(
                sorted(replaced_targets, key=lambda path: path.name.lower())
            ),
            scan_context_path=preview.real_mods_path,
            inventory=inventory,
        )

    def check_smapi_update_status(
        self,
        *,
        game_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> SmapiUpdateStatus:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        try:
            return check_smapi_update_status_service(game_path=game_path)
        except OSError as exc:
            raise AppShellError(f"Could not check SMAPI update status: {exc}") from exc

    @staticmethod
    def resolve_smapi_update_page_url(status: SmapiUpdateStatus | None = None) -> str:
        if status is not None and status.update_page_url.strip():
            return status.update_page_url.strip()
        return default_smapi_update_page_url()

    def check_app_update_status(self, *, current_version: str) -> AppUpdateStatus:
        try:
            return check_app_update_status_service(current_version=current_version)
        except OSError as exc:
            raise AppShellError(f"Could not check Cinderleaf release status: {exc}") from exc

    @staticmethod
    def resolve_app_update_page_url(status: AppUpdateStatus | None = None) -> str:
        if status is not None and status.update_page_url.strip():
            return status.update_page_url.strip()
        return default_app_update_page_url()

    def check_smapi_log_troubleshooting(
        self,
        *,
        game_path_text: str,
        log_path_text: str = "",
        existing_config: AppConfig | None = None,
        preferred_context_label: str | None = None,
    ) -> SmapiLogReport:
        manual_log_path: Path | None = None
        raw_log_path = log_path_text.strip()
        if raw_log_path:
            manual_log_path = Path(raw_log_path).expanduser()
            if not manual_log_path.exists():
                raise AppShellError(f"SMAPI log file does not exist: {manual_log_path}")
            if not manual_log_path.is_file():
                raise AppShellError(f"SMAPI log path is not a file: {manual_log_path}")
            if manual_log_path.suffix.casefold() not in {".txt", ".log"}:
                raise AppShellError(
                    f"SMAPI log file must be .txt or .log: {manual_log_path}"
                )

        resolved_game_path: Path | None = None
        if not manual_log_path:
            resolved_game_path = self._resolve_game_path(game_path_text, existing_config)
        elif game_path_text.strip():
            resolved_game_path = self._parse_and_validate_game_path(game_path_text)

        try:
            service_kwargs = {
                "game_path": resolved_game_path,
                "manual_log_path": manual_log_path,
            }
            if preferred_context_label is not None:
                service_kwargs["preferred_context_label"] = preferred_context_label
            return check_smapi_log_troubleshooting_service(**service_kwargs)
        except OSError as exc:
            raise AppShellError(f"Could not inspect SMAPI log: {exc}") from exc

    def scan(self, mods_dir_text: str) -> ModsInventory:
        mods_path = self._parse_and_validate_mods_path(mods_dir_text)
        excluded_paths = (mods_path / _LEGACY_ARCHIVE_DIRNAME,)

        try:
            return scan_mods_directory(mods_path, excluded_paths=excluded_paths)
        except OSError as exc:
            raise AppShellError(f"Could not scan Mods directory: {exc}") from exc

    def scan_with_target(
        self,
        *,
        scan_target: ScanTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str = "",
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> ScanResult:
        if scan_target == SCAN_TARGET_CONFIGURED_REAL_MODS:
            real_mods_path = self._parse_and_validate_mods_path(configured_mods_path_text)
            catalog = self.load_real_mod_profiles()
            scan_result, updated_catalog, _ = self._scan_selected_real_profile(
                real_mods_path=real_mods_path,
                existing_config=existing_config,
                catalog=catalog,
            )
            if updated_catalog != catalog:
                self._save_normalized_real_profile_catalog(updated_catalog)
            return scan_result
        elif scan_target == SCAN_TARGET_SANDBOX_MODS:
            sandbox_mods_path = self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
            sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)
            catalog = self.load_sandbox_mod_profiles()
            scan_result, updated_catalog, _ = self._scan_selected_sandbox_profile(
                sandbox_mods_path=sandbox_mods_path,
                sandbox_archive_path_text=sandbox_archive_path_text,
                existing_config=existing_config,
                catalog=catalog,
            )
            if updated_catalog != catalog:
                self._save_normalized_sandbox_profile_catalog(updated_catalog)
            return scan_result
        else:
            raise AppShellError(f"Unknown scan target: {scan_target}")

    def compare_real_and_sandbox_mods(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str = "",
        sandbox_archive_path_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> ModsCompareResult:
        real_mods_path = self._parse_and_validate_mods_path(configured_mods_path_text)
        sandbox_mods_path = self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
        real_excluded_paths = self._resolve_scan_excluded_paths(
            scan_target=SCAN_TARGET_CONFIGURED_REAL_MODS,
            scan_path=real_mods_path,
            configured_archive_text=real_archive_path_text,
            configured_archive_fallback=(
                existing_config.real_archive_path if existing_config is not None else None
            ),
        )
        sandbox_excluded_paths = self._resolve_scan_excluded_paths(
            scan_target=SCAN_TARGET_SANDBOX_MODS,
            scan_path=sandbox_mods_path,
            configured_archive_text=sandbox_archive_path_text,
            configured_archive_fallback=(
                existing_config.sandbox_archive_path if existing_config is not None else None
            ),
        )

        try:
            real_inventory = scan_mods_directory(real_mods_path, excluded_paths=real_excluded_paths)
            sandbox_inventory = scan_mods_directory(
                sandbox_mods_path,
                excluded_paths=sandbox_excluded_paths,
            )
        except OSError as exc:
            raise AppShellError(f"Could not compare real and sandbox Mods: {exc}") from exc

        return _build_mods_compare_result(
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            real_inventory=real_inventory,
            sandbox_inventory=sandbox_inventory,
        )

    def inspect_zip(self, package_path_text: str) -> PackageInspectionResult:
        package_path = self._parse_and_validate_zip_path(package_path_text)

        try:
            return inspect_zip_package(package_path)
        except zipfile.BadZipFile as exc:
            raise AppShellError(f"File is not a valid zip package: {package_path}") from exc
        except OSError as exc:
            raise AppShellError(f"Could not inspect package: {exc}") from exc

    def inspect_zip_with_inventory_context(
        self,
        package_path_text: str,
        inventory: ModsInventory | None,
        *,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> PackageInspectionResult:
        base_result = self.inspect_zip(package_path_text)
        return self._enrich_package_inspection_result(
            base_result,
            inventory=inventory,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

    def inspect_zip_batch_with_inventory_context(
        self,
        package_path_texts: Iterable[str],
        inventory: ModsInventory | None,
        *,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> PackageInspectionBatchResult:
        path_texts = tuple(text.strip() for text in package_path_texts if text.strip())
        if not path_texts:
            raise AppShellError("Select one or more zip packages to inspect.")

        entries: list[PackageInspectionBatchEntry] = []
        for package_path_text in path_texts:
            package_path = Path(package_path_text)
            try:
                inspection = self.inspect_zip_with_inventory_context(
                    package_path_text,
                    inventory,
                    nexus_api_key_text=nexus_api_key_text,
                    existing_config=existing_config,
                )
            except AppShellError as exc:
                entries.append(
                    PackageInspectionBatchEntry(
                        package_path=package_path,
                        error_message=str(exc),
                    )
                )
                continue

            entries.append(
                PackageInspectionBatchEntry(
                    package_path=inspection.package_path,
                    inspection=inspection,
                )
            )

        return PackageInspectionBatchResult(entries=tuple(entries))

    @staticmethod
    def evaluate_installed_dependency_preflight(
        inventory: ModsInventory,
    ) -> tuple[DependencyPreflightFinding, ...]:
        return evaluate_installed_dependencies(inventory.mods)

    def check_updates(
        self,
        inventory: ModsInventory,
        *,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> ModUpdateReport:
        nexus_api_key = self._resolve_nexus_api_key(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )
        update_source_intent_overlay = self.load_update_source_intent_overlay()
        try:
            return check_updates_for_inventory(
                inventory,
                nexus_api_key=nexus_api_key,
                update_source_intent_overlay=update_source_intent_overlay,
            )
        except OSError as exc:
            raise AppShellError(f"Could not check remote metadata: {exc}") from exc

    def _enrich_package_inspection_result(
        self,
        base_result: PackageInspectionResult,
        *,
        inventory: ModsInventory | None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> PackageInspectionResult:
        nexus_api_key = self._resolve_nexus_api_key(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )
        dependency_findings = evaluate_package_dependencies(
            package_mods=base_result.mods,
            installed_mods=inventory.mods if inventory is not None else None,
            source="package_inspection",
        )
        remote_requirements = evaluate_remote_requirements_for_package_mods(
            base_result.mods,
            source="package_inspection",
            nexus_api_key=nexus_api_key,
        )
        return replace(
            base_result,
            dependency_findings=dependency_findings,
            remote_requirements=remote_requirements,
        )

    def search_mod_discovery(
        self,
        *,
        query_text: str,
        max_results: int = 50,
    ) -> ModDiscoveryResult:
        try:
            return search_discoverable_mods(
                query_text,
                max_results=max_results,
            )
        except DiscoveryServiceError as exc:
            raise AppShellError(f"Could not search mod discovery index: [{exc.reason}] {exc.message}") from exc
        except OSError as exc:
            raise AppShellError(f"Could not search mod discovery index: {exc}") from exc

    @staticmethod
    def resolve_discovery_source_page_url(entry: ModDiscoveryEntry) -> str:
        if entry.source_page_url:
            return entry.source_page_url
        raise AppShellError(
            f"No source page URL is available for discovered mod: {entry.unique_id}"
        )

    def correlate_discovery_results(
        self,
        *,
        discovery_result: ModDiscoveryResult,
        inventory: ModsInventory | None,
        update_report: ModUpdateReport | None,
    ) -> tuple[DiscoveryContextCorrelation, ...]:
        installed_keys: dict[str, str] = {}
        if inventory is not None:
            for mod in inventory.mods:
                key = canonicalize_unique_id(mod.unique_id)
                installed_keys.setdefault(key, mod.unique_id)

        update_status_by_key: dict[str, object] = {}
        if update_report is not None:
            for status in update_report.statuses:
                key = canonicalize_unique_id(status.unique_id)
                update_status_by_key.setdefault(key, status)

        correlations: list[DiscoveryContextCorrelation] = []
        for entry in discovery_result.results:
            key_candidates = _discovery_entry_unique_id_keys(entry)
            installed_match_unique_id = _first_present(installed_keys, key_candidates)
            update_status = _first_present(update_status_by_key, key_candidates)

            update_state = None
            tracked_provider = None
            if update_status is not None:
                update_state = str(update_status.state)
                if update_status.remote_link is not None:
                    tracked_provider = str(update_status.remote_link.provider)

            provider_relation, provider_relation_note = _build_discovery_provider_relation(
                discovery_source_provider=entry.source_provider,
                tracked_provider=tracked_provider,
            )
            context_summary, next_step = _build_discovery_context_messages(
                installed_match_unique_id=installed_match_unique_id,
                update_state=update_state,
            )

            correlations.append(
                DiscoveryContextCorrelation(
                    entry=entry,
                    installed_match_unique_id=installed_match_unique_id,
                    update_state=update_state,
                    provider_relation=provider_relation,
                    provider_relation_note=provider_relation_note,
                    context_summary=context_summary,
                    next_step=next_step,
                )
            )

        return tuple(correlations)

    @staticmethod
    def build_manual_discovery_flow_hint(
        *,
        correlation: DiscoveryContextCorrelation,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        watcher_running: bool,
    ) -> str:
        watched_path = AppShellService._format_watched_download_paths_for_guidance(
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
        )
        watch_step = (
            "Watcher is running; it will detect new zip files added now."
            if watcher_running
            else "Start watch before downloading, so new zip files are detected."
        )
        relation = (
            f"\nProvider relation: {correlation.provider_relation_note}"
            if correlation.provider_relation_note
            else ""
        )
        return (
            f"Manual discovery flow for {correlation.entry.unique_id}:\n"
            f"Context: {correlation.context_summary}.{relation}\n"
            "1. Open source page and download the zip manually.\n"
            f"2. Save the zip into {watched_path}\n"
            f"3. {watch_step}\n"
            "4. In detected packages, select that zip and click 'Plan selected intake'.\n"
            "5. Review dependency + archive/overwrite warnings, then run install explicitly."
        )

    def get_nexus_integration_status(
        self,
        *,
        nexus_api_key_text: str,
        existing_config: AppConfig | None,
        validate_connection: bool,
    ) -> NexusIntegrationStatus:
        nexus_api_key, source = self._resolve_nexus_api_key_with_source(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
            allow_environment_fallback=True,
        )

        if not nexus_api_key:
            return NexusIntegrationStatus(
                state=NEXUS_NOT_CONFIGURED,
                source="none",
                masked_key=None,
                message="Nexus API key is not configured.",
            )

        if not validate_connection:
            return NexusIntegrationStatus(
                state=NEXUS_CONFIGURED,
                source=source,
                masked_key=mask_api_key(nexus_api_key),
                message="Nexus key is configured. Run connection check to validate it.",
            )

        status = check_nexus_connection(nexus_api_key=nexus_api_key)
        return replace(status, source=source)

    def initialize_downloads_watch(
        self,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
    ) -> tuple[Path, ...]:
        watched_paths = self._parse_and_validate_watched_downloads_path(
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
        )

        try:
            combined_known_zip_paths: list[Path] = []
            seen_paths: set[Path] = set()
            for watched_path in watched_paths:
                for zip_path in initialize_known_zip_paths(watched_path):
                    if zip_path in seen_paths:
                        continue
                    seen_paths.add(zip_path)
                    combined_known_zip_paths.append(zip_path)
            return tuple(combined_known_zip_paths)
        except OSError as exc:
            raise AppShellError(f"Could not initialize watched downloads directories: {exc}") from exc

    def poll_downloads_watch(
        self,
        *,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        known_zip_paths: tuple[Path, ...],
        inventory: ModsInventory,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> DownloadsWatchPollResult:
        watched_paths = self._parse_and_validate_watched_downloads_path(
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
        )
        nexus_api_key = self._resolve_nexus_api_key(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

        try:
            poll_results = tuple(
                poll_watched_directory(
                    watched_path=watched_path,
                    known_zip_paths=known_zip_paths,
                    inventory=inventory,
                )
                for watched_path in watched_paths
            )

            enriched_intakes = []
            combined_known_zip_paths: list[Path] = []
            seen_known_zip_paths: set[Path] = set()
            for result in poll_results:
                for zip_path in result.known_zip_paths:
                    if zip_path in seen_known_zip_paths:
                        continue
                    seen_known_zip_paths.add(zip_path)
                    combined_known_zip_paths.append(zip_path)
                for intake in result.intakes:
                    enriched_intakes.append(
                        replace(
                            intake,
                            remote_requirements=evaluate_remote_requirements_for_package_mods(
                                intake.mods,
                                source="downloads_intake",
                                nexus_api_key=nexus_api_key,
                            ),
                        )
                    )

            return DownloadsWatchPollResult(
                watched_path=watched_paths[0],
                known_zip_paths=tuple(combined_known_zip_paths),
                intakes=tuple(enriched_intakes),
            )
        except OSError as exc:
            raise AppShellError(f"Could not poll watched downloads directories: {exc}") from exc

    @staticmethod
    def select_intake_result(
        *,
        intakes: tuple[DownloadsIntakeResult, ...],
        selected_index: int,
    ) -> DownloadsIntakeResult:
        if selected_index < 0 or selected_index >= len(intakes):
            raise AppShellError("Select a detected package first.")
        return intakes[selected_index]

    @staticmethod
    def is_actionable_intake_result(intake: DownloadsIntakeResult) -> bool:
        return intake.classification in _ACTIONABLE_INTAKE_CLASSIFICATIONS

    @staticmethod
    def refresh_detected_intakes_against_inventory(
        *,
        intakes: tuple[DownloadsIntakeResult, ...],
        inventory: ModsInventory | None,
    ) -> tuple[DownloadsIntakeResult, ...]:
        if inventory is None:
            return intakes

        refreshed: list[DownloadsIntakeResult] = []
        for intake in intakes:
            refreshed_intake = inspect_downloads_intake_package(
                package_path=intake.package_path,
                inventory=inventory,
            )
            refreshed.append(
                replace(
                    refreshed_intake,
                    remote_requirements=intake.remote_requirements,
                )
            )
        return tuple(refreshed)

    def build_sandbox_install_plan_from_intake(
        self,
        *,
        intake: DownloadsIntakeResult,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        return self.build_install_plan_from_intake(
            intake=intake,
            install_target=INSTALL_TARGET_SANDBOX_MODS,
            configured_mods_path_text=str(configured_real_mods_path) if configured_real_mods_path else "",
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text="",
            sandbox_archive_path_text=sandbox_archive_path_text,
            allow_overwrite=allow_overwrite,
            configured_real_mods_path=configured_real_mods_path,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

    def build_install_plan_from_intake(
        self,
        *,
        intake: DownloadsIntakeResult,
        install_target: InstallTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        if not self.is_actionable_intake_result(intake):
            raise AppShellError(
                f"Selected package is not actionable for install planning: {intake.classification}"
            )

        return self.build_install_plan(
            package_path_text=str(intake.package_path),
            install_target=install_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            allow_overwrite=allow_overwrite,
            configured_real_mods_path=configured_real_mods_path,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

    def correlate_intakes_with_updates(
        self,
        *,
        intakes: tuple[DownloadsIntakeResult, ...],
        inventory: ModsInventory | None = None,
        comparison_target_kind: ScanTargetKind | None = None,
        update_report: ModUpdateReport | None,
        guided_update_unique_ids: tuple[str, ...] = tuple(),
    ) -> tuple[IntakeUpdateCorrelation, ...]:
        return tuple(
            self.correlate_intake_with_updates(
                intake=intake,
                inventory=inventory,
                comparison_target_kind=comparison_target_kind,
                update_report=update_report,
                guided_update_unique_ids=guided_update_unique_ids,
            )
            for intake in intakes
        )

    def correlate_intake_with_updates(
        self,
        *,
        intake: DownloadsIntakeResult,
        inventory: ModsInventory | None = None,
        comparison_target_kind: ScanTargetKind | None = None,
        update_report: ModUpdateReport | None,
        guided_update_unique_ids: tuple[str, ...] = tuple(),
    ) -> IntakeUpdateCorrelation:
        actionable = self.is_actionable_intake_result(intake)
        legacy_mode = inventory is None and comparison_target_kind is None
        comparison_target_label = _packages_comparison_target_label(comparison_target_kind)
        version_comparisons = (
            tuple()
            if legacy_mode
            else _compare_intake_against_inventory(
                intake=intake,
                inventory=inventory,
            )
        )
        comparison_state = (
            "not_installed_in_target"
            if legacy_mode
            else _resolve_package_comparison_state(
                inventory=inventory,
                comparisons=version_comparisons,
            )
        )
        update_candidate_unique_ids = (
            intake.matched_installed_unique_ids
            if legacy_mode
            else tuple(
                comparison.installed_unique_id
                for comparison in version_comparisons
                if comparison.state == "newer" and comparison.installed_unique_id
            )
        )

        update_available_keys: dict[str, str] = {}
        if update_report is not None:
            for status in update_report.statuses:
                if status.state != "update_available":
                    continue
                key = canonicalize_unique_id(status.unique_id)
                if key not in update_available_keys:
                    update_available_keys[key] = status.unique_id

        matched_update_available = _sorted_unique_ids(
            unique_id
            for unique_id in update_candidate_unique_ids
            if canonicalize_unique_id(unique_id) in update_available_keys
        )
        guided_keys = {canonicalize_unique_id(value) for value in guided_update_unique_ids}
        matched_guided = _sorted_unique_ids(
            unique_id
            for unique_id in update_candidate_unique_ids
            if canonicalize_unique_id(unique_id) in guided_keys
        )
        actionable_as_update = actionable and comparison_state == "newer_than_installed"

        if legacy_mode:
            summary, next_step = _build_legacy_intake_flow_messages(
                intake=intake,
                actionable=actionable,
                matched_update_available=matched_update_available,
                matched_guided=matched_guided,
            )
        else:
            summary, next_step = _build_intake_flow_messages(
                intake=intake,
                actionable=actionable,
                comparison_target_label=comparison_target_label,
                comparison_state=comparison_state,
                version_comparisons=version_comparisons,
                matched_update_available=matched_update_available,
                matched_guided=matched_guided,
            )

        return IntakeUpdateCorrelation(
            intake=intake,
            actionable=actionable,
            matched_update_available_unique_ids=matched_update_available,
            matched_guided_update_unique_ids=matched_guided,
            comparison_target_kind=comparison_target_kind,
            comparison_target_label=comparison_target_label,
            comparison_state=comparison_state,
            actionable_as_update=actionable_as_update,
            summary=summary,
            next_step=next_step,
        )

    @staticmethod
    def build_manual_update_flow_hint(
        *,
        unique_id: str,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
        watcher_running: bool,
    ) -> str:
        watched_path = AppShellService._format_watched_download_paths_for_guidance(
            watched_downloads_path_text=watched_downloads_path_text,
            secondary_watched_downloads_path_text=secondary_watched_downloads_path_text,
        )
        watch_step = (
            "Watcher is running; it will detect new zip files added now."
            if watcher_running
            else "Start watch before downloading, so new zip files are detected."
        )
        return (
            f"Manual update flow for {unique_id}:\n"
            "1. Open remote page and download manually.\n"
            f"2. Save the zip into {watched_path}\n"
            f"3. {watch_step}\n"
            "4. In detected packages, select that zip and click 'Stage update'.\n"
            "5. Review plan warnings/dependencies, then run install explicitly."
        )

    def build_sandbox_install_plan(
        self,
        package_path_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        *,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        return self.build_install_plan(
            package_path_text=package_path_text,
            install_target=INSTALL_TARGET_SANDBOX_MODS,
            configured_mods_path_text=str(configured_real_mods_path) if configured_real_mods_path else "",
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text="",
            sandbox_archive_path_text=sandbox_archive_path_text,
            allow_overwrite=allow_overwrite,
            configured_real_mods_path=configured_real_mods_path,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

    def _build_install_plan_for_package_base(
        self,
        *,
        package_path: Path,
        install_target: InstallTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        nexus_api_key = self._resolve_nexus_api_key(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

        destination_mods_path, destination_archive_path = self._resolve_install_destination_paths(
            install_target=install_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
        )

        effective_real_mods_path = configured_real_mods_path
        if effective_real_mods_path is None and configured_mods_path_text.strip():
            effective_real_mods_path = self._parse_and_validate_mods_path(configured_mods_path_text)

        safety = self.evaluate_install_target_safety(
            install_target=install_target,
            destination_mods_path=destination_mods_path,
            configured_real_mods_path=effective_real_mods_path,
        )
        if not safety.allowed:
            assert safety.message is not None
            raise AppShellError(safety.message)

        try:
            plan = build_sandbox_install_plan_service(
                package_path=package_path,
                sandbox_mods_path=destination_mods_path,
                sandbox_archive_path=destination_archive_path,
                allow_overwrite=allow_overwrite,
            )
            inspected_mods = _inspect_package_mod_entries(package_path)
            remote_requirements = evaluate_remote_requirements_for_package_mods(
                inspected_mods,
                source="sandbox_plan",
                nexus_api_key=nexus_api_key,
            )
            return replace(
                plan,
                remote_requirements=remote_requirements,
                destination_kind=install_target,
            )
        except (SandboxInstallError, zipfile.BadZipFile) as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Could not build sandbox install plan: {exc}") from exc

    def _build_install_plan_for_package(
        self,
        *,
        package_path: Path,
        install_target: InstallTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        base_plan = self._build_install_plan_for_package_base(
            package_path=package_path,
            install_target=install_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            allow_overwrite=allow_overwrite,
            configured_real_mods_path=configured_real_mods_path,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )
        return self._apply_install_dependency_preflight(base_plan)

    def _combine_install_plans(
        self,
        plans: tuple[SandboxInstallPlan, ...],
        *,
        package_paths: tuple[Path, ...],
        destination_kind: InstallTargetKind,
    ) -> SandboxInstallPlan:
        first_plan = plans[0]
        return replace(
            first_plan,
            package_path=package_paths[0],
            package_paths=package_paths,
            entries=tuple(entry for plan in plans for entry in plan.entries),
            package_findings=tuple(
                finding for plan in plans for finding in plan.package_findings
            ),
            package_warnings=tuple(
                warning for plan in plans for warning in plan.package_warnings
            ),
            plan_warnings=tuple(warning for plan in plans for warning in plan.plan_warnings),
            dependency_findings=tuple(
                finding for plan in plans for finding in plan.dependency_findings
            ),
            remote_requirements=tuple(
                requirement for plan in plans for requirement in plan.remote_requirements
            ),
            destination_kind=destination_kind,
        )

    def _apply_install_dependency_preflight(
        self,
        plan: SandboxInstallPlan,
    ) -> SandboxInstallPlan:
        inventory = scan_mods_directory(
            plan.sandbox_mods_path,
            excluded_paths=(plan.sandbox_archive_path, plan.sandbox_mods_path / _LEGACY_ARCHIVE_DIRNAME),
        )
        dependency_findings = _evaluate_sandbox_plan_dependencies(
            plan=plan,
            base_findings=plan.dependency_findings,
            installed_inventory=inventory,
        )
        return _apply_dependency_preflight_to_plan(plan, dependency_findings)

    def build_install_plan(
        self,
        *,
        package_path_text: str = "",
        package_paths_text: tuple[str, ...] = tuple(),
        install_target: InstallTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        allow_overwrite: bool,
        configured_real_mods_path: Path | None = None,
        nexus_api_key_text: str = "",
        existing_config: AppConfig | None = None,
    ) -> SandboxInstallPlan:
        selected_package_texts = tuple(
            path_text.strip()
            for path_text in package_paths_text
            if path_text.strip()
        )
        if selected_package_texts:
            package_paths = tuple(
                self._parse_and_validate_zip_path(path_text)
                for path_text in selected_package_texts
            )
            if len(package_paths) == 1:
                return self._build_install_plan_for_package(
                    package_path=package_paths[0],
                    install_target=install_target,
                    configured_mods_path_text=configured_mods_path_text,
                    sandbox_mods_path_text=sandbox_mods_path_text,
                    real_archive_path_text=real_archive_path_text,
                    sandbox_archive_path_text=sandbox_archive_path_text,
                    allow_overwrite=allow_overwrite,
                    configured_real_mods_path=configured_real_mods_path,
                    nexus_api_key_text=nexus_api_key_text,
                    existing_config=existing_config,
                )

            batch_plans = tuple(
                self._build_install_plan_for_package_base(
                    package_path=package_path,
                    install_target=install_target,
                    configured_mods_path_text=configured_mods_path_text,
                    sandbox_mods_path_text=sandbox_mods_path_text,
                    real_archive_path_text=real_archive_path_text,
                    sandbox_archive_path_text=sandbox_archive_path_text,
                    allow_overwrite=allow_overwrite,
                    configured_real_mods_path=configured_real_mods_path,
                    nexus_api_key_text=nexus_api_key_text,
                    existing_config=existing_config,
                )
                for package_path in package_paths
            )
            combined_plan = self._combine_install_plans(
                batch_plans,
                package_paths=package_paths,
                destination_kind=install_target,
            )
            return self._apply_install_dependency_preflight(combined_plan)

        if not package_path_text.strip():
            raise AppShellError("No package selected for install planning.")

        package_path = self._parse_and_validate_zip_path(package_path_text)
        return self._build_install_plan_for_package(
            package_path=package_path,
            install_target=install_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            allow_overwrite=allow_overwrite,
            configured_real_mods_path=configured_real_mods_path,
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
        )

    def execute_sandbox_install_plan(
        self,
        plan: SandboxInstallPlan,
        *,
        confirm_real_destination: bool = False,
    ) -> SandboxInstallResult:
        review = self.review_install_execution(plan)
        if not review.allowed:
            raise AppShellError(review.message)
        if review.requires_explicit_approval and not confirm_real_destination:
            raise AppShellError(review.message)

        try:
            result = execute_sandbox_install_plan_service(plan)
            completed_result = replace(result, destination_kind=plan.destination_kind)
            self._record_completed_install_operation(plan=plan, result=completed_result)
            return completed_result
        except SandboxFileLockError as exc:
            raise AppShellError(str(exc), detail_message=exc.technical_detail) from exc
        except SandboxInstallError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Sandbox install failed: {exc}") from exc

    def build_mod_removal_plan(
        self,
        *,
        scan_target: ScanTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        mod_folder_path_text: str,
    ) -> ModRemovalPlan:
        destination_mods_path, destination_archive_path = self._resolve_install_destination_paths(
            install_target=scan_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
        )

        configured_real_mods_path: Path | None = None
        if configured_mods_path_text.strip():
            configured_real_mods_path = self._parse_and_validate_mods_path(configured_mods_path_text)

        safety = self.evaluate_install_target_safety(
            install_target=scan_target,
            destination_mods_path=destination_mods_path,
            configured_real_mods_path=configured_real_mods_path,
        )
        if not safety.allowed:
            assert safety.message is not None
            raise AppShellError(safety.message)

        raw_target = mod_folder_path_text.strip()
        if not raw_target:
            raise AppShellError("Select an installed mod row first.")

        target_mod_path = Path(raw_target).expanduser()
        if not target_mod_path.exists() or not target_mod_path.is_dir():
            raise AppShellError(f"Selected mod folder is not accessible: {target_mod_path}")

        mods_root_resolved = destination_mods_path.resolve()
        target_resolved = target_mod_path.resolve()
        if target_resolved.parent != mods_root_resolved:
            raise AppShellError(
                "Selected mod folder must be a direct child of the selected Mods destination."
            )

        return ModRemovalPlan(
            destination_kind=scan_target,
            mods_path=destination_mods_path,
            archive_path=destination_archive_path,
            target_mod_path=target_mod_path,
        )

    def execute_mod_removal(
        self,
        plan: ModRemovalPlan,
        *,
        confirm_removal: bool = False,
    ) -> ModRemovalResult:
        if not confirm_removal:
            raise AppShellError("Explicit confirmation is required before mod removal.")

        try:
            archived_target = remove_mod_to_archive_service(
                target_mod_path=plan.target_mod_path,
                mods_root=plan.mods_path,
                archive_root=plan.archive_path,
            )
            inventory = scan_mods_directory(
                plan.mods_path,
                excluded_paths=(plan.archive_path, plan.mods_path / _LEGACY_ARCHIVE_DIRNAME),
            )
        except SandboxFileLockError as exc:
            raise AppShellError(str(exc), detail_message=exc.technical_detail) from exc
        except SandboxInstallError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Mod removal failed: {exc}") from exc

        return ModRemovalResult(
            plan=plan,
            removed_target=plan.target_mod_path,
            archived_target=archived_target,
            scan_context_path=plan.mods_path,
            inventory=inventory,
            destination_kind=plan.destination_kind,
        )

    def list_archived_entries(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> tuple[ArchivedModEntry, ...]:
        real_mods_path = self._resolve_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        real_archive_path = self._resolve_archive_path_for_source(
            source_kind=ARCHIVE_SOURCE_REAL,
            real_mods_path=real_mods_path,
            sandbox_mods_path=None,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )

        entries = list(
            list_archived_mod_entries(
                archive_root=real_archive_path,
                source_kind=ARCHIVE_SOURCE_REAL,
            )
        )

        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is not None:
            sandbox_archive_path = self._resolve_archive_path_for_source(
                source_kind=ARCHIVE_SOURCE_SANDBOX,
                real_mods_path=real_mods_path,
                sandbox_mods_path=sandbox_mods_path,
                real_archive_path_text=real_archive_path_text,
                sandbox_archive_path_text=sandbox_archive_path_text,
                existing_config=existing_config,
            )
            entries.extend(
                list_archived_mod_entries(
                    archive_root=sandbox_archive_path,
                    source_kind=ARCHIVE_SOURCE_SANDBOX,
                )
            )

        entries.sort(
            key=lambda entry: (
                0 if entry.source_kind == ARCHIVE_SOURCE_REAL else 1,
                entry.target_folder_name.casefold(),
                entry.archived_folder_name.casefold(),
            )
        )
        return _annotate_archive_retention_entries(
            tuple(entries),
            keep_latest_count=ARCHIVE_RETENTION_KEEP_LATEST_COUNT,
        )

    def build_archive_restore_plan(
        self,
        *,
        source_kind: ArchiveSourceKind,
        archived_path_text: str,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> ArchiveRestorePlan:
        if source_kind not in {ARCHIVE_SOURCE_REAL, ARCHIVE_SOURCE_SANDBOX}:
            raise AppShellError(f"Unknown archive source: {source_kind}")

        restore_target = self._infer_restore_target_from_source(source_kind)
        destination_mods_path, destination_archive_path = self._resolve_install_destination_paths(
            install_target=restore_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
        )

        configured_real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        safety = self.evaluate_install_target_safety(
            install_target=restore_target,
            destination_mods_path=destination_mods_path,
            configured_real_mods_path=configured_real_mods_path,
        )
        if not safety.allowed:
            assert safety.message is not None
            raise AppShellError(safety.message)

        archived_entry = self._resolve_archived_entry(
            source_kind=source_kind,
            archived_path_text=archived_path_text,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        destination_target_path = destination_mods_path / archived_entry.target_folder_name
        if destination_target_path.exists():
            raise AppShellError(
                f"Restore target already exists in destination Mods directory: {destination_target_path}"
            )

        return ArchiveRestorePlan(
            entry=archived_entry,
            destination_kind=restore_target,
            destination_mods_path=destination_mods_path,
            destination_target_path=destination_target_path,
            scan_excluded_paths=(
                destination_archive_path,
                destination_mods_path / _LEGACY_ARCHIVE_DIRNAME,
            ),
        )

    def execute_archive_restore(
        self,
        plan: ArchiveRestorePlan,
        *,
        confirm_restore: bool = False,
    ) -> ArchiveRestoreResult:
        if not confirm_restore:
            raise AppShellError("Explicit confirmation is required before archive restore.")

        try:
            restored_target = restore_archived_mod_entry(
                archive_root=plan.entry.archive_root,
                archived_path=plan.entry.archived_path,
                destination_mods_root=plan.destination_mods_path,
                destination_folder_name=plan.entry.target_folder_name,
            )
            inventory = scan_mods_directory(
                plan.destination_mods_path,
                excluded_paths=plan.scan_excluded_paths,
            )
        except ArchiveManagerError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Archive restore failed: {exc}") from exc

        return ArchiveRestoreResult(
            plan=plan,
            restored_target=restored_target,
            scan_context_path=plan.destination_mods_path,
            inventory=inventory,
            destination_kind=plan.destination_kind,
        )

    def build_archive_delete_plan(
        self,
        *,
        source_kind: ArchiveSourceKind,
        archived_path_text: str,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> ArchiveDeletePlan:
        if source_kind not in {ARCHIVE_SOURCE_REAL, ARCHIVE_SOURCE_SANDBOX}:
            raise AppShellError(f"Unknown archive source: {source_kind}")

        archived_entry = self._resolve_archived_entry(
            source_kind=source_kind,
            archived_path_text=archived_path_text,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        return ArchiveDeletePlan(entry=archived_entry)

    def execute_archive_delete(
        self,
        plan: ArchiveDeletePlan,
        *,
        confirm_delete: bool = False,
    ) -> ArchiveDeleteResult:
        if not confirm_delete:
            raise AppShellError("Explicit confirmation is required before permanent archive delete.")

        try:
            deleted_path = delete_archived_mod_entry(
                archive_root=plan.entry.archive_root,
                archived_path=plan.entry.archived_path,
            )
        except ArchiveManagerError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Permanent archive delete failed: {exc}") from exc

        return ArchiveDeleteResult(
            plan=plan,
            deleted_path=deleted_path,
        )

    def build_archive_cleanup_plan(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None = None,
        keep_latest_count: int = ARCHIVE_RETENTION_KEEP_LATEST_COUNT,
    ) -> ArchiveCleanupPlan:
        if keep_latest_count < 1:
            raise AppShellError("Archive retention keep count must be at least 1.")

        entries = self.list_archived_entries(
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        entries = _annotate_archive_retention_entries(
            entries,
            keep_latest_count=keep_latest_count,
        )
        cleanup_entries = tuple(
            entry for entry in entries if entry.retention_cleanup_candidate
        )
        if not cleanup_entries:
            raise AppShellError(
                f"No archive cleanup candidates found. Keep latest {keep_latest_count} per mod is already satisfied."
            )

        groups = _build_archive_retention_groups(
            entries,
            keep_latest_count=keep_latest_count,
            only_cleanup_groups=True,
        )
        return ArchiveCleanupPlan(
            retention_keep_limit=keep_latest_count,
            entries_to_delete=cleanup_entries,
            groups=groups,
        )

    def execute_archive_cleanup(
        self,
        plan: ArchiveCleanupPlan,
        *,
        confirm_cleanup: bool = False,
    ) -> ArchiveCleanupResult:
        if not confirm_cleanup:
            raise AppShellError("Explicit confirmation is required before archive cleanup.")

        deleted_paths: list[Path] = []
        for entry in plan.entries_to_delete:
            try:
                deleted_path = delete_archived_mod_entry(
                    archive_root=entry.archive_root,
                    archived_path=entry.archived_path,
                )
            except ArchiveManagerError as exc:
                if deleted_paths:
                    raise AppShellError(
                        "Archive cleanup partially completed before failing on "
                        f"{entry.archived_path}: {exc}. Older copies already deleted: "
                        f"{len(deleted_paths)}."
                    ) from exc
                raise AppShellError(str(exc)) from exc
            except OSError as exc:
                if deleted_paths:
                    raise AppShellError(
                        "Archive cleanup partially completed before failing on "
                        f"{entry.archived_path}: {exc}. Older copies already deleted: "
                        f"{len(deleted_paths)}."
                    ) from exc
                raise AppShellError(f"Archive cleanup failed: {exc}") from exc
            deleted_paths.append(deleted_path)

        return ArchiveCleanupResult(
            plan=plan,
            deleted_paths=tuple(deleted_paths),
        )

    def list_mod_rollback_candidates(
        self,
        *,
        scan_target: ScanTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        mod_folder_path_text: str,
        mod_unique_id_text: str,
        existing_config: AppConfig | None = None,
    ) -> tuple[ArchivedModEntry, ...]:
        source_kind = self._archive_source_for_scan_target(scan_target)
        mods_path, archive_path = self._resolve_install_destination_paths(
            install_target=scan_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
        )
        target_mod_path = self._parse_and_validate_selected_mod_path(
            mods_path=mods_path,
            mod_folder_path_text=mod_folder_path_text,
        )
        unique_id = mod_unique_id_text.strip()
        if not unique_id:
            raise AppShellError("Selected installed mod does not include a valid UniqueID.")

        all_entries = list_archived_mod_entries(
            archive_root=archive_path,
            source_kind=source_kind,
        )
        unique_key = canonicalize_unique_id(unique_id)
        folder_key = target_mod_path.name.casefold()
        candidates = tuple(
            entry
            for entry in all_entries
            if entry.unique_id is not None
            and canonicalize_unique_id(entry.unique_id) == unique_key
            and entry.target_folder_name.casefold() == folder_key
        )
        return tuple(
            sorted(
                candidates,
                key=lambda entry: (
                    _version_sort_key(entry.version),
                    entry.archived_folder_name.casefold(),
                ),
                reverse=True,
            )
        )

    def build_mod_rollback_plan(
        self,
        *,
        scan_target: ScanTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        mod_folder_path_text: str,
        mod_unique_id_text: str,
        mod_version_text: str,
        archived_candidate_path_text: str,
        existing_config: AppConfig | None = None,
    ) -> ModRollbackPlan:
        _ = existing_config
        source_kind = self._archive_source_for_scan_target(scan_target)
        mods_path, archive_path = self._resolve_install_destination_paths(
            install_target=scan_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
        )
        target_mod_path = self._parse_and_validate_selected_mod_path(
            mods_path=mods_path,
            mod_folder_path_text=mod_folder_path_text,
        )
        unique_id = mod_unique_id_text.strip()
        if not unique_id:
            raise AppShellError("Selected installed mod does not include a valid UniqueID.")

        candidate_path_text = archived_candidate_path_text.strip()
        if not candidate_path_text:
            raise AppShellError("Select an archived rollback candidate first.")
        candidate_path = Path(candidate_path_text).expanduser()

        candidates = self.list_mod_rollback_candidates(
            scan_target=scan_target,
            configured_mods_path_text=configured_mods_path_text,
            sandbox_mods_path_text=sandbox_mods_path_text,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            mod_folder_path_text=str(target_mod_path),
            mod_unique_id_text=unique_id,
        )
        selected_candidate: ArchivedModEntry | None = None
        for candidate in candidates:
            if _paths_deterministically_match(candidate.archived_path, candidate_path):
                selected_candidate = candidate
                break
        if selected_candidate is None:
            raise AppShellError(
                f"Selected archived rollback candidate is not a safe match: {candidate_path}"
            )

        current_archive_path = allocate_archive_destination(
            archive_root=archive_path,
            target_folder_name=target_mod_path.name,
        )
        return ModRollbackPlan(
            destination_kind=scan_target,
            mods_path=mods_path,
            archive_path=archive_path,
            current_mod_path=target_mod_path,
            current_unique_id=unique_id,
            current_version=mod_version_text.strip() or "<unknown>",
            rollback_entry=selected_candidate,
            current_archive_path=current_archive_path,
        )

    def execute_mod_rollback(
        self,
        plan: ModRollbackPlan,
        *,
        confirm_rollback: bool = False,
    ) -> ModRollbackResult:
        if not confirm_rollback:
            raise AppShellError("Explicit confirmation is required before rollback.")

        try:
            archived_current_target, restored_target = rollback_installed_mod_from_archive(
                current_mod_path=plan.current_mod_path,
                mods_root=plan.mods_path,
                archive_root=plan.archive_path,
                archived_candidate_path=plan.rollback_entry.archived_path,
            )
            inventory = scan_mods_directory(
                plan.mods_path,
                excluded_paths=(plan.archive_path, plan.mods_path / _LEGACY_ARCHIVE_DIRNAME),
            )
        except ArchiveManagerError as exc:
            raise AppShellError(str(exc)) from exc
        except OSError as exc:
            raise AppShellError(f"Mod rollback failed: {exc}") from exc

        return ModRollbackResult(
            plan=plan,
            archived_current_target=archived_current_target,
            restored_target=restored_target,
            scan_context_path=plan.mods_path,
            inventory=inventory,
            destination_kind=plan.destination_kind,
        )

    def evaluate_install_target_safety(
        self,
        *,
        install_target: InstallTargetKind,
        destination_mods_path: Path,
        configured_real_mods_path: Path | None,
    ) -> InstallTargetSafetyDecision:
        if install_target not in {INSTALL_TARGET_SANDBOX_MODS, INSTALL_TARGET_CONFIGURED_REAL_MODS}:
            return InstallTargetSafetyDecision(
                allowed=False,
                message=f"Unknown install target: {install_target}",
                requires_explicit_confirmation=False,
            )

        if configured_real_mods_path is None:
            if install_target == INSTALL_TARGET_SANDBOX_MODS:
                return InstallTargetSafetyDecision(
                    allowed=True,
                    message="Sandbox destination selected.",
                    requires_explicit_confirmation=False,
                )
            return InstallTargetSafetyDecision(
                allowed=False,
                message="Configured real Mods path is required for destination safety checks.",
                requires_explicit_confirmation=False,
            )

        if install_target == INSTALL_TARGET_SANDBOX_MODS:
            if _paths_deterministically_match(destination_mods_path, configured_real_mods_path):
                return InstallTargetSafetyDecision(
                    allowed=False,
                    message=(
                        "Sandbox install target matches configured real Mods path. "
                        "Select sandbox destination or choose a different path."
                    ),
                    requires_explicit_confirmation=False,
                )

            return InstallTargetSafetyDecision(
                allowed=True,
                message="Sandbox destination selected.",
                requires_explicit_confirmation=False,
            )

        if not _paths_deterministically_match(destination_mods_path, configured_real_mods_path):
            return InstallTargetSafetyDecision(
                allowed=False,
                message=(
                    "Real install destination must exactly match the configured real Mods path."
                ),
                requires_explicit_confirmation=False,
            )

        return InstallTargetSafetyDecision(
            allowed=True,
            message="Real game Mods destination selected. Explicit confirmation required before install.",
            requires_explicit_confirmation=True,
        )

    def _build_config(
        self,
        *,
        game_path: Path,
        mods_path: Path,
        existing_config: AppConfig | None,
    ) -> AppConfig:
        if existing_config is not None:
            return AppConfig(
                game_path=game_path,
                mods_path=mods_path,
                app_data_path=existing_config.app_data_path,
                sandbox_mods_path=existing_config.sandbox_mods_path,
                sandbox_archive_path=existing_config.sandbox_archive_path,
                real_archive_path=existing_config.real_archive_path,
                watched_downloads_path=existing_config.watched_downloads_path,
                secondary_watched_downloads_path=existing_config.secondary_watched_downloads_path,
                nexus_api_key=existing_config.nexus_api_key,
                scan_target=existing_config.scan_target,
                install_target=existing_config.install_target,
                steam_auto_start_enabled=existing_config.steam_auto_start_enabled,
            )

        return AppConfig(
            game_path=game_path,
            mods_path=mods_path,
            app_data_path=self._state_file.parent,
            scan_target=SCAN_TARGET_CONFIGURED_REAL_MODS,
            install_target=INSTALL_TARGET_SANDBOX_MODS,
        )

    @staticmethod
    def _resolve_nexus_api_key(
        *,
        nexus_api_key_text: str,
        existing_config: AppConfig | None,
        allow_environment_fallback: bool = True,
    ) -> str | None:
        api_key, _ = AppShellService._resolve_nexus_api_key_with_source(
            nexus_api_key_text=nexus_api_key_text,
            existing_config=existing_config,
            allow_environment_fallback=allow_environment_fallback,
        )
        return api_key

    @staticmethod
    def _resolve_nexus_api_key_with_source(
        *,
        nexus_api_key_text: str,
        existing_config: AppConfig | None,
        allow_environment_fallback: bool,
    ) -> tuple[str | None, str]:
        entered = normalize_nexus_api_key(nexus_api_key_text)
        if entered:
            return entered, "entered"

        if existing_config is not None:
            saved = normalize_nexus_api_key(existing_config.nexus_api_key)
            if saved:
                return saved, "saved_config"

        if allow_environment_fallback:
            env_value = normalize_nexus_api_key(os.getenv(NEXUS_API_KEY_ENV, ""))
            if env_value:
                return env_value, "environment"

        return None, "none"

    def _resolve_real_mods_path(
        self,
        *,
        configured_mods_path_text: str,
        existing_config: AppConfig | None,
    ) -> Path:
        if configured_mods_path_text.strip():
            return self._parse_and_validate_mods_path(configured_mods_path_text)
        if existing_config is not None:
            return self._parse_and_validate_existing_directory(
                existing_config.mods_path,
                "Saved configured real Mods path is not accessible",
            )
        raise AppShellError("Configured real Mods directory is required.")

    def _resolve_optional_real_mods_path(
        self,
        *,
        configured_mods_path_text: str,
        existing_config: AppConfig | None,
    ) -> Path | None:
        if configured_mods_path_text.strip():
            return self._parse_and_validate_mods_path(configured_mods_path_text)
        if existing_config is not None:
            return self._parse_and_validate_existing_directory(
                existing_config.mods_path,
                "Saved configured real Mods path is not accessible",
            )
        return None

    def _resolve_optional_sandbox_mods_path(
        self,
        *,
        sandbox_mods_path_text: str,
        existing_config: AppConfig | None,
    ) -> Path | None:
        if sandbox_mods_path_text.strip():
            return self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
        if existing_config is not None and existing_config.sandbox_mods_path is not None:
            return self._parse_and_validate_existing_directory(
                existing_config.sandbox_mods_path,
                "Saved sandbox Mods path is not accessible",
            )
        return None

    def _resolve_sandbox_dev_launch_context(
        self,
        *,
        game_path_text: str,
        sandbox_mods_path_text: str,
        configured_mods_path_text: str,
        existing_config: AppConfig | None,
    ) -> tuple[Path, Path, LaunchCommand]:
        game_path = self._resolve_game_path(game_path_text, existing_config)
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required for sandbox dev launch.")
        sandbox_mods_path = self._prepare_canonical_sandbox_profile_library(sandbox_mods_path)
        catalog = self.load_sandbox_mod_profiles()
        active_mods_path, updated_catalog, _ = self._resolve_selected_sandbox_profile_path(
            catalog=catalog,
            sandbox_mods_path=sandbox_mods_path,
            requested_profile_id=None,
        )
        if updated_catalog != catalog:
            self._save_normalized_sandbox_profile_catalog(updated_catalog)

        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is not None and _paths_deterministically_match(
            active_mods_path,
            real_mods_path,
        ):
            raise AppShellError(
                "Sandbox dev launch is blocked: sandbox Mods path matches the configured real Mods path."
            )

        try:
            command = resolve_launch_command(game_path=game_path, mode="smapi")
        except GameLaunchError as exc:
            raise AppShellError(str(exc)) from exc

        if command.executable_path.suffix.casefold() == ".sh":
            raise AppShellError(
                "Sandbox dev launch requires a direct SMAPI executable target; shell-script SMAPI wrappers are not supported in this stage."
            )

        sandbox_command = LaunchCommand(
            mode=command.mode,
            executable_path=command.executable_path,
            argv=(*command.argv, "--mods-path", str(active_mods_path)),
        )
        return game_path, active_mods_path, sandbox_command

    def _resolve_real_smapi_launch_command(
        self,
        *,
        game_path: Path,
        configured_mods_path_text: str,
        existing_config: AppConfig | None,
    ) -> LaunchCommand:
        try:
            command = resolve_launch_command(game_path=game_path, mode="smapi")
        except GameLaunchError as exc:
            raise AppShellError(str(exc)) from exc

        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            return command

        catalog = self.load_real_mod_profiles()
        active_mods_path, updated_catalog, profile = self._resolve_selected_real_profile_path(
            catalog=catalog,
            real_mods_path=real_mods_path,
            requested_profile_id=None,
        )
        if updated_catalog != catalog:
            self._save_normalized_real_profile_catalog(updated_catalog)
        if profile.is_default:
            return command

        if command.executable_path.suffix.casefold() == ".sh":
            raise AppShellError(
                "Real profile launch requires a direct SMAPI executable target; shell-script SMAPI wrappers are not supported in this stage."
            )

        return LaunchCommand(
            mode=command.mode,
            executable_path=command.executable_path,
            argv=(str(command.executable_path), "--mods-path", str(active_mods_path)),
        )

    def _resolve_sandbox_mod_sync_context(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None,
    ) -> tuple[Path, Path, tuple[Path, ...]]:
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            raise AppShellError("Configured real Mods directory is required for sandbox sync.")

        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required for sandbox sync.")

        if _paths_deterministically_match(real_mods_path, sandbox_mods_path):
            raise AppShellError(
                "Sandbox sync is blocked: sandbox Mods path matches the configured real Mods path."
            )

        source_paths = self._resolve_selected_real_mod_paths(
            real_mods_path=real_mods_path,
            selected_mod_folder_paths_text=selected_mod_folder_paths_text,
        )

        conflicting_targets = tuple(
            sandbox_mods_path / source_path.name
            for source_path in source_paths
            if (sandbox_mods_path / source_path.name).exists()
        )
        if conflicting_targets:
            conflict_names = ", ".join(target.name for target in conflicting_targets[:3])
            if len(conflicting_targets) == 1:
                raise AppShellError(
                    "Sandbox sync blocked: sandbox target already exists for "
                    f"{conflict_names}. Remove or archive the sandbox copy first."
                )
            raise AppShellError(
                "Sandbox sync blocked: sandbox targets already exist for "
                f"{conflict_names}. Remove or archive those sandbox copies first."
            )

        return real_mods_path, sandbox_mods_path, source_paths

    def _resolve_sandbox_mod_promotion_context(
        self,
        *,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        selected_mod_folder_paths_text: Iterable[str],
        existing_config: AppConfig | None,
    ) -> tuple[Path, Path, Path, tuple[Path, ...], ModsInventory]:
        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        if real_mods_path is None:
            raise AppShellError("Configured real Mods directory is required for sandbox promotion.")

        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        if sandbox_mods_path is None:
            raise AppShellError("Sandbox Mods directory is required for sandbox promotion.")

        if _paths_deterministically_match(real_mods_path, sandbox_mods_path):
            raise AppShellError(
                "Sandbox promotion is blocked: sandbox Mods path matches the configured real Mods path."
            )

        archive_path = self._parse_and_validate_archive_path(
            archive_path_text=real_archive_path_text,
            destination_mods_path=real_mods_path,
            field_label="Real Mods archive path",
            default_archive_dir_name=_DEFAULT_REAL_ARCHIVE_DIRNAME,
        )

        source_paths = self._resolve_selected_sandbox_mod_paths(
            sandbox_mods_path=sandbox_mods_path,
            selected_mod_folder_paths_text=selected_mod_folder_paths_text,
        )
        source_inventory = scan_mods_directory(
            sandbox_mods_path,
            excluded_paths=(sandbox_mods_path / _LEGACY_ARCHIVE_DIRNAME,),
        )
        return real_mods_path, sandbox_mods_path, archive_path, source_paths, source_inventory

    def _build_sandbox_mods_promotion_plan(
        self,
        *,
        real_mods_path: Path,
        sandbox_mods_path: Path,
        archive_path: Path,
        source_paths: tuple[Path, ...],
        source_inventory: ModsInventory,
    ) -> SandboxInstallPlan:
        selected_mods_by_path = {
            str(mod.folder_path): mod
            for mod in source_inventory.mods
            if str(mod.folder_path) in {str(path) for path in source_paths}
        }
        entries: list[SandboxInstallPlanEntry] = []
        has_replace_entries = False

        for source_path in source_paths:
            target_path = real_mods_path / source_path.name
            target_exists = target_path.exists()
            archive_target_path: Path | None = None
            action = INSTALL_NEW
            warnings = ["Promoted from sandbox Mods selection via explicit managed action."]
            source_mod = selected_mods_by_path.get(str(source_path))
            if source_mod is None:
                manifest_result = parse_manifest_file(source_path / "manifest.json", source_path)
                if manifest_result.manifest is None:
                    raise AppShellError(
                        "Could not resolve a manifest for the selected sandbox mod folder."
                    )
                source_name = manifest_result.manifest.name
                source_unique_id = manifest_result.manifest.unique_id
                source_version = manifest_result.manifest.version
                source_manifest_path = str(source_path / "manifest.json")
            else:
                source_name = source_mod.name
                source_unique_id = source_mod.unique_id
                source_version = source_mod.version
                source_manifest_path = str(source_mod.manifest_path)

            if target_exists:
                has_replace_entries = True
                action = OVERWRITE_WITH_ARCHIVE
                archive_target_path = _build_archive_destination_service(
                    archive_root=archive_path,
                    target_folder_name=target_path.name,
                )
                warnings.append(
                    "Existing REAL Mods target will be archived before replacement."
                )

            entries.append(
                SandboxInstallPlanEntry(
                    name=source_name,
                    unique_id=source_unique_id,
                    version=source_version,
                    source_package_path=source_path,
                    source_manifest_path=source_manifest_path,
                    source_root_path=str(source_path),
                    target_path=target_path,
                    action=action,
                    target_exists=target_exists,
                    archive_path=archive_target_path,
                    can_install=True,
                    warnings=tuple(warnings),
                )
            )

        entries.sort(key=lambda item: (item.target_path.name.lower(), item.unique_id.casefold()))
        plan_warnings = [
            "Sandbox promotion writes into the configured real Mods path.",
        ]
        if has_replace_entries:
            plan_warnings.append(
                "Conflicting live targets will be archived before replacement."
            )
            plan_warnings.append(
                "Recovery remains per-entry and depends on recorded archive history."
            )

        return SandboxInstallPlan(
            package_path=_promotion_history_source_marker(
                sandbox_mods_path=sandbox_mods_path,
                source_paths=source_paths,
            ),
            sandbox_mods_path=real_mods_path,
            sandbox_archive_path=archive_path,
            entries=tuple(entries),
            package_findings=tuple(),
            package_warnings=tuple(),
            plan_warnings=tuple(plan_warnings),
            dependency_findings=tuple(),
            remote_requirements=tuple(),
            destination_kind=INSTALL_TARGET_CONFIGURED_REAL_MODS,
        )

    def _rollback_sandbox_mods_promotion_entries(
        self,
        entries: tuple[SandboxInstallPlanEntry, ...],
    ) -> tuple[str, ...]:
        errors: list[str] = []
        for entry in reversed(entries):
            if entry.action == INSTALL_NEW:
                if not entry.target_path.exists():
                    continue
                try:
                    _remove_path_for_promotion_rollback(entry.target_path)
                except OSError as exc:
                    errors.append(
                        f"could not remove promoted target {entry.target_path}: {exc}"
                    )
                continue

            if entry.action == OVERWRITE_WITH_ARCHIVE:
                archive_path = entry.archive_path
                if entry.target_path.exists():
                    try:
                        _remove_path_for_promotion_rollback(entry.target_path)
                    except OSError as exc:
                        errors.append(
                            f"could not remove replaced target {entry.target_path}: {exc}"
                        )
                        continue

                if archive_path is None:
                    errors.append(
                        f"missing archive path for rollback of {entry.target_path}"
                    )
                    continue
                if not archive_path.exists():
                    errors.append(
                        f"archived target is missing for rollback of {entry.target_path}: "
                        f"{archive_path}"
                    )
                    continue
                try:
                    archive_path.rename(entry.target_path)
                except OSError as exc:
                    errors.append(
                        f"could not restore archived target {archive_path} -> "
                        f"{entry.target_path}: {exc}"
                    )
        return tuple(errors)

    def _remaining_sandbox_mods_promotion_state(
        self,
        entries: tuple[SandboxInstallPlanEntry, ...],
    ) -> tuple[
        tuple[SandboxInstallPlanEntry, ...],
        tuple[Path, ...],
        tuple[Path, ...],
    ]:
        remaining_entries: list[SandboxInstallPlanEntry] = []
        installed_targets: list[Path] = []
        archived_targets: list[Path] = []

        for entry in entries:
            if entry.action == INSTALL_NEW:
                if not entry.target_path.exists():
                    continue
                remaining_entries.append(
                    replace(
                        entry,
                        warnings=entry.warnings
                        + (
                            "Partial sandbox promotion failure: rollback did not remove this REAL Mods target.",
                        ),
                    )
                )
                installed_targets.append(entry.target_path)
                continue

            if entry.action != OVERWRITE_WITH_ARCHIVE:
                continue

            archive_exists = entry.archive_path is not None and entry.archive_path.exists()
            target_exists = entry.target_path.exists()
            if not archive_exists and not target_exists:
                continue

            remaining_entries.append(
                replace(
                    entry,
                    warnings=entry.warnings
                    + (
                        "Partial sandbox promotion failure: rollback did not fully restore this REAL Mods target.",
                    ),
                )
            )
            if target_exists:
                installed_targets.append(entry.target_path)
            if archive_exists and entry.archive_path is not None:
                archived_targets.append(entry.archive_path)

        remaining_entries.sort(
            key=lambda item: (item.target_path.name.lower(), item.unique_id.casefold())
        )
        return (
            tuple(remaining_entries),
            tuple(sorted(installed_targets, key=lambda path: path.name.lower())),
            tuple(sorted(archived_targets, key=lambda path: path.name.lower())),
        )

    def _resolve_selected_real_mod_paths(
        self,
        *,
        real_mods_path: Path,
        selected_mod_folder_paths_text: Iterable[str],
    ) -> tuple[Path, ...]:
        deduplicated_paths: list[Path] = []
        seen_keys: set[str] = set()
        for raw_value in selected_mod_folder_paths_text:
            path_text = str(raw_value).strip()
            if not path_text:
                continue
            source_path = Path(path_text).expanduser()
            key = str(source_path.resolve(strict=False))
            if os.name == "nt":
                key = key.casefold()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduplicated_paths.append(source_path)

        if not deduplicated_paths:
            raise AppShellError("Select at least one installed mod row to sync to sandbox.")

        validated_paths = [
            self._parse_and_validate_selected_mod_path(
                mods_path=real_mods_path,
                mod_folder_path_text=str(source_path),
            )
            for source_path in deduplicated_paths
        ]
        return tuple(validated_paths)

    def _resolve_selected_sandbox_mod_paths(
        self,
        *,
        sandbox_mods_path: Path,
        selected_mod_folder_paths_text: Iterable[str],
    ) -> tuple[Path, ...]:
        deduplicated_paths: list[Path] = []
        seen_keys: set[str] = set()
        for raw_value in selected_mod_folder_paths_text:
            path_text = str(raw_value).strip()
            if not path_text:
                continue
            source_path = Path(path_text).expanduser()
            key = str(source_path.resolve(strict=False))
            if os.name == "nt":
                key = key.casefold()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduplicated_paths.append(source_path)

        if not deduplicated_paths:
            raise AppShellError("Select at least one installed sandbox mod row to promote.")

        validated_paths = [
            self._parse_and_validate_selected_mod_path(
                mods_path=sandbox_mods_path,
                mod_folder_path_text=str(source_path),
            )
            for source_path in deduplicated_paths
        ]
        return tuple(validated_paths)

    def _resolve_archive_path_for_source(
        self,
        *,
        source_kind: ArchiveSourceKind,
        real_mods_path: Path | None,
        sandbox_mods_path: Path | None,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None,
    ) -> Path:
        if source_kind == ARCHIVE_SOURCE_REAL:
            if real_mods_path is None:
                raise AppShellError("Configured real Mods directory is required for real archive operations.")
            archive_text = real_archive_path_text
            if not archive_text.strip() and existing_config is not None and existing_config.real_archive_path:
                archive_text = str(existing_config.real_archive_path)
            return self._parse_and_validate_archive_path(
                archive_path_text=archive_text,
                destination_mods_path=real_mods_path,
                field_label="Real Mods archive path",
                default_archive_dir_name=_DEFAULT_REAL_ARCHIVE_DIRNAME,
            )

        if source_kind == ARCHIVE_SOURCE_SANDBOX:
            if sandbox_mods_path is None:
                raise AppShellError("Sandbox Mods directory is required for sandbox archive operations.")
            archive_text = sandbox_archive_path_text
            if (
                not archive_text.strip()
                and existing_config is not None
                and existing_config.sandbox_archive_path is not None
            ):
                archive_text = str(existing_config.sandbox_archive_path)
            return self._parse_and_validate_archive_path(
                archive_path_text=archive_text,
                destination_mods_path=sandbox_mods_path,
                field_label="Sandbox archive path",
                default_archive_dir_name=_DEFAULT_SANDBOX_ARCHIVE_DIRNAME,
            )

        raise AppShellError(f"Unknown archive source: {source_kind}")

    def _resolve_archived_entry(
        self,
        *,
        source_kind: ArchiveSourceKind,
        archived_path_text: str,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
        existing_config: AppConfig | None,
    ) -> ArchivedModEntry:
        raw_archived_path = archived_path_text.strip()
        if not raw_archived_path:
            raise AppShellError("Archived entry path is required.")
        archived_path = Path(raw_archived_path).expanduser()

        real_mods_path = self._resolve_optional_real_mods_path(
            configured_mods_path_text=configured_mods_path_text,
            existing_config=existing_config,
        )
        sandbox_mods_path = self._resolve_optional_sandbox_mods_path(
            sandbox_mods_path_text=sandbox_mods_path_text,
            existing_config=existing_config,
        )
        archive_root = self._resolve_archive_path_for_source(
            source_kind=source_kind,
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            real_archive_path_text=real_archive_path_text,
            sandbox_archive_path_text=sandbox_archive_path_text,
            existing_config=existing_config,
        )
        entries = list_archived_mod_entries(
            archive_root=archive_root,
            source_kind=source_kind,
        )
        for entry in entries:
            if _paths_deterministically_match(entry.archived_path, archived_path):
                return entry

        raise AppShellError(
            f"Selected archived entry is not available in {source_kind}: {archived_path}"
        )

    def _resolve_install_destination_paths(
        self,
        *,
        install_target: InstallTargetKind,
        configured_mods_path_text: str,
        sandbox_mods_path_text: str,
        real_archive_path_text: str,
        sandbox_archive_path_text: str,
    ) -> tuple[Path, Path]:
        if install_target == INSTALL_TARGET_CONFIGURED_REAL_MODS:
            real_mods_path = self._parse_and_validate_mods_path(configured_mods_path_text)
            real_archive_path = self._parse_and_validate_archive_path(
                archive_path_text=real_archive_path_text,
                destination_mods_path=real_mods_path,
                field_label="Real Mods archive path",
                default_archive_dir_name=_DEFAULT_REAL_ARCHIVE_DIRNAME,
            )
            return real_mods_path, real_archive_path

        if install_target == INSTALL_TARGET_SANDBOX_MODS:
            sandbox_mods_path = self._parse_and_validate_sandbox_mods_path(sandbox_mods_path_text)
            sandbox_archive_path = self._parse_and_validate_archive_path(
                archive_path_text=sandbox_archive_path_text,
                destination_mods_path=sandbox_mods_path,
                field_label="Sandbox archive path",
                default_archive_dir_name=_DEFAULT_SANDBOX_ARCHIVE_DIRNAME,
            )
            return sandbox_mods_path, sandbox_archive_path

        raise AppShellError(f"Unknown install target: {install_target}")

    @staticmethod
    def _infer_restore_target_from_source(source_kind: ArchiveSourceKind) -> InstallTargetKind:
        if source_kind == ARCHIVE_SOURCE_REAL:
            return INSTALL_TARGET_CONFIGURED_REAL_MODS
        if source_kind == ARCHIVE_SOURCE_SANDBOX:
            return INSTALL_TARGET_SANDBOX_MODS
        raise AppShellError(
            f"Archive source '{source_kind}' has no reliable restore destination context."
        )

    @staticmethod
    def _resolve_game_path(game_path_text: str, existing_config: AppConfig | None) -> Path:
        raw_value = game_path_text.strip()
        if raw_value:
            return AppShellService._parse_and_validate_game_path(raw_value)
        if existing_config is not None:
            return AppShellService._parse_and_validate_existing_directory(
                existing_config.game_path,
                "Saved game path is not accessible",
            )
        raise AppShellError("Game directory is required")

    @staticmethod
    def _resolve_mods_path(mods_dir_text: str, game_path: Path) -> Path:
        raw_mods_text = mods_dir_text.strip()
        if raw_mods_text:
            return AppShellService._parse_and_validate_mods_path(raw_mods_text)

        derived_mods_path = derive_mods_path(game_path)
        if derived_mods_path.exists() and derived_mods_path.is_dir():
            return derived_mods_path
        raise AppShellError(
            f"Mods directory is required and could not be derived from game path: {derived_mods_path}"
        )

    @staticmethod
    def default_archive_path_for_destination(
        *,
        destination_mods_path: Path,
        default_archive_dir_name: str,
    ) -> Path:
        return destination_mods_path.parent / default_archive_dir_name

    @staticmethod
    def _resolve_scan_excluded_paths(
        *,
        scan_target: ScanTargetKind,
        scan_path: Path,
        configured_archive_text: str,
        configured_archive_fallback: Path | None,
    ) -> tuple[Path, ...]:
        candidates: list[Path] = []

        raw_archive = configured_archive_text.strip()
        if raw_archive:
            candidates.append(Path(raw_archive).expanduser())
        elif configured_archive_fallback is not None:
            candidates.append(configured_archive_fallback)
        else:
            default_archive_name = (
                _DEFAULT_REAL_ARCHIVE_DIRNAME
                if scan_target == SCAN_TARGET_CONFIGURED_REAL_MODS
                else _DEFAULT_SANDBOX_ARCHIVE_DIRNAME
            )
            candidates.append(
                AppShellService.default_archive_path_for_destination(
                    destination_mods_path=scan_path,
                    default_archive_dir_name=default_archive_name,
                )
            )

        # Legacy compatibility: previous versions defaulted archives inside Mods root.
        candidates.append(scan_path / _LEGACY_ARCHIVE_DIRNAME)

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path.expanduser().resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)

        return tuple(deduped)

    @staticmethod
    def _archive_source_for_scan_target(scan_target: ScanTargetKind) -> ArchiveSourceKind:
        if scan_target == SCAN_TARGET_CONFIGURED_REAL_MODS:
            return ARCHIVE_SOURCE_REAL
        if scan_target == SCAN_TARGET_SANDBOX_MODS:
            return ARCHIVE_SOURCE_SANDBOX
        raise AppShellError(f"Unknown scan target: {scan_target}")

    @staticmethod
    def _parse_and_validate_selected_mod_path(
        *,
        mods_path: Path,
        mod_folder_path_text: str,
    ) -> Path:
        raw_target = mod_folder_path_text.strip()
        if not raw_target:
            raise AppShellError("Select an installed mod row first.")

        target_mod_path = Path(raw_target).expanduser()
        if not target_mod_path.exists() or not target_mod_path.is_dir():
            raise AppShellError(f"Selected mod folder is not accessible: {target_mod_path}")

        mods_root_resolved = mods_path.resolve()
        target_resolved = target_mod_path.resolve()
        if target_resolved.parent != mods_root_resolved:
            raise AppShellError(
                "Selected mod folder must be a direct child of the selected Mods destination."
            )
        return target_mod_path

    @staticmethod
    def _parse_and_validate_game_path(game_path_text: str) -> Path:
        game_path = AppShellService._parse_game_path_text(game_path_text)
        if not game_path.exists():
            raise AppShellError(f"Game directory does not exist: {game_path}")
        if not game_path.is_dir():
            raise AppShellError(f"Game path is not a directory: {game_path}")

        return game_path

    @staticmethod
    def _parse_game_path_text(game_path_text: str) -> Path:
        raw_value = game_path_text.strip()
        if not raw_value:
            raise AppShellError("Game directory is required")

        game_path = Path(raw_value).expanduser()
        return game_path

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
    def _parse_and_validate_existing_directory(path: Path, message_prefix: str) -> Path:
        if not path.exists() or not path.is_dir():
            raise AppShellError(f"{message_prefix}: {path}")
        return path

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
        return AppShellService._parse_and_validate_archive_path(
            archive_path_text=sandbox_archive_path_text,
            destination_mods_path=sandbox_mods_path,
            field_label="Sandbox archive path",
            default_archive_dir_name=_DEFAULT_SANDBOX_ARCHIVE_DIRNAME,
        )

    @staticmethod
    def _parse_and_validate_archive_path(
        *,
        archive_path_text: str,
        destination_mods_path: Path,
        field_label: str,
        default_archive_dir_name: str,
    ) -> Path:
        raw_value = archive_path_text.strip()
        archive_path = (
            AppShellService.default_archive_path_for_destination(
                destination_mods_path=destination_mods_path,
                default_archive_dir_name=default_archive_dir_name,
            )
            if not raw_value
            else Path(raw_value).expanduser()
        )

        if archive_path.exists() and not archive_path.is_dir():
            raise AppShellError(f"{field_label} is not a directory: {archive_path}")

        if _is_path_within_or_equal(archive_path, destination_mods_path):
            raise AppShellError(
                f"{field_label} must be outside the active Mods directory: {archive_path}"
            )

        parent = archive_path.parent
        if not parent.exists() or not parent.is_dir():
            raise AppShellError(
                f"{field_label} parent directory is not accessible: {parent}"
            )

        return archive_path

    @staticmethod
    def _parse_and_validate_watched_downloads_path(
        *,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
    ) -> tuple[Path, ...]:
        watched_paths = []
        for raw_text in (
            watched_downloads_path_text.strip(),
            secondary_watched_downloads_path_text.strip(),
        ):
            if not raw_text:
                continue

            watched_path = Path(raw_text).expanduser()
            if not watched_path.exists():
                raise AppShellError(f"Watched downloads directory does not exist: {watched_path}")
            if not watched_path.is_dir():
                raise AppShellError(
                    f"Watched downloads path is not a directory: {watched_path}"
                )
            watched_paths.append(watched_path)

        if not watched_paths:
            raise AppShellError("At least one watched downloads directory is required")

        distinct_paths: list[Path] = []
        seen_paths: set[Path] = set()
        for watched_path in watched_paths:
            if watched_path in seen_paths:
                continue
            seen_paths.add(watched_path)
            distinct_paths.append(watched_path)
        return tuple(distinct_paths)

    @staticmethod
    def _format_watched_download_paths_for_guidance(
        *,
        watched_downloads_path_text: str,
        secondary_watched_downloads_path_text: str = "",
    ) -> str:
        watched_paths = []
        for raw_text in (
            watched_downloads_path_text.strip(),
            secondary_watched_downloads_path_text.strip(),
        ):
            if raw_text and raw_text not in watched_paths:
                watched_paths.append(raw_text)

        if not watched_paths:
            return "<set a watched downloads path first>"
        if len(watched_paths) == 1:
            return f"watched downloads path: {watched_paths[0]}"
        return "one watched downloads path:\n   - " + "\n   - ".join(watched_paths)

    @staticmethod
    def _parse_optional_directory(path_text: str) -> Path | None:
        raw_value = path_text.strip()
        if not raw_value:
            return None

        path = Path(raw_value).expanduser()
        if not path.exists():
            raise AppShellError(f"Directory does not exist: {path}")
        if not path.is_dir():
            raise AppShellError(f"Path is not a directory: {path}")

        return path

    @staticmethod
    def _effective_required_path_text(raw_text: str, fallback_path: Path) -> str:
        text = raw_text.strip()
        if text:
            return text
        return str(fallback_path)

    @staticmethod
    def _effective_optional_path_text(raw_text: str, fallback_path: Path | None) -> str:
        text = raw_text.strip()
        if text:
            return text
        if fallback_path is None:
            return ""
        return str(fallback_path)

    @staticmethod
    def _copied_directory_matches(source_path: Path, target_path: Path) -> bool:
        return _directory_copy_signature(source_path) == _directory_copy_signature(target_path)

    @staticmethod
    def _parse_optional_archive_directory(path_text: str) -> Path | None:
        raw_value = path_text.strip()
        if not raw_value:
            return None

        path = Path(raw_value).expanduser()
        if path.exists() and not path.is_dir():
            raise AppShellError(f"Real archive path is not a directory: {path}")
        if not path.parent.exists() or not path.parent.is_dir():
            raise AppShellError(
                f"Real archive parent directory is not accessible: {path.parent}"
            )
        return path

    def _build_restore_import_planning_local_targets(
        self,
        *,
        game_path_text: str,
        mods_dir_text: str,
        sandbox_mods_path_text: str,
        sandbox_archive_path_text: str,
        real_archive_path_text: str,
        existing_config: AppConfig | None,
        inspection: BackupBundleInspectionResult,
    ) -> _RestoreImportPlanningLocalTargets:
        game_path = self._resolve_restore_import_game_path(
            game_path_text=game_path_text,
            existing_config=existing_config,
        )
        real_mods_path = self._resolve_restore_import_real_mods_path(
            mods_dir_text=mods_dir_text,
            game_path=game_path,
            existing_config=existing_config,
        )
        sandbox_mods_path = self._resolve_restore_import_optional_path(
            sandbox_mods_path_text,
            fallback=(existing_config.sandbox_mods_path if existing_config is not None else None),
        )
        real_archive_path = self._resolve_restore_import_archive_path(
            archive_path_text=real_archive_path_text,
            fallback=(existing_config.real_archive_path if existing_config is not None else None),
            destination_mods_path=real_mods_path,
            default_archive_dir_name=_DEFAULT_REAL_ARCHIVE_DIRNAME,
        )
        sandbox_archive_path = self._resolve_restore_import_archive_path(
            archive_path_text=sandbox_archive_path_text,
            fallback=(
                existing_config.sandbox_archive_path if existing_config is not None else None
            ),
            destination_mods_path=sandbox_mods_path,
            default_archive_dir_name=_DEFAULT_SANDBOX_ARCHIVE_DIRNAME,
        )
        bundle_config, bundle_config_warning = self._load_backup_bundle_config_snapshot(
            inspection
        )
        return _RestoreImportPlanningLocalTargets(
            app_state_path=self._state_file,
            install_history_path=self._install_operation_history_file,
            recovery_history_path=self._recovery_execution_history_file,
            update_source_intent_overlay_path=self._update_source_intent_overlay_file,
            real_mods_path=real_mods_path,
            sandbox_mods_path=sandbox_mods_path,
            real_archive_path=real_archive_path,
            sandbox_archive_path=sandbox_archive_path,
            bundle_config=bundle_config,
            bundle_config_warning=bundle_config_warning,
        )

    @staticmethod
    def _resolve_restore_import_game_path(
        *,
        game_path_text: str,
        existing_config: AppConfig | None,
    ) -> Path | None:
        raw_value = game_path_text.strip()
        if raw_value:
            return Path(raw_value).expanduser()
        if existing_config is not None:
            return existing_config.game_path
        return None

    @staticmethod
    def _resolve_restore_import_real_mods_path(
        *,
        mods_dir_text: str,
        game_path: Path | None,
        existing_config: AppConfig | None,
    ) -> Path | None:
        raw_value = mods_dir_text.strip()
        if raw_value:
            return Path(raw_value).expanduser()
        if existing_config is not None:
            return existing_config.mods_path
        if game_path is not None:
            return derive_mods_path(game_path)
        return None

    @staticmethod
    def _resolve_restore_import_optional_path(
        path_text: str,
        *,
        fallback: Path | None,
    ) -> Path | None:
        raw_value = path_text.strip()
        if raw_value:
            return Path(raw_value).expanduser()
        return fallback

    @staticmethod
    def _resolve_restore_import_archive_path(
        *,
        archive_path_text: str,
        fallback: Path | None,
        destination_mods_path: Path | None,
        default_archive_dir_name: str,
    ) -> Path | None:
        raw_value = archive_path_text.strip()
        if raw_value:
            return Path(raw_value).expanduser()
        if fallback is not None:
            return fallback
        if destination_mods_path is not None:
            return AppShellService.default_archive_path_for_destination(
                destination_mods_path=destination_mods_path,
                default_archive_dir_name=default_archive_dir_name,
            )
        return None

    @staticmethod
    def _load_backup_bundle_config_snapshot(
        inspection: BackupBundleInspectionResult,
    ) -> tuple[AppConfig | None, str | None]:
        app_state_item = next(
            (item for item in inspection.items if item.key == "app_state"),
            None,
        )
        if app_state_item is None or app_state_item.structure_state != "present":
            return None, None

        config_path = _backup_bundle_content_root(inspection) / app_state_item.relative_path
        try:
            return load_app_config(config_path), None
        except AppStateStoreError as exc:
            return None, f"Bundle app-state snapshot could not be parsed: {exc}"

    def _prepare_zip_backup_bundle_content(
        self,
        bundle_path: Path,
    ) -> _PreparedBackupBundleZipContent:
        resolved_bundle_path = bundle_path.resolve()
        bundle_stat = resolved_bundle_path.stat()
        signature = (bundle_stat.st_mtime_ns, bundle_stat.st_size)
        cached = self._prepared_backup_bundle_zip_content.get(resolved_bundle_path)
        if (
            cached is not None
            and cached.signature == signature
            and cached.content_root_path.exists()
        ):
            return cached

        if cached is not None:
            cached.temp_dir.cleanup()
            self._prepared_backup_bundle_zip_content.pop(resolved_bundle_path, None)

        temp_dir = tempfile.TemporaryDirectory(prefix="cinderleaf-backup-zip-")
        extracted_root = Path(temp_dir.name)
        try:
            with zipfile.ZipFile(resolved_bundle_path) as bundle_zip:
                _extract_backup_bundle_zip_safely(bundle_zip, extracted_root)
        except Exception:
            temp_dir.cleanup()
            raise

        prepared = _PreparedBackupBundleZipContent(
            artifact_path=resolved_bundle_path,
            content_root_path=_resolve_extracted_backup_bundle_content_root(extracted_root),
            temp_dir=temp_dir,
            signature=signature,
        )
        self._prepared_backup_bundle_zip_content[resolved_bundle_path] = prepared
        return prepared

    @staticmethod
    def _resolve_existing_export_source(
        path: Path | None,
        *,
        field_label: str,
    ) -> _BackupBundleSourceResolution:
        if path is None:
            return _BackupBundleSourceResolution(
                path=None,
                missing_status="not_configured",
                note=f"No {field_label.lower()} is configured.",
            )
        if path.exists():
            return _BackupBundleSourceResolution(
                path=path,
                missing_status="configured_missing",
                note=None,
            )
        return _BackupBundleSourceResolution(
            path=path,
            missing_status="configured_missing",
            note=f"{field_label} is configured for export but does not exist yet.",
        )

    def _prepare_mod_config_snapshot_export_item(
        self,
        *,
        key: str,
        label: str,
        mods_source: _BackupBundleSourceResolution,
        excluded_paths: tuple[Path, ...],
        relative_path: Path,
        selected: bool = True,
    ) -> _PreparedModConfigSnapshot:
        if not selected:
            return _PreparedModConfigSnapshot(
                item=BackupBundleExportItem(
                    key=key,
                    label=label,
                    kind="directory",
                    status="not_present",
                    relative_path=relative_path,
                    source_path=mods_source.path,
                    note="Excluded by export selection.",
                )
            )

        mods_path = mods_source.path
        if mods_path is None:
            return _PreparedModConfigSnapshot(
                item=BackupBundleExportItem(
                    key=key,
                    label=label,
                    kind="directory",
                    status=mods_source.missing_status,
                    relative_path=relative_path,
                    source_path=None,
                    note=mods_source.note,
                )
            )

        if not mods_path.exists() or not mods_path.is_dir():
            return _PreparedModConfigSnapshot(
                item=BackupBundleExportItem(
                    key=key,
                    label=label,
                    kind="directory",
                    status=mods_source.missing_status,
                    relative_path=relative_path,
                    source_path=mods_path,
                    note=mods_source.note,
                )
            )

        snapshot_root, config_file_count, config_mod_count, warning = _build_mod_config_snapshot(
            mods_path=mods_path,
            excluded_paths=excluded_paths,
        )
        if snapshot_root is None:
            return _PreparedModConfigSnapshot(
                item=BackupBundleExportItem(
                    key=key,
                    label=label,
                    kind="directory",
                    status="not_present",
                    relative_path=relative_path,
                    source_path=None,
                    note=warning or f"No mod config artifacts were found under {mods_path}.",
                )
            )

        note = (
            f"{config_file_count} config artifact(s) from {config_mod_count} mod folder(s)."
        )
        if warning:
            note = f"{note} {warning}"
        return _PreparedModConfigSnapshot(
            item=BackupBundleExportItem(
                key=key,
                label=label,
                kind="directory",
                status="copied",
                relative_path=relative_path,
                source_path=snapshot_root,
                note=note,
            ),
            temp_root=snapshot_root,
        )

    @staticmethod
    def _allocate_backup_bundle_path(destination_root: Path) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        base_name = f"Cinderleaf-backup-{timestamp}"
        candidate = destination_root / base_name
        suffix = 2
        while candidate.exists():
            candidate = destination_root / f"{base_name}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _backup_bundle_item_plan(
        *,
        key: str,
        label: str,
        kind: Literal["file", "directory"],
        resolution: _BackupBundleSourceResolution,
        relative_path: Path,
        selected: bool = True,
    ) -> BackupBundleExportItem:
        source_path = resolution.path
        if not selected:
            return BackupBundleExportItem(
                key=key,
                label=label,
                kind=kind,
                status="not_present",
                relative_path=relative_path,
                source_path=source_path,
                note="Excluded by export selection.",
            )

        if source_path is None:
            return BackupBundleExportItem(
                key=key,
                label=label,
                kind=kind,
                status=resolution.missing_status,
                relative_path=relative_path,
                source_path=None,
                note=resolution.note,
            )

        if not source_path.exists():
            return BackupBundleExportItem(
                key=key,
                label=label,
                kind=kind,
                status=resolution.missing_status,
                relative_path=relative_path,
                source_path=source_path,
                note=resolution.note,
            )

        if kind == "file" and not source_path.is_file():
            return BackupBundleExportItem(
                key=key,
                label=label,
                kind=kind,
                status=resolution.missing_status,
                relative_path=relative_path,
                source_path=source_path,
                note=f"{label} exists but is not a file.",
            )

        if kind == "directory" and not source_path.is_dir():
            return BackupBundleExportItem(
                key=key,
                label=label,
                kind=kind,
                status=resolution.missing_status,
                relative_path=relative_path,
                source_path=source_path,
                note=f"{label} exists but is not a directory.",
            )

        return BackupBundleExportItem(
            key=key,
            label=label,
            kind=kind,
            status="copied",
            relative_path=relative_path,
            source_path=source_path,
            note=None,
        )

    @staticmethod
    def _copy_backup_bundle_item(*, bundle_path: Path, item: BackupBundleExportItem) -> None:
        if item.status != "copied" or item.source_path is None:
            return

        destination_path = bundle_path / item.relative_path
        if item.kind == "file":
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source_path, destination_path)
            return

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(item.source_path, destination_path)

    @staticmethod
    def _create_backup_bundle_zip(
        *,
        source_bundle_path: Path,
        destination_zip_path: Path,
    ) -> None:
        with zipfile.ZipFile(destination_zip_path, mode="x", compression=zipfile.ZIP_DEFLATED) as bundle_zip:
            for source_path in sorted(source_bundle_path.rglob("*")):
                archive_name = source_path.relative_to(source_bundle_path).as_posix()
                if source_path.is_dir():
                    bundle_zip.writestr(f"{archive_name}/", b"")
                    continue
                bundle_zip.write(source_path, arcname=archive_name)

    @staticmethod
    def _serialize_backup_bundle_manifest(
        *,
        bundle_path: Path,
        created_at_utc: str,
        items: tuple[BackupBundleExportItem, ...],
    ) -> dict[str, object]:
        status_counts = Counter(item.status for item in items)
        return {
            "bundle_format": BACKUP_BUNDLE_FORMAT,
            "format_version": 1,
            "created_at_utc": created_at_utc,
            "bundle_folder_name": bundle_path.name,
            "summary": {
                "copied": status_counts.get("copied", 0),
                "not_present": status_counts.get("not_present", 0),
                "not_configured": status_counts.get("not_configured", 0),
                "configured_missing": status_counts.get("configured_missing", 0),
            },
            "items": [
                {
                    "key": item.key,
                    "label": item.label,
                    "kind": item.kind,
                    "status": item.status,
                    "relative_path": str(item.relative_path),
                    "source_path": str(item.source_path) if item.source_path is not None else None,
                    "note": item.note,
                }
                for item in items
            ],
            "intentionally_not_included": [
                "Game binaries, Steam files, and SMAPI runtime executables.",
                "Watcher download folders and other unmanaged download cache locations.",
                "Only common per-mod config artifacts inside installed Mods trees are included in this stage; other external mod-created state folders are not yet covered.",
                "Transient UI state such as current selections, filters, and pending plans.",
                "A restore/import workflow. This bundle is export-only in this stage.",
            ],
        }

    @property
    def _install_operation_history_file(self) -> Path:
        return install_operation_history_file(self._state_file)

    @property
    def _recovery_execution_history_file(self) -> Path:
        return recovery_execution_history_file(self._state_file)

    @property
    def _update_source_intent_overlay_file(self) -> Path:
        return update_source_intent_overlay_file(self._state_file)

    @property
    def _sandbox_mod_profile_catalog_file(self) -> Path:
        return sandbox_mod_profile_catalog_file(self._state_file)

    @property
    def _real_mod_profile_catalog_file(self) -> Path:
        return real_mod_profile_catalog_file(self._state_file)

    def _record_completed_install_operation(
        self,
        *,
        plan: SandboxInstallPlan,
        result: SandboxInstallResult,
    ) -> None:
        self._record_install_operation_state(
            plan=plan,
            installed_targets=result.installed_targets,
            archived_targets=result.archived_targets,
        )

    def _record_install_operation_state(
        self,
        *,
        plan: SandboxInstallPlan,
        installed_targets: tuple[Path, ...],
        archived_targets: tuple[Path, ...],
    ) -> None:
        operation = InstallOperationRecord(
            operation_id=_new_operation_id("install"),
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            package_path=plan.package_path,
            destination_kind=plan.destination_kind,
            destination_mods_path=plan.sandbox_mods_path,
            archive_path=plan.sandbox_archive_path,
            installed_targets=installed_targets,
            archived_targets=archived_targets,
            entries=tuple(
                InstallOperationEntryRecord(
                    name=entry.name,
                    unique_id=entry.unique_id,
                    version=entry.version,
                    action=entry.action,
                    target_path=entry.target_path,
                    archive_path=entry.archive_path,
                    source_manifest_path=entry.source_manifest_path,
                    source_root_path=entry.source_root_path,
                    target_exists_before=entry.target_exists,
                    can_install=entry.can_install,
                    warnings=entry.warnings,
                )
                for entry in plan.entries
            ),
        )
        try:
            append_install_operation_record(self._install_operation_history_file, operation)
        except (AppStateStoreError, OSError) as exc:
            raise AppShellError(
                "Install completed, but recording install history failed: "
                f"{exc}. Recovery inspection depends on recorded install history."
            ) from exc

    def _record_recovery_execution_attempt(
        self,
        *,
        review: InstallRecoveryExecutionReview,
        outcome_status: str,
        removed_target_paths: tuple[Path, ...],
        restored_target_paths: tuple[Path, ...],
        failure_message: str | None,
        critical: bool,
    ) -> None:
        record = RecoveryExecutionRecord(
            recovery_execution_id=_new_operation_id("recovery"),
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            related_install_operation_id=review.plan.operation.operation_id,
            related_install_operation_timestamp=review.plan.operation.timestamp,
            related_install_package_path=review.plan.operation.package_path,
            destination_kind=review.plan.operation.destination_kind,
            destination_mods_path=review.plan.operation.destination_mods_path,
            executed_entry_count=len(removed_target_paths) + len(restored_target_paths),
            removed_target_paths=removed_target_paths,
            restored_target_paths=restored_target_paths,
            outcome_status=outcome_status,
            failure_message=failure_message,
        )
        try:
            append_recovery_execution_record(self._recovery_execution_history_file, record)
        except (AppStateStoreError, OSError) as exc:
            if not critical:
                # Blocked/no-op recovery paths have not changed files, so the primary
                # review outcome remains the important signal and audit recording can
                # remain best-effort here.
                return

            if outcome_status == "completed":
                raise AppShellError(
                    "Recovery completed, but recording recovery history failed: "
                    f"{exc}. Recovery audit history is required for reversible workflow trust."
                ) from exc

            raise AppShellError(
                "Recovery failed after filesystem changes, and recording recovery history also failed: "
                f"{exc}. Original recovery error: {failure_message or 'unknown'}"
            ) from exc


def _non_null_paths(paths: Iterable[Path | None]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path is not None)


def _build_mod_config_snapshot(
    *,
    mods_path: Path,
    excluded_paths: tuple[Path, ...],
) -> tuple[Path | None, int, int, str | None]:
    try:
        inventory = scan_mods_directory(mods_path, excluded_paths=excluded_paths)
    except OSError as exc:
        return None, 0, 0, f"Config snapshot scan failed: {exc}"

    temp_root = Path(tempfile.mkdtemp(prefix="cinderleaf-config-snapshot-"))
    copied_mod_folders: set[Path] = set()
    copied_count = 0
    try:
        for mod in inventory.mods:
            for artifact in _iter_mod_config_artifacts(mod.folder_path):
                relative_path = artifact.relative_to(mods_path)
                destination_path = temp_root / relative_path
                if artifact.is_file():
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(artifact, destination_path)
                    copied_count += 1
                elif artifact.is_dir():
                    for source_file in artifact.rglob("*"):
                        if not source_file.is_file():
                            continue
                        nested_relative_path = source_file.relative_to(mods_path)
                        nested_destination_path = temp_root / nested_relative_path
                        nested_destination_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, nested_destination_path)
                        copied_count += 1
                copied_mod_folders.add(mod.folder_path)

        if copied_count == 0:
            shutil.rmtree(temp_root, ignore_errors=True)
            return None, 0, 0, None
        return temp_root, copied_count, len(copied_mod_folders), None
    except OSError as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        return None, 0, 0, f"Config snapshot build failed: {exc}"


def _iter_mod_config_artifacts(mod_folder: Path) -> tuple[Path, ...]:
    artifacts: list[Path] = []
    for candidate_name in ("config.json", "config", "configs"):
        candidate_path = mod_folder / candidate_name
        if not candidate_path.exists():
            continue
        if candidate_path.is_file() or candidate_path.is_dir():
            artifacts.append(candidate_path)
    return tuple(artifacts)


def _bundle_zip_member_pseudo_path(bundle_path: Path, relative_path: str) -> Path:
    return Path(f"{bundle_path}!/{relative_path}")


def _extract_backup_bundle_zip_safely(bundle_zip: zipfile.ZipFile, extracted_root: Path) -> None:
    extracted_root_resolved = extracted_root.resolve()
    for member in bundle_zip.infolist():
        relative_parts = _safe_backup_bundle_zip_member_parts(member.filename)
        destination_path = (extracted_root / Path(*relative_parts)).resolve()
        try:
            destination_path.relative_to(extracted_root_resolved)
        except ValueError as exc:
            raise OSError(
                f"Zip bundle contains unsafe path entry outside the extraction root: {member.filename}"
            ) from exc
        if member.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with bundle_zip.open(member, "r") as source, destination_path.open("wb") as target:
            shutil.copyfileobj(source, target)


def _safe_backup_bundle_zip_member_parts(member_name: str) -> tuple[str, ...]:
    normalized_name = member_name.replace("\\", "/").strip()
    if not normalized_name:
        raise OSError("Zip bundle contains an unsafe path entry: empty path.")
    member_path = PurePosixPath(normalized_name)
    if member_path.is_absolute():
        raise OSError(f"Zip bundle contains an unsafe path entry: {member_name}")
    parts = tuple(part for part in member_path.parts if part not in ("",))
    if not parts or any(part in (".", "..") for part in parts):
        raise OSError(f"Zip bundle contains an unsafe path entry: {member_name}")
    return parts


def _resolve_extracted_backup_bundle_content_root(extracted_root: Path) -> Path:
    manifest_path = extracted_root / "manifest.json"
    if manifest_path.exists():
        return extracted_root

    try:
        child_directories = [path for path in extracted_root.iterdir() if path.is_dir()]
    except OSError:
        return extracted_root
    if len(child_directories) != 1:
        return extracted_root

    nested_root = child_directories[0]
    return nested_root if (nested_root / "manifest.json").exists() else extracted_root


def _backup_bundle_content_root(inspection: BackupBundleInspectionResult) -> Path:
    return inspection.content_root_path or inspection.bundle_path


def _invalid_backup_bundle_inspection_result(
    *,
    bundle_path: Path,
    manifest_path: Path,
    summary_path: Path,
    message: str,
    warnings: tuple[str, ...],
    bundle_storage_kind: Literal["directory", "zip"] = "directory",
) -> BackupBundleInspectionResult:
    if not summary_path.exists():
        warnings = (*warnings, "Bundle summary README.txt is missing.")
    return BackupBundleInspectionResult(
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
        bundle_format=None,
        format_version=None,
        created_at_utc=None,
        items=tuple(),
        structurally_usable=False,
        message=message,
        warnings=warnings,
        bundle_storage_kind=bundle_storage_kind,
    )


def _build_backup_bundle_inspection_result(
    *,
    bundle_path: Path,
    manifest_path: Path,
    summary_path: Path,
    raw_manifest: object,
    bundle_storage_kind: Literal["directory", "zip"] = "directory",
    content_root_path: Path | None = None,
) -> BackupBundleInspectionResult:
    bundle_content_root = content_root_path or bundle_path
    if not isinstance(raw_manifest, dict):
        return _invalid_backup_bundle_inspection_result(
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            summary_path=summary_path,
            message="Backup bundle is structurally invalid: manifest root must be a JSON object.",
            warnings=("Manifest root is not a JSON object.",),
            bundle_storage_kind=bundle_storage_kind,
        )

    warnings: list[str] = []
    bundle_format = (
        raw_manifest.get("bundle_format")
        if isinstance(raw_manifest.get("bundle_format"), str)
        else None
    )
    format_version = (
        raw_manifest.get("format_version")
        if isinstance(raw_manifest.get("format_version"), int)
        else None
    )
    created_at_utc = (
        raw_manifest.get("created_at_utc")
        if isinstance(raw_manifest.get("created_at_utc"), str)
        else None
    )
    if bundle_format not in LEGACY_BACKUP_BUNDLE_FORMATS:
        warnings.append(
            "Manifest bundle_format is missing or unsupported for the current backup format."
        )
    if format_version != 1:
        warnings.append(
            "Manifest format_version is missing or unsupported for the current inspection baseline."
        )
    if created_at_utc is None:
        warnings.append("Manifest created_at_utc is missing or invalid.")

    raw_items = raw_manifest.get("items")
    if not isinstance(raw_items, list):
        warnings.append("Manifest items list is missing or invalid.")
        return BackupBundleInspectionResult(
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            summary_path=summary_path,
            bundle_format=bundle_format,
            format_version=format_version,
            created_at_utc=created_at_utc,
            items=tuple(),
            structurally_usable=False,
            message="Backup bundle is structurally invalid: manifest items are missing or unreadable.",
            warnings=_finish_backup_bundle_inspection_warnings(
                warnings=warnings,
                summary_path=summary_path,
            ),
            intentionally_not_included=_parse_backup_bundle_not_included(raw_manifest),
            bundle_storage_kind=bundle_storage_kind,
            content_root_path=bundle_content_root,
        )

    items: list[BackupBundleInspectionItem] = []
    structurally_usable = bundle_format in LEGACY_BACKUP_BUNDLE_FORMATS and format_version == 1
    for index, raw_item in enumerate(raw_items):
        parsed_item, item_warning, item_valid_for_restore = _parse_backup_bundle_inspection_item(
            bundle_content_root=bundle_content_root,
            raw_item=raw_item,
            item_index=index,
        )
        if parsed_item is not None:
            items.append(parsed_item)
        if item_warning is not None:
            warnings.append(item_warning)
        structurally_usable = structurally_usable and item_valid_for_restore

    if not any(item.key == "app_state" and item.structure_state == "present" for item in items):
        warnings.append("App state/config snapshot is missing from the bundle.")
        structurally_usable = False

    warnings = _finish_backup_bundle_inspection_warnings(
        warnings=warnings,
        summary_path=summary_path,
    )
    message = (
        "Backup bundle looks structurally usable for future restore/import."
        if structurally_usable
        else "Backup bundle is inspectable, but structurally incomplete for future restore/import."
    )
    return BackupBundleInspectionResult(
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
        bundle_format=bundle_format,
        format_version=format_version,
        created_at_utc=created_at_utc,
        items=tuple(items),
        structurally_usable=structurally_usable,
        message=message,
        warnings=warnings,
        intentionally_not_included=_parse_backup_bundle_not_included(raw_manifest),
        bundle_storage_kind=bundle_storage_kind,
        content_root_path=bundle_content_root,
    )


def _parse_backup_bundle_inspection_item(
    *,
    bundle_content_root: Path,
    raw_item: object,
    item_index: int,
) -> tuple[BackupBundleInspectionItem | None, str | None, bool]:
    if not isinstance(raw_item, dict):
        return (
            None,
            f"Manifest item #{item_index + 1} is not a JSON object.",
            False,
        )

    key = raw_item.get("key")
    label = raw_item.get("label")
    kind = raw_item.get("kind")
    declared_status = raw_item.get("status")
    relative_path_text = raw_item.get("relative_path")
    note = raw_item.get("note")
    if not isinstance(key, str) or not key.strip():
        return (None, f"Manifest item #{item_index + 1} has no valid key.", False)
    if not isinstance(label, str) or not label.strip():
        return (None, f"Manifest item '{key}' has no valid label.", False)
    if kind not in {"file", "directory"}:
        return (None, f"Manifest item '{key}' has an unsupported kind.", False)
    if declared_status not in {
        "copied",
        "not_present",
        "not_configured",
        "configured_missing",
    }:
        return (None, f"Manifest item '{key}' has an unsupported status.", False)
    if not isinstance(relative_path_text, str) or not relative_path_text.strip():
        return (None, f"Manifest item '{key}' has no valid relative_path.", False)
    if note is not None and not isinstance(note, str):
        note = str(note)

    relative_path = Path(relative_path_text)
    bundle_item_path = bundle_content_root / relative_path
    expected_type_matches = (
        bundle_item_path.is_file() if kind == "file" else bundle_item_path.is_dir()
    )
    if declared_status == "copied":
        if expected_type_matches:
            return (
                BackupBundleInspectionItem(
                    key=key,
                    label=label,
                    kind=kind,
                    declared_status=declared_status,
                    relative_path=relative_path,
                    structure_state="present",
                    note=note,
                ),
                None,
                True,
            )
        warning = (
            f"{label} was marked copied in the manifest but is missing or has the wrong type in the bundle."
        )
        return (
            BackupBundleInspectionItem(
                key=key,
                label=label,
                kind=kind,
                declared_status=declared_status,
                relative_path=relative_path,
                structure_state="missing_expected",
                note=note or warning,
            ),
            warning,
            False,
        )

    if bundle_item_path.exists():
        warning = f"{label} is present in the bundle even though the manifest marked it {declared_status}."
        return (
            BackupBundleInspectionItem(
                key=key,
                label=label,
                kind=kind,
                declared_status=declared_status,
                relative_path=relative_path,
                structure_state="unexpected_present",
                note=note or warning,
            ),
            warning,
            True,
        )

    return (
        BackupBundleInspectionItem(
            key=key,
            label=label,
            kind=kind,
            declared_status=declared_status,
            relative_path=relative_path,
            structure_state="absent_as_declared",
            note=note,
        ),
        None,
        True,
    )


def _finish_backup_bundle_inspection_warnings(
    *,
    warnings: list[str],
    summary_path: Path,
) -> tuple[str, ...]:
    if not summary_path.exists():
        warnings.append("Bundle summary README.txt is missing.")
    deduped: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if warning in seen:
            continue
        seen.add(warning)
        deduped.append(warning)
    return tuple(deduped)


def _parse_backup_bundle_not_included(raw_manifest: dict[str, object]) -> tuple[str, ...]:
    values = raw_manifest.get("intentionally_not_included")
    if not isinstance(values, list):
        return tuple()
    return tuple(value for value in values if isinstance(value, str) and value.strip())


def _build_restore_import_planning_result(
    *,
    inspection: BackupBundleInspectionResult,
    local_targets: _RestoreImportPlanningLocalTargets,
) -> RestoreImportPlanningResult:
    warnings = list(inspection.warnings)
    if local_targets.bundle_config_warning:
        warnings.append(local_targets.bundle_config_warning)

    planned_items: list[RestoreImportPlanningItem] = []
    mod_entries: list[RestoreImportPlanningModEntry] = []
    config_entries: list[RestoreImportPlanningConfigEntry] = []
    for item in inspection.items:
        (
            planned_item,
            planned_mod_entries,
            planned_config_entries,
            item_warnings,
        ) = _build_restore_import_planning_item(
            inspection=inspection,
            item=item,
            local_targets=local_targets,
        )
        planned_items.append(planned_item)
        mod_entries.extend(planned_mod_entries)
        config_entries.extend(planned_config_entries)
        warnings.extend(item_warnings)

    item_state_counts = Counter(item.state for item in planned_items)
    mod_state_counts = Counter(
        _restore_import_mod_state_bucket(entry.state) for entry in mod_entries
    )
    config_state_counts = Counter(
        _restore_import_config_state_bucket(entry.state) for entry in config_entries
    )
    message = _restore_import_planning_summary_message(
        inspection=inspection,
        safe_item_count=item_state_counts.get("safe_to_restore_later", 0),
        review_item_count=item_state_counts.get("needs_review", 0),
        blocked_item_count=item_state_counts.get("blocked", 0),
        safe_mod_count=mod_state_counts.get("safe_to_restore_later", 0),
        review_mod_count=mod_state_counts.get("needs_review", 0),
        blocked_mod_count=mod_state_counts.get("blocked", 0),
        safe_config_count=config_state_counts.get("safe_to_restore_later", 0),
        review_config_count=config_state_counts.get("needs_review", 0),
        blocked_config_count=config_state_counts.get("blocked", 0),
    )
    return RestoreImportPlanningResult(
        bundle_path=inspection.bundle_path,
        inspection=inspection,
        items=tuple(planned_items),
        mod_entries=tuple(mod_entries),
        config_entries=tuple(config_entries),
        safe_item_count=item_state_counts.get("safe_to_restore_later", 0),
        review_item_count=item_state_counts.get("needs_review", 0),
        blocked_item_count=item_state_counts.get("blocked", 0),
        safe_mod_count=mod_state_counts.get("safe_to_restore_later", 0),
        review_mod_count=mod_state_counts.get("needs_review", 0),
        blocked_mod_count=mod_state_counts.get("blocked", 0),
        message=message,
        safe_config_count=config_state_counts.get("safe_to_restore_later", 0),
        review_config_count=config_state_counts.get("needs_review", 0),
        blocked_config_count=config_state_counts.get("blocked", 0),
        warnings=_dedupe_text_lines(warnings),
    )


def _build_restore_import_planning_item(
    *,
    inspection: BackupBundleInspectionResult,
    item: BackupBundleInspectionItem,
    local_targets: _RestoreImportPlanningLocalTargets,
) -> tuple[
    RestoreImportPlanningItem,
    tuple[RestoreImportPlanningModEntry, ...],
    tuple[RestoreImportPlanningConfigEntry, ...],
    tuple[str, ...],
]:
    local_target_path = _restore_import_local_target_for_item(item.key, local_targets)
    if item.declared_status != "copied":
        message = (
            f"This bundle does not include {item.label.lower()} "
            f"({item.declared_status.replace('_', ' ')})."
        )
        return (
            RestoreImportPlanningItem(
                key=item.key,
                label=item.label,
                state="blocked",
                message=message,
                bundle_relative_path=item.relative_path,
                local_target_path=local_target_path,
                bundle_declared_status=item.declared_status,
                bundle_structure_state=item.structure_state,
                note=item.note,
            ),
            tuple(),
            tuple(),
            tuple(),
        )

    if item.structure_state == "missing_expected":
        return (
            RestoreImportPlanningItem(
                key=item.key,
                label=item.label,
                state="blocked",
                message=f"{item.label} is structurally missing or unusable in this bundle.",
                bundle_relative_path=item.relative_path,
                local_target_path=local_target_path,
                bundle_declared_status=item.declared_status,
                bundle_structure_state=item.structure_state,
                note=item.note,
            ),
            tuple(),
            tuple(),
            tuple(),
        )

    if item.kind == "directory" and item.key in {"real_mods", "sandbox_mods"}:
        return _build_restore_import_mod_directory_plan(
            inspection=inspection,
            item=item,
            local_target_path=local_target_path,
        )

    if item.kind == "directory" and item.key in {"real_archive", "sandbox_archive"}:
        return _build_restore_import_archive_directory_plan(
            inspection=inspection,
            item=item,
            local_target_path=local_target_path,
        )

    if item.kind == "directory" and item.key in {"real_mod_configs", "sandbox_mod_configs"}:
        return _build_restore_import_mod_config_directory_plan(
            inspection=inspection,
            item=item,
            local_target_path=local_target_path,
        )

    return _build_restore_import_file_item_plan(
        item=item,
        local_target_path=local_target_path,
        local_targets=local_targets,
    )


def _build_restore_import_file_item_plan(
    *,
    item: BackupBundleInspectionItem,
    local_target_path: Path | None,
    local_targets: _RestoreImportPlanningLocalTargets,
) -> tuple[
    RestoreImportPlanningItem,
    tuple[RestoreImportPlanningModEntry, ...],
    tuple[RestoreImportPlanningConfigEntry, ...],
    tuple[str, ...],
]:
    warnings: list[str] = []
    state: RestoreImportPlanningItemState
    message: str
    note = item.note

    if item.key in {"real_mod_profiles", "sandbox_mod_profiles", "stardew_save_files"}:
        message = (
            f"{item.label} is exported for backup only in this stage. "
            "Restore/import does not yet restore this artifact type."
        )
        return (
            RestoreImportPlanningItem(
                key=item.key,
                label=item.label,
                state="blocked",
                message=message,
                bundle_relative_path=item.relative_path,
                local_target_path=local_target_path,
                bundle_declared_status=item.declared_status,
                bundle_structure_state=item.structure_state,
                note=item.note,
            ),
            tuple(),
            tuple(),
            tuple(),
        )

    if item.structure_state == "unexpected_present":
        state = "needs_review"
        message = (
            f"{item.label} is present in the bundle, but its manifest state needs review."
        )
    elif local_target_path is None:
        state = "blocked"
        message = f"No local destination is defined for {item.label.lower()}."
    elif item.key == "app_state":
        if local_targets.bundle_config_warning is not None:
            state = "blocked"
            message = "Bundle app-state snapshot is present but not readable for restore/import planning."
        else:
            mismatch_note = _summarize_bundle_config_mismatches(
                bundle_config=local_targets.bundle_config,
                local_targets=local_targets,
            )
            if mismatch_note:
                note = mismatch_note if note is None else f"{note} | {mismatch_note}"
                state = "needs_review"
                message = (
                    "Bundle app-state snapshot uses different Mods/archive paths than the current local setup."
                )
            elif local_target_path.exists():
                state = "needs_review"
                message = "Local app state already exists and would need review before any restore/import."
            else:
                state = "safe_to_restore_later"
                message = "Bundle app-state snapshot is available for later restore/import."
    elif local_target_path.exists():
        state = "needs_review"
        message = f"Local {item.label.lower()} already exists and would need merge/replace review later."
    else:
        state = "safe_to_restore_later"
        message = f"{item.label} is available in the bundle and currently missing locally."

    if item.structure_state == "unexpected_present":
        warnings.append(
            f"{item.label} is present in the bundle even though the manifest did not mark it copied."
        )

    return (
        RestoreImportPlanningItem(
            key=item.key,
            label=item.label,
            state=state,
            message=message,
            bundle_relative_path=item.relative_path,
            local_target_path=local_target_path,
            bundle_declared_status=item.declared_status,
            bundle_structure_state=item.structure_state,
            note=note,
        ),
        tuple(),
        tuple(),
        tuple(warnings),
    )


def _build_restore_import_archive_directory_plan(
    *,
    inspection: BackupBundleInspectionResult,
    item: BackupBundleInspectionItem,
    local_target_path: Path | None,
) -> tuple[
    RestoreImportPlanningItem,
    tuple[RestoreImportPlanningModEntry, ...],
    tuple[RestoreImportPlanningConfigEntry, ...],
    tuple[str, ...],
]:
    bundle_directory = _backup_bundle_content_root(inspection) / item.relative_path
    archive_entry_count = _count_directory_children(bundle_directory)
    state: RestoreImportPlanningItemState
    if local_target_path is None:
        state = "blocked"
        message = f"No current destination is configured for {item.label.lower()}."
    elif not _restore_import_directory_target_is_ready(local_target_path):
        state = "blocked"
        message = f"Current destination for {item.label.lower()} is not ready on this machine."
    elif local_target_path.exists():
        state = "needs_review"
        message = (
            f"{item.label} contains {archive_entry_count} bundled entr"
            f"{'y' if archive_entry_count == 1 else 'ies'}, and the local archive root already exists."
        )
    else:
        state = "safe_to_restore_later"
        message = (
            f"{item.label} contains {archive_entry_count} bundled entr"
            f"{'y' if archive_entry_count == 1 else 'ies'} and the local archive root is currently missing."
        )

    if item.structure_state == "unexpected_present":
        state = "needs_review"
        message = (
            f"{item.label} is present in the bundle, but its manifest state needs review."
        )

    return (
        RestoreImportPlanningItem(
            key=item.key,
            label=item.label,
            state=state,
            message=message,
            bundle_relative_path=item.relative_path,
            local_target_path=local_target_path,
            bundle_declared_status=item.declared_status,
            bundle_structure_state=item.structure_state,
            note=item.note,
        ),
        tuple(),
        tuple(),
        tuple(),
    )


def _build_restore_import_mod_directory_plan(
    *,
    inspection: BackupBundleInspectionResult,
    item: BackupBundleInspectionItem,
    local_target_path: Path | None,
) -> tuple[
    RestoreImportPlanningItem,
    tuple[RestoreImportPlanningModEntry, ...],
    tuple[RestoreImportPlanningConfigEntry, ...],
    tuple[str, ...],
]:
    bundle_directory = _backup_bundle_content_root(inspection) / item.relative_path
    warnings: list[str] = []
    bundle_inventory, bundle_error = _scan_inventory_for_restore_planning(bundle_directory)
    if bundle_inventory is None:
        entry = RestoreImportPlanningModEntry(
            bundle_item_key=item.key,
            bundle_item_label=item.label,
            name=item.label,
            unique_id="<bundle-unusable>",
            bundle_version=None,
            local_version=None,
            state="bundle_unusable",
            local_target_path=local_target_path,
            note=bundle_error or "Bundle content could not be scanned.",
        )
        return (
            RestoreImportPlanningItem(
                key=item.key,
                label=item.label,
                state="blocked",
                message=f"{item.label} could not be scanned from this bundle.",
                bundle_relative_path=item.relative_path,
                local_target_path=local_target_path,
                bundle_declared_status=item.declared_status,
                bundle_structure_state=item.structure_state,
                note=item.note or bundle_error,
                blocked_mod_count=1,
            ),
            (entry,),
            tuple(),
            tuple(error for error in (bundle_error,) if error),
        )

    local_inventory: ModsInventory | None = None
    local_inventory_error: str | None = None
    if local_target_path is None:
        local_inventory_error = f"No current destination is configured for {item.label.lower()}."
    elif not _restore_import_directory_target_is_ready(local_target_path):
        local_inventory_error = f"Current destination for {item.label.lower()} is not ready on this machine."
    else:
        local_inventory, local_inventory_error = _scan_inventory_for_restore_planning(
            local_target_path
        )

    if bundle_inventory.parse_warnings:
        warnings.append(
            f"{item.label} bundle scan reported {len(bundle_inventory.parse_warnings)} parse warning(s)."
        )
    if bundle_inventory.duplicate_unique_ids:
        warnings.append(
            f"{item.label} bundle scan found duplicate UniqueIDs that need review."
        )
    if local_inventory is not None and local_inventory.parse_warnings:
        warnings.append(
            f"Current local {item.label.lower()} scan reported {len(local_inventory.parse_warnings)} parse warning(s)."
        )
    if local_inventory is not None and local_inventory.duplicate_unique_ids:
        warnings.append(
            f"Current local {item.label.lower()} scan found duplicate UniqueIDs that need review."
        )
    if local_inventory_error:
        warnings.append(local_inventory_error)

    planned_mod_entries = _build_restore_import_mod_entries(
        bundle_item_key=item.key,
        bundle_item_label=item.label,
        bundle_inventory=bundle_inventory,
        local_inventory=local_inventory,
        local_target_path=local_target_path,
        local_inventory_error=local_inventory_error,
    )
    mod_state_counts = Counter(
        _restore_import_mod_state_bucket(entry.state) for entry in planned_mod_entries
    )
    state = _restore_import_item_state_from_mod_entries(planned_mod_entries)
    message = _restore_import_mod_directory_message(
        label=item.label,
        state=state,
        safe_count=mod_state_counts.get("safe_to_restore_later", 0),
        review_count=mod_state_counts.get("needs_review", 0),
        blocked_count=mod_state_counts.get("blocked", 0),
    )
    return (
        RestoreImportPlanningItem(
            key=item.key,
            label=item.label,
            state=state,
            message=message,
            bundle_relative_path=item.relative_path,
            local_target_path=local_target_path,
            bundle_declared_status=item.declared_status,
            bundle_structure_state=item.structure_state,
            note=item.note,
            safe_mod_count=mod_state_counts.get("safe_to_restore_later", 0),
            review_mod_count=mod_state_counts.get("needs_review", 0),
            blocked_mod_count=mod_state_counts.get("blocked", 0),
        ),
        planned_mod_entries,
        tuple(),
        tuple(warnings),
    )


def _build_restore_import_mod_config_directory_plan(
    *,
    inspection: BackupBundleInspectionResult,
    item: BackupBundleInspectionItem,
    local_target_path: Path | None,
) -> tuple[
    RestoreImportPlanningItem,
    tuple[RestoreImportPlanningModEntry, ...],
    tuple[RestoreImportPlanningConfigEntry, ...],
    tuple[str, ...],
]:
    bundle_directory = _backup_bundle_content_root(inspection) / item.relative_path
    warnings: list[str] = []
    config_relative_paths, bundle_error = _scan_mod_config_snapshot_relative_paths(bundle_directory)
    if bundle_error is not None:
        entry = RestoreImportPlanningConfigEntry(
            bundle_item_key=item.key,
            bundle_item_label=item.label,
            relative_path=Path("<bundle-unusable>"),
            state="bundle_unusable",
            local_target_path=local_target_path,
            note=bundle_error,
        )
        return (
            RestoreImportPlanningItem(
                key=item.key,
                label=item.label,
                state="blocked",
                message=f"{item.label} could not be scanned from this bundle.",
                bundle_relative_path=item.relative_path,
                local_target_path=local_target_path,
                bundle_declared_status=item.declared_status,
                bundle_structure_state=item.structure_state,
                note=item.note or bundle_error,
                blocked_config_count=1,
            ),
            tuple(),
            (entry,),
            tuple(error for error in (bundle_error,) if error),
        )

    planned_config_entries = _build_restore_import_config_entries(
        bundle_item_key=item.key,
        bundle_item_label=item.label,
        bundle_directory=bundle_directory,
        bundle_relative_paths=config_relative_paths,
        local_target_path=local_target_path,
    )
    config_state_counts = Counter(
        _restore_import_config_state_bucket(entry.state) for entry in planned_config_entries
    )
    state = _restore_import_item_state_from_config_entries(planned_config_entries)
    message = _restore_import_config_directory_message(
        label=item.label,
        state=state,
        safe_count=config_state_counts.get("safe_to_restore_later", 0),
        review_count=config_state_counts.get("needs_review", 0),
        blocked_count=config_state_counts.get("blocked", 0),
    )
    return (
        RestoreImportPlanningItem(
            key=item.key,
            label=item.label,
            state=state,
            message=message,
            bundle_relative_path=item.relative_path,
            local_target_path=local_target_path,
            bundle_declared_status=item.declared_status,
            bundle_structure_state=item.structure_state,
            note=item.note,
            safe_config_count=config_state_counts.get("safe_to_restore_later", 0),
            review_config_count=config_state_counts.get("needs_review", 0),
            blocked_config_count=config_state_counts.get("blocked", 0),
        ),
        tuple(),
        planned_config_entries,
        tuple(warnings),
    )


def _build_restore_import_mod_entries(
    *,
    bundle_item_key: str,
    bundle_item_label: str,
    bundle_inventory: ModsInventory,
    local_inventory: ModsInventory | None,
    local_target_path: Path | None,
    local_inventory_error: str | None,
) -> tuple[RestoreImportPlanningModEntry, ...]:
    bundle_duplicates = {
        canonicalize_unique_id(finding.unique_id)
        for finding in bundle_inventory.duplicate_unique_ids
    }
    local_duplicates = (
        {
            canonicalize_unique_id(finding.unique_id)
            for finding in local_inventory.duplicate_unique_ids
        }
        if local_inventory is not None
        else set()
    )
    local_mods_by_unique_id: dict[str, list[InstalledMod]] = {}
    if local_inventory is not None:
        for mod in local_inventory.mods:
            local_mods_by_unique_id.setdefault(canonicalize_unique_id(mod.unique_id), []).append(mod)

    entries: list[RestoreImportPlanningModEntry] = []
    for bundle_mod in sorted(
        bundle_inventory.mods,
        key=lambda item: (canonicalize_unique_id(item.unique_id), item.name.casefold()),
    ):
        unique_key = canonicalize_unique_id(bundle_mod.unique_id)
        local_matches = local_mods_by_unique_id.get(unique_key, [])
        if local_inventory_error is not None:
            state = "destination_not_ready"
            local_version = None
            note = local_inventory_error
        elif unique_key in bundle_duplicates or unique_key in local_duplicates or len(local_matches) > 1:
            state = "ambiguous_match"
            local_version = None
            note = "UniqueID matching is ambiguous and needs manual review."
        elif not local_matches:
            state = "missing_locally"
            local_version = None
            note = "Present in bundle but missing locally."
        else:
            local_match = local_matches[0]
            local_version = local_match.version
            if bundle_mod.version == local_match.version:
                state = "same_version"
                note = "Local destination already has the same version."
            else:
                state = "different_version"
                note = (
                    f"Bundle version {bundle_mod.version} differs from local version {local_match.version}."
                )

        entries.append(
            RestoreImportPlanningModEntry(
                bundle_item_key=bundle_item_key,
                bundle_item_label=bundle_item_label,
                name=bundle_mod.name,
                unique_id=bundle_mod.unique_id,
                bundle_version=bundle_mod.version,
                local_version=local_version,
                state=state,
                local_target_path=local_target_path,
                note=note,
            )
        )
    return tuple(entries)


def _scan_mod_config_snapshot_relative_paths(
    snapshot_root: Path,
) -> tuple[tuple[Path, ...], str | None]:
    try:
        if not snapshot_root.exists():
            return tuple(), f"Directory does not exist: {snapshot_root}"
        if not snapshot_root.is_dir():
            return tuple(), f"Path is not a directory: {snapshot_root}"
        paths = tuple(
            sorted(
                (
                    path.relative_to(snapshot_root)
                    for path in snapshot_root.rglob("*")
                    if path.is_file()
                ),
                key=lambda path: str(path).casefold(),
            )
        )
        return paths, None
    except OSError as exc:
        return tuple(), f"Could not scan config snapshot {snapshot_root}: {exc}"


def _build_restore_import_config_entries(
    *,
    bundle_item_key: str,
    bundle_item_label: str,
    bundle_directory: Path,
    bundle_relative_paths: tuple[Path, ...],
    local_target_path: Path | None,
) -> tuple[RestoreImportPlanningConfigEntry, ...]:
    entries: list[RestoreImportPlanningConfigEntry] = []
    for relative_path in bundle_relative_paths:
        bundle_file_path = bundle_directory / relative_path
        if local_target_path is None or not _restore_import_directory_target_is_ready(local_target_path):
            state = "destination_not_ready"
            resolved_local_path = local_target_path
            note = (
                f"Current destination for {bundle_item_label.lower()} is not ready on this machine."
            )
        else:
            resolved_local_path = local_target_path / relative_path
            if not resolved_local_path.exists():
                state = "missing_locally"
                note = "Config artifact is present in the bundle but missing locally."
            elif not resolved_local_path.is_file():
                state = "bundle_unusable"
                note = "Local path exists but is not a file."
            elif _file_sha256(bundle_file_path) == _file_sha256(resolved_local_path):
                state = "same_content"
                note = "Local config artifact already matches the bundled content."
            else:
                state = "different_content"
                note = "Local config artifact differs from the bundled content."
        entries.append(
            RestoreImportPlanningConfigEntry(
                bundle_item_key=bundle_item_key,
                bundle_item_label=bundle_item_label,
                relative_path=relative_path,
                state=state,
                local_target_path=resolved_local_path,
                note=note,
            )
        )
    return tuple(entries)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_inventory_for_restore_planning(
    mods_path: Path,
) -> tuple[ModsInventory | None, str | None]:
    try:
        if not mods_path.exists():
            return None, f"Directory does not exist: {mods_path}"
        if not mods_path.is_dir():
            return None, f"Path is not a directory: {mods_path}"
        return scan_mods_directory(mods_path), None
    except OSError as exc:
        return None, f"Could not scan directory {mods_path}: {exc}"


def _restore_import_local_target_for_item(
    key: str,
    local_targets: _RestoreImportPlanningLocalTargets,
) -> Path | None:
    if key == "app_state":
        return local_targets.app_state_path
    if key == "install_history":
        return local_targets.install_history_path
    if key == "recovery_history":
        return local_targets.recovery_history_path
    if key == "update_source_intent_overlay":
        return local_targets.update_source_intent_overlay_path
    if key == "real_mods":
        return local_targets.real_mods_path
    if key == "sandbox_mods":
        return local_targets.sandbox_mods_path
    if key == "real_mod_configs":
        return local_targets.real_mods_path
    if key == "sandbox_mod_configs":
        return local_targets.sandbox_mods_path
    if key == "real_archive":
        return local_targets.real_archive_path
    if key == "sandbox_archive":
        return local_targets.sandbox_archive_path
    return None


def _restore_import_item_state_from_mod_entries(
    entries: tuple[RestoreImportPlanningModEntry, ...],
) -> RestoreImportPlanningItemState:
    if any(
        _restore_import_mod_state_bucket(entry.state) == "blocked" for entry in entries
    ):
        return "blocked"
    if any(
        _restore_import_mod_state_bucket(entry.state) == "needs_review" for entry in entries
    ):
        return "needs_review"
    return "safe_to_restore_later"


def _restore_import_item_state_from_config_entries(
    entries: tuple[RestoreImportPlanningConfigEntry, ...],
) -> RestoreImportPlanningItemState:
    if any(
        _restore_import_config_state_bucket(entry.state) == "blocked" for entry in entries
    ):
        return "blocked"
    if any(
        _restore_import_config_state_bucket(entry.state) == "needs_review"
        for entry in entries
    ):
        return "needs_review"
    return "safe_to_restore_later"


def _restore_import_mod_state_bucket(state: str) -> RestoreImportPlanningItemState:
    if state in {"missing_locally", "same_version"}:
        return "safe_to_restore_later"
    if state in {"different_version", "ambiguous_match"}:
        return "needs_review"
    return "blocked"


def _restore_import_config_state_bucket(state: str) -> RestoreImportPlanningItemState:
    if state in {"missing_locally", "same_content"}:
        return "safe_to_restore_later"
    if state == "different_content":
        return "needs_review"
    return "blocked"


def _restore_import_mod_directory_message(
    *,
    label: str,
    state: RestoreImportPlanningItemState,
    safe_count: int,
    review_count: int,
    blocked_count: int,
) -> str:
    if state == "blocked":
        return (
            f"{label} planning is blocked: {blocked_count} blocked, "
            f"{review_count} need review, {safe_count} look safe."
        )
    if state == "needs_review":
        return (
            f"{label} planning found review points: {review_count} need review, "
            f"{safe_count} look safe."
        )
    return f"{label} planning looks straightforward: {safe_count} safe, 0 blocked."


def _restore_import_planning_summary_message(
    *,
    inspection: BackupBundleInspectionResult,
    safe_item_count: int,
    review_item_count: int,
    blocked_item_count: int,
    safe_mod_count: int,
    review_mod_count: int,
    blocked_mod_count: int,
    safe_config_count: int,
    review_config_count: int,
    blocked_config_count: int,
) -> str:
    if not inspection.items:
        return "Restore/import planning could not compare this bundle because the manifest is missing or unreadable."
    if blocked_item_count > 0 or blocked_mod_count > 0 or blocked_config_count > 0:
        return (
            "Restore/import planning found blocked or unavailable items that are not restorable from this bundle yet or need local setup first."
        )
    if review_item_count > 0 or review_mod_count > 0 or review_config_count > 0:
        return (
            f"Restore/import planning complete: {safe_item_count} item(s) look straightforward, "
            f"{review_item_count} item(s) need review."
        )
    return (
        f"Restore/import planning complete: {safe_item_count} item(s) and "
        f"{safe_mod_count} bundled mod row(s) plus {safe_config_count} config artifact(s) look straightforward."
    )


def _build_restore_import_execution_review(
    planning_result: RestoreImportPlanningResult,
) -> RestoreImportExecutionReview:
    analysis = _analyze_restore_import_execution(planning_result)
    executable_mod_count = len(analysis.mod_actions)
    executable_config_count = len(analysis.config_actions)
    has_executable_content = executable_mod_count > 0 or executable_config_count > 0

    if has_executable_content:
        message = (
            "Restore/import is ready to write "
            f"{executable_mod_count} mod folder(s) and "
            f"{executable_config_count} config artifact(s) into the current configured destinations. "
            "Existing local content will not be merged."
        )
        if analysis.replace_mod_count > 0:
            message += (
                f" {analysis.replace_mod_count} mod folder(s) will be archive-and-replaced after explicit review."
            )
        if analysis.replace_config_count > 0:
            message += (
                f" {analysis.replace_config_count} conflicting config artifact(s) will be resolved by archive-and-replacing the containing mod folder."
            )
        if (
            analysis.review_entry_count > 0
            or analysis.blocked_entry_count > 0
            or analysis.deferred_item_count > 0
        ):
            message += " Review, blocked, and deferred bundle content will be left untouched."
    elif analysis.review_entry_count > 0 or analysis.blocked_entry_count > 0:
        message = (
            "Restore/import execution is blocked: no clearly restorable missing content is available "
            "under the current review model."
        )
    else:
        message = (
            "Restore/import execution found nothing to do: the current configured destinations do not "
            "have any clearly missing content from this bundle."
        )

    return RestoreImportExecutionReview(
        allowed=has_executable_content,
        message=message,
        executable_mod_count=executable_mod_count,
        executable_config_count=executable_config_count,
        replace_mod_count=analysis.replace_mod_count,
        replace_config_count=analysis.replace_config_count,
        covered_config_count=analysis.covered_config_count,
        review_entry_count=analysis.review_entry_count,
        blocked_entry_count=analysis.blocked_entry_count,
        deferred_item_count=analysis.deferred_item_count,
        requires_explicit_confirmation=True,
        warnings=analysis.warnings,
    )


def _build_restore_import_execution_actions(
    planning_result: RestoreImportPlanningResult,
) -> tuple[
    tuple[_RestoreImportExecutableModAction, ...],
    tuple[_RestoreImportExecutableConfigAction, ...],
    tuple[str, ...],
]:
    analysis = _analyze_restore_import_execution(planning_result)
    return analysis.mod_actions, analysis.config_actions, analysis.warnings


def _analyze_restore_import_execution(
    planning_result: RestoreImportPlanningResult,
) -> _RestoreImportExecutionAnalysis:
    warnings = list(planning_result.warnings)
    review_entry_count = sum(
        1
        for entry in planning_result.mod_entries
        if _restore_import_mod_state_bucket(entry.state) == "needs_review"
    ) + sum(
        1
        for entry in planning_result.config_entries
        if _restore_import_config_state_bucket(entry.state) == "needs_review"
    )
    blocked_entry_count = sum(
        1
        for entry in planning_result.mod_entries
        if _restore_import_mod_state_bucket(entry.state) == "blocked"
    ) + sum(
        1
        for entry in planning_result.config_entries
        if _restore_import_config_state_bucket(entry.state) == "blocked"
    )
    deferred_item_count = sum(
        1
        for item in planning_result.items
        if item.key
        not in {"real_mods", "sandbox_mods", "real_mod_configs", "sandbox_mod_configs"}
    )

    planning_items_by_key = {item.key: item for item in planning_result.items}
    mod_source_paths = _build_restore_import_mod_source_index(planning_result, warnings)
    mod_source_paths_by_folder = _build_restore_import_mod_folder_source_index(planning_result, warnings)

    mod_actions: list[_RestoreImportExecutableModAction] = []
    covered_config_folders_by_key: dict[str, set[str]] = {
        "real_mod_configs": set(),
        "sandbox_mod_configs": set(),
    }
    scheduled_replace_destinations: set[tuple[str, str]] = set()
    for entry in planning_result.mod_entries:
        if entry.bundle_item_key not in {"real_mods", "sandbox_mods"}:
            continue
        if entry.state not in {"missing_locally", "different_version"}:
            continue
        if entry.local_target_path is None or not _restore_import_directory_target_is_ready(
            entry.local_target_path
        ):
            blocked_entry_count += 1
            warnings.append(
                f"Restore/import target is no longer ready for bundled mod {entry.name} ({entry.unique_id})."
            )
            continue

        source_path = mod_source_paths.get(
            (entry.bundle_item_key, canonicalize_unique_id(entry.unique_id))
        )
        if source_path is None:
            blocked_entry_count += 1
            warnings.append(
                f"Bundled source folder could not be resolved for {entry.name} ({entry.unique_id})."
            )
            continue

        destination_path = entry.local_target_path / source_path.name
        action_kind: Literal["restore_missing", "archive_replace"] = "restore_missing"
        archive_root: Path | None = None
        archive_destination_path: Path | None = None
        replace_config_count = 0
        if entry.state == "different_version":
            if not destination_path.exists() or not destination_path.is_dir():
                blocked_entry_count += 1
                warnings.append(
                    "Restore/import replace target is not available for archive-aware replacement: "
                    f"{destination_path}"
                )
                continue
            archive_root = _restore_import_archive_root_for_mod_item(
                mod_item_key=entry.bundle_item_key,
                planning_items_by_key=planning_items_by_key,
            )
            if archive_root is None:
                blocked_entry_count += 1
                warnings.append(
                    f"No archive destination is configured for reviewed restore/import replacement of {destination_path}."
                )
                continue
            try:
                _ensure_archive_root_service(archive_root)
                archive_destination_path = allocate_archive_destination(
                    archive_root=archive_root,
                    target_folder_name=destination_path.name,
                )
            except (SandboxInstallError, ArchiveManagerError, OSError) as exc:
                blocked_entry_count += 1
                warnings.append(
                    f"Could not prepare archive-aware replacement for {destination_path}: {exc}"
                )
                continue
            action_kind = "archive_replace"
            scheduled_replace_destinations.add(
                (entry.bundle_item_key, destination_path.name.casefold())
            )
        elif destination_path.exists():
            blocked_entry_count += 1
            warnings.append(
                f"Restore/import target already exists and will not be overwritten without review: {destination_path}"
            )
            continue

        mod_actions.append(
            _RestoreImportExecutableModAction(
                bundle_item_key=entry.bundle_item_key,
                unique_id=entry.unique_id,
                source_path=source_path,
                destination_path=destination_path,
                action_kind=action_kind,
                archive_root=archive_root,
                archive_destination_path=archive_destination_path,
                replace_config_count=replace_config_count,
            )
        )
        covered_config_key = _restore_import_config_key_for_mod_item(entry.bundle_item_key)
        if covered_config_key is not None:
            covered_config_folders_by_key.setdefault(covered_config_key, set()).add(
                source_path.name
            )

    config_actions: list[_RestoreImportExecutableConfigAction] = []
    covered_config_count = 0
    replace_config_count = 0
    config_conflicts_by_folder: dict[tuple[str, str], list[RestoreImportPlanningConfigEntry]] = {}
    for entry in planning_result.config_entries:
        if entry.bundle_item_key not in {"real_mod_configs", "sandbox_mod_configs"}:
            continue
        relative_parts = entry.relative_path.parts
        top_level_folder = relative_parts[0] if relative_parts else None
        if entry.state == "different_content":
            if top_level_folder is None:
                blocked_entry_count += 1
                warnings.append(
                    "Bundled config conflict has an invalid relative path and cannot be reviewed for replacement."
                )
                continue
            config_conflicts_by_folder.setdefault(
                (entry.bundle_item_key, top_level_folder.casefold()),
                [],
            ).append(entry)
            continue
        if entry.state != "missing_locally":
            continue

        if (
            top_level_folder is not None
            and top_level_folder in covered_config_folders_by_key.get(entry.bundle_item_key, set())
        ):
            covered_config_count += 1
            continue

        planning_item = planning_items_by_key.get(entry.bundle_item_key)
        if planning_item is None or planning_item.local_target_path is None:
            blocked_entry_count += 1
            warnings.append(
                f"No local destination is available for bundled config artifact {entry.relative_path}."
            )
            continue
        if not _restore_import_directory_target_is_ready(planning_item.local_target_path):
            blocked_entry_count += 1
            warnings.append(
                f"Config restore destination is not ready for {entry.relative_path}."
            )
            continue

        if top_level_folder is None:
            blocked_entry_count += 1
            warnings.append(
                "Bundled config artifact has an invalid relative path and cannot be restored automatically."
            )
            continue

        destination_mod_folder = planning_item.local_target_path / top_level_folder
        if not destination_mod_folder.exists() or not destination_mod_folder.is_dir():
            blocked_entry_count += 1
            warnings.append(
                "Config artifact cannot be restored automatically because the local mod folder is "
                f"missing: {destination_mod_folder}"
            )
            continue

        if entry.local_target_path is None:
            blocked_entry_count += 1
            warnings.append(
                f"No local destination path is available for bundled config artifact {entry.relative_path}."
            )
            continue
        if entry.local_target_path.exists():
            blocked_entry_count += 1
            warnings.append(
                f"Config artifact target already exists and will not be overwritten: {entry.local_target_path}"
            )
            continue

        source_path = (
            _backup_bundle_content_root(planning_result.inspection)
            / planning_item.bundle_relative_path
            / entry.relative_path
        )
        try:
            source_exists = source_path.exists()
            source_is_file = source_path.is_file()
        except OSError:
            source_exists = False
            source_is_file = False
        if not source_exists or not source_is_file:
            blocked_entry_count += 1
            warnings.append(
                f"Bundled config artifact is missing or unreadable: {source_path}"
            )
            continue

        config_actions.append(
            _RestoreImportExecutableConfigAction(
                bundle_item_key=entry.bundle_item_key,
                relative_path=entry.relative_path,
                source_path=source_path,
                destination_path=entry.local_target_path,
            )
        )

    for (config_item_key, folder_key), conflict_entries in sorted(
        config_conflicts_by_folder.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        planning_item = planning_items_by_key.get(config_item_key)
        if planning_item is None or planning_item.local_target_path is None:
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                f"No local destination is available for reviewed config restore conflicts in {folder_key}."
            )
            continue
        destination_path = planning_item.local_target_path / conflict_entries[0].relative_path.parts[0]
        if not destination_path.exists() or not destination_path.is_dir():
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                "Config conflict replacement target is not available for archive-aware replacement: "
                f"{destination_path}"
            )
            continue

        mod_item_key = _restore_import_mod_item_key_for_config_item(config_item_key)
        if mod_item_key is None:
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                f"Config conflict group {destination_path.name} is missing a matching bundled Mods directory."
            )
            continue
        if (mod_item_key, folder_key) in scheduled_replace_destinations:
            replace_config_count += len(conflict_entries)
            continue
        source_path = mod_source_paths_by_folder.get((mod_item_key, folder_key))
        if source_path is None:
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                f"Bundled mod folder source could not be resolved for config conflict replacement of {destination_path.name}."
            )
            continue

        archive_root = _restore_import_archive_root_for_mod_item(
            mod_item_key=mod_item_key,
            planning_items_by_key=planning_items_by_key,
        )
        if archive_root is None:
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                f"No archive destination is configured for reviewed restore/import replacement of {destination_path}."
            )
            continue
        try:
            _ensure_archive_root_service(archive_root)
            archive_destination_path = allocate_archive_destination(
                archive_root=archive_root,
                target_folder_name=destination_path.name,
            )
        except (SandboxInstallError, ArchiveManagerError, OSError) as exc:
            blocked_entry_count += len(conflict_entries)
            warnings.append(
                f"Could not prepare archive-aware replacement for config conflict {destination_path}: {exc}"
            )
            continue

        mod_actions.append(
            _RestoreImportExecutableModAction(
                bundle_item_key=mod_item_key,
                unique_id="<config-conflict>",
                source_path=source_path,
                destination_path=destination_path,
                action_kind="archive_replace",
                archive_root=archive_root,
                archive_destination_path=archive_destination_path,
                replace_config_count=len(conflict_entries),
            )
        )
        scheduled_replace_destinations.add((mod_item_key, folder_key))
        replace_config_count += len(conflict_entries)

    replace_mod_count = sum(
        1 for action in mod_actions if action.action_kind == "archive_replace"
    )

    return _RestoreImportExecutionAnalysis(
        mod_actions=tuple(mod_actions),
        config_actions=tuple(config_actions),
        replace_mod_count=replace_mod_count,
        replace_config_count=replace_config_count,
        covered_config_count=covered_config_count,
        review_entry_count=review_entry_count,
        blocked_entry_count=blocked_entry_count,
        deferred_item_count=deferred_item_count,
        warnings=_dedupe_text_lines(warnings),
    )


def _build_restore_import_mod_source_index(
    planning_result: RestoreImportPlanningResult,
    warnings: list[str],
) -> dict[tuple[str, str], Path]:
    indexed_sources: dict[tuple[str, str], Path] = {}
    indexed_sources_by_folder = _build_restore_import_mod_folder_source_index(
        planning_result,
        warnings,
    )
    for (item_key, _folder_key), source_path in indexed_sources_by_folder.items():
        unique_key = _restore_import_unique_key_for_bundle_mod_path(
            planning_result=planning_result,
            item_key=item_key,
            source_path=source_path,
            warnings=warnings,
        )
        if unique_key is None:
            continue
        indexed_sources[(item_key, unique_key)] = source_path
    return indexed_sources


def _build_restore_import_mod_folder_source_index(
    planning_result: RestoreImportPlanningResult,
    warnings: list[str],
) -> dict[tuple[str, str], Path]:
    planning_items_by_key = {item.key: item for item in planning_result.items}
    indexed_sources: dict[tuple[str, str], Path] = {}
    for item_key in ("real_mods", "sandbox_mods"):
        planning_item = planning_items_by_key.get(item_key)
        if planning_item is None:
            continue
        bundle_directory = (
            _backup_bundle_content_root(planning_result.inspection)
            / planning_item.bundle_relative_path
        )
        bundle_inventory, bundle_error = _scan_inventory_for_restore_planning(bundle_directory)
        if bundle_inventory is None:
            if bundle_error:
                warnings.append(bundle_error)
            continue

        unique_id_counts = Counter(
            canonicalize_unique_id(mod.unique_id) for mod in bundle_inventory.mods
        )
        for mod in bundle_inventory.mods:
            unique_key = canonicalize_unique_id(mod.unique_id)
            if unique_id_counts[unique_key] > 1:
                continue
            indexed_sources[(item_key, mod.folder_path.name.casefold())] = mod.folder_path
    return indexed_sources


def _restore_import_config_key_for_mod_item(mod_item_key: str) -> str | None:
    if mod_item_key == "real_mods":
        return "real_mod_configs"
    if mod_item_key == "sandbox_mods":
        return "sandbox_mod_configs"
    return None


def _restore_import_mod_item_key_for_config_item(config_item_key: str) -> str | None:
    if config_item_key == "real_mod_configs":
        return "real_mods"
    if config_item_key == "sandbox_mod_configs":
        return "sandbox_mods"
    return None


def _restore_import_archive_root_for_mod_item(
    *,
    mod_item_key: str,
    planning_items_by_key: dict[str, RestoreImportPlanningItem],
) -> Path | None:
    if mod_item_key == "real_mods":
        archive_item = planning_items_by_key.get("real_archive")
    elif mod_item_key == "sandbox_mods":
        archive_item = planning_items_by_key.get("sandbox_archive")
    else:
        archive_item = None
    if archive_item is None:
        return None
    return archive_item.local_target_path


def _restore_import_unique_key_for_bundle_mod_path(
    *,
    planning_result: RestoreImportPlanningResult,
    item_key: str,
    source_path: Path,
    warnings: list[str],
) -> str | None:
    planning_items_by_key = {item.key: item for item in planning_result.items}
    planning_item = planning_items_by_key.get(item_key)
    if planning_item is None:
        return None
    bundle_directory = (
        _backup_bundle_content_root(planning_result.inspection)
        / planning_item.bundle_relative_path
    )
    bundle_inventory, bundle_error = _scan_inventory_for_restore_planning(bundle_directory)
    if bundle_inventory is None:
        if bundle_error:
            warnings.append(bundle_error)
        return None
    for mod in bundle_inventory.mods:
        if _paths_deterministically_match(mod.folder_path, source_path):
            return canonicalize_unique_id(mod.unique_id)
    warnings.append(f"Could not determine bundled UniqueID for {source_path}.")
    return None


def _build_restore_import_execution_summary_message(
    *,
    restored_mod_count: int,
    restored_config_count: int,
    replaced_mod_count: int,
    replaced_config_count: int,
    covered_config_count: int,
    review_entry_count: int,
    blocked_entry_count: int,
    deferred_item_count: int,
) -> str:
    message = (
        "Restore/import execution completed: "
        f"{restored_mod_count} mod folder(s) and {restored_config_count} config artifact(s) restored."
    )
    if replaced_mod_count > 0:
        message += f" {replaced_mod_count} mod folder(s) were archive-and-replaced."
    if replaced_config_count > 0:
        message += (
            f" {replaced_config_count} conflicting config artifact(s) were resolved by "
            "archive-and-replacing the containing mod folder."
        )
    if covered_config_count > 0:
        message += f" {covered_config_count} config artifact(s) were already covered by restored mod folders."
    if review_entry_count > 0 or blocked_entry_count > 0 or deferred_item_count > 0:
        message += " Review, blocked, and deferred bundle content was left untouched."
    return message


def _rollback_restore_import_paths(
    *,
    archived_target_restores: tuple[tuple[Path, Path], ...],
    restored_mod_paths: tuple[Path, ...],
    restored_config_paths: tuple[Path, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    for path in reversed(restored_config_paths):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            warnings.append(f"Could not remove restored config artifact {path}: {exc}")
    for path in reversed(restored_mod_paths):
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError as exc:
            warnings.append(f"Could not remove restored mod folder {path}: {exc}")
    for archived_path, restore_target in reversed(archived_target_restores):
        try:
            if archived_path.exists() and not restore_target.exists():
                archived_path.rename(restore_target)
        except OSError as exc:
            warnings.append(f"Could not restore archived target {archived_path}: {exc}")
    return tuple(warnings)


def _restore_import_config_directory_message(
    *,
    label: str,
    state: RestoreImportPlanningItemState,
    safe_count: int,
    review_count: int,
    blocked_count: int,
) -> str:
    if state == "blocked":
        return (
            f"{label} planning is blocked: {blocked_count} blocked, "
            f"{review_count} need review, {safe_count} look safe."
        )
    if state == "needs_review":
        return (
            f"{label} planning found review points: {review_count} need review, "
            f"{safe_count} look safe."
        )
    return f"{label} planning looks straightforward: {safe_count} safe, 0 blocked."


def _summarize_bundle_config_mismatches(
    *,
    bundle_config: AppConfig | None,
    local_targets: _RestoreImportPlanningLocalTargets,
) -> str | None:
    if bundle_config is None:
        return None

    mismatches: list[str] = []
    if local_targets.real_mods_path is not None and bundle_config.mods_path != local_targets.real_mods_path:
        mismatches.append("real Mods path differs from the current local setup")
    if (
        bundle_config.sandbox_mods_path != local_targets.sandbox_mods_path
        and not (
            bundle_config.sandbox_mods_path is None and local_targets.sandbox_mods_path is None
        )
    ):
        mismatches.append("sandbox Mods path differs from the current local setup")
    if (
        bundle_config.real_archive_path != local_targets.real_archive_path
        and not (
            bundle_config.real_archive_path is None and local_targets.real_archive_path is None
        )
    ):
        mismatches.append("real archive path differs from the current local setup")
    if (
        bundle_config.sandbox_archive_path != local_targets.sandbox_archive_path
        and not (
            bundle_config.sandbox_archive_path is None
            and local_targets.sandbox_archive_path is None
        )
    ):
        mismatches.append("sandbox archive path differs from the current local setup")
    if not mismatches:
        return None
    return "Bundle config mismatch: " + "; ".join(mismatches) + "."


def _restore_import_directory_target_is_ready(path: Path) -> bool:
    if path.exists():
        return path.is_dir()
    return path.parent.exists() and path.parent.is_dir()


def _count_directory_children(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for _ in path.iterdir())
    except OSError:
        return 0


def _dedupe_text_lines(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return tuple(deduped)


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


def _is_path_within_or_equal(candidate: Path, container: Path) -> bool:
    candidate_resolved = candidate.expanduser().resolve(strict=False)
    container_resolved = container.expanduser().resolve(strict=False)

    if candidate_resolved == container_resolved:
        return True

    try:
        return candidate_resolved.is_relative_to(container_resolved)
    except ValueError:
        return False


def _directory_copy_signature(root: Path) -> tuple[tuple[str, str, int | str], ...]:
    root_resolved = root.expanduser().resolve(strict=False)
    entries: list[tuple[str, str, int | str]] = []
    for path in sorted(root_resolved.rglob("*"), key=lambda candidate: candidate.as_posix().casefold()):
        relative_text = path.relative_to(root_resolved).as_posix()
        if path.is_dir():
            entries.append(("dir", relative_text, 0))
            continue
        if not path.is_file():
            entries.append(("other", relative_text, 0))
            continue
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            while True:
                chunk = source_file.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        entries.append(("file", relative_text, f"{path.stat().st_size}:{digest.hexdigest()}"))
    return tuple(entries)


def _promotion_history_source_marker(
    *,
    sandbox_mods_path: Path,
    source_paths: tuple[Path, ...],
) -> Path:
    if len(source_paths) == 1:
        return source_paths[0]
    return sandbox_mods_path / ".sdvmm-sandbox-promotion-selection"


def _sorted_unique_ids(values: Iterable[str]) -> tuple[str, ...]:
    unique = {str(value) for value in values if str(value).strip()}
    return tuple(sorted(unique, key=str.casefold))


def _build_mods_compare_result(
    *,
    real_mods_path: Path,
    sandbox_mods_path: Path,
    real_inventory: ModsInventory,
    sandbox_inventory: ModsInventory,
) -> ModsCompareResult:
    real_groups = _group_installed_mods_for_compare(real_inventory.mods)
    sandbox_groups = _group_installed_mods_for_compare(sandbox_inventory.mods)
    all_keys = sorted(set(real_groups) | set(sandbox_groups), key=str.casefold)
    entries: list[ModsCompareEntry] = []

    for key in all_keys:
        real_group = real_groups.get(key, tuple())
        sandbox_group = sandbox_groups.get(key, tuple())
        if len(real_group) > 1 or len(sandbox_group) > 1:
            reference_mod = (real_group or sandbox_group)[0]
            notes: list[str] = []
            if len(real_group) > 1:
                notes.append(f"real Mods has {len(real_group)} folders with this UniqueID")
            if len(sandbox_group) > 1:
                notes.append(f"sandbox Mods has {len(sandbox_group)} folders with this UniqueID")
            entries.append(
                ModsCompareEntry(
                    match_key=key,
                    unique_id=reference_mod.unique_id,
                    name=reference_mod.name,
                    state="ambiguous_match",
                    real_mod=real_group[0] if real_group else None,
                    sandbox_mod=sandbox_group[0] if sandbox_group else None,
                    note=". ".join(notes) + ".",
                )
            )
            continue

        real_mod = real_group[0] if real_group else None
        sandbox_mod = sandbox_group[0] if sandbox_group else None
        reference_mod = real_mod or sandbox_mod
        assert reference_mod is not None

        if real_mod is None:
            state = "only_in_sandbox"
        elif sandbox_mod is None:
            state = "only_in_real"
        elif real_mod.version == sandbox_mod.version:
            state = "same_version"
        else:
            state = "version_mismatch"

        entries.append(
            ModsCompareEntry(
                match_key=key,
                unique_id=reference_mod.unique_id,
                name=reference_mod.name,
                state=state,
                real_mod=real_mod,
                sandbox_mod=sandbox_mod,
            )
        )

    entries.sort(
        key=lambda entry: (
            _mods_compare_state_sort_rank(entry.state),
            entry.name.casefold(),
            entry.unique_id.casefold(),
        )
    )

    return ModsCompareResult(
        real_mods_path=real_mods_path,
        sandbox_mods_path=sandbox_mods_path,
        real_inventory=real_inventory,
        sandbox_inventory=sandbox_inventory,
        entries=tuple(entries),
    )


def _group_installed_mods_for_compare(
    mods: tuple[InstalledMod, ...],
) -> dict[str, tuple[InstalledMod, ...]]:
    grouped: dict[str, list[InstalledMod]] = {}
    for mod in mods:
        key = canonicalize_unique_id(mod.unique_id)
        if not key:
            continue
        grouped.setdefault(key, []).append(mod)
    return {
        key: tuple(
            sorted(
                group,
                key=lambda entry: (entry.name.casefold(), str(entry.folder_path).casefold()),
            )
        )
        for key, group in grouped.items()
    }


def _mods_compare_state_label(state: str) -> str:
    if state == "only_in_real":
        return "only in real"
    if state == "only_in_sandbox":
        return "only in sandbox"
    if state == "same_version":
        return "same version"
    if state == "version_mismatch":
        return "version mismatch"
    if state == "ambiguous_match":
        return "ambiguous match"
    return state


def _mods_compare_state_sort_rank(state: str) -> int:
    if state == "only_in_real":
        return 0
    if state == "only_in_sandbox":
        return 1
    if state == "version_mismatch":
        return 2
    if state == "ambiguous_match":
        return 3
    if state == "same_version":
        return 4
    return 5


def _require_canonical_unique_id(unique_id: str) -> str:
    normalized = canonicalize_unique_id(unique_id)
    if not normalized:
        raise AppShellError("UniqueID is required.")
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _upsert_update_source_intent_record(
    records: tuple[UpdateSourceIntentRecord, ...],
    record: UpdateSourceIntentRecord,
) -> tuple[UpdateSourceIntentRecord, ...]:
    remaining = [
        existing
        for existing in records
        if existing.normalized_unique_id != record.normalized_unique_id
    ]
    remaining.append(record)
    remaining.sort(key=lambda item: item.normalized_unique_id)
    return tuple(remaining)


def _version_sort_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return tuple()
    numbers: list[int] = []
    for token in version.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if not digits:
            numbers.append(0)
            continue
        numbers.append(int(digits))
    return tuple(numbers)


def _discovery_entry_unique_id_keys(entry: ModDiscoveryEntry) -> tuple[str, ...]:
    candidates = [entry.unique_id, *entry.alternate_unique_ids]
    keys: dict[str, str] = {}
    for candidate in candidates:
        normalized = str(candidate).strip()
        if not normalized:
            continue
        key = canonicalize_unique_id(normalized)
        keys.setdefault(key, normalized)
    return tuple(keys.keys())


def _first_present(values_by_key: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in values_by_key:
            return values_by_key[key]
    return None


def _build_discovery_provider_relation(
    *,
    discovery_source_provider: str,
    tracked_provider: str | None,
) -> tuple[str, str | None]:
    if tracked_provider is None:
        return ("no_update_provider_context", None)

    if discovery_source_provider not in {"nexus", "github"}:
        return (
            "provider_not_comparable",
            "Tracked update provider exists, but discovery source is custom/other.",
        )

    if discovery_source_provider == tracked_provider:
        return (
            "provider_aligned",
            f"Discovery source matches tracked update provider ({_provider_label(tracked_provider)}).",
        )

    return (
        "provider_mismatch",
        "Discovery source differs from tracked update provider "
        f"({_provider_label(discovery_source_provider)} vs {_provider_label(tracked_provider)}).",
    )


def _build_discovery_context_messages(
    *,
    installed_match_unique_id: str | None,
    update_state: str | None,
) -> tuple[str, str]:
    if installed_match_unique_id is None:
        return (
            "Not currently installed in the scanned inventory",
            (
                "Open source page, download manually, let watcher detect the zip, "
                "then plan a safe install."
            ),
        )

    if update_state == "update_available":
        return (
            f"Already installed ({installed_match_unique_id}); update is available in current metadata report",
            (
                "Open source page, download manually, let watcher detect the zip, "
                "then plan a safe update/replace."
            ),
        )

    if update_state == "up_to_date":
        return (
            f"Already installed ({installed_match_unique_id}); currently marked up to date",
            (
                "Open source page only if you intentionally want a manual reinstall or alternate build. "
                "If downloaded, continue via watcher -> intake -> plan."
            ),
        )

    if update_state == "metadata_unavailable":
        return (
            f"Already installed ({installed_match_unique_id}); update metadata currently unavailable",
            (
                "Open source page and continue manual flow if needed. You can also run Check updates again "
                "after fixing metadata/provider issues."
            ),
        )

    if update_state == "no_remote_link":
        return (
            f"Already installed ({installed_match_unique_id}); no tracked remote link in update report",
            (
                "Use discovery source page as manual source. Download manually, then continue via watcher "
                "-> intake -> plan."
            ),
        )

    return (
        f"Already installed ({installed_match_unique_id}); update state not checked yet",
        "Run Check updates for richer context, or continue manual watcher -> intake -> plan flow.",
    )


def _provider_label(provider: str) -> str:
    labels = {
        "nexus": "Nexus",
        "github": "GitHub",
        "json": "JSON",
        "custom_url": "Custom URL",
    }
    return labels.get(provider, provider)


def _collect_install_execution_review_warnings(
    plan: SandboxInstallPlan,
) -> tuple[str, ...]:
    warnings: list[str] = []

    for warning in plan.plan_warnings:
        text = warning.strip()
        if text:
            warnings.append(text)

    for warning in plan.package_warnings:
        text = warning.message.strip()
        if text:
            warnings.append(text)

    for entry in plan.entries:
        for warning in entry.warnings:
            text = warning.strip()
            if text:
                warnings.append(f"{entry.name}: {text}")

    deduped: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if warning in seen:
            continue
        seen.add(warning)
        deduped.append(warning)
    return tuple(deduped)


def _build_sandbox_install_review_message(summary: InstallExecutionSummary) -> str:
    message = (
        f"Sandbox install can proceed for {summary.total_entry_count} "
        f"{_entry_count_label(summary.total_entry_count)}."
    )
    if summary.has_existing_targets_to_replace or summary.has_archive_writes:
        message += " Inspect archive/replace actions before execution."
    else:
        message += " No explicit approval is required."
    return message


def _build_real_install_review_message(summary: InstallExecutionSummary) -> str:
    message = (
        f"Real Mods install targets {summary.total_entry_count} "
        f"{_entry_count_label(summary.total_entry_count)} in {summary.destination_mods_path}. "
        "Explicit approval is required before execution."
    )
    if summary.has_existing_targets_to_replace or summary.has_archive_writes:
        message += " Inspect archive/replace actions carefully."
    return message


def _entry_count_label(count: int) -> str:
    return "entry" if count == 1 else "entries"


def _normalize_sandbox_promotion_error(
    exc: AppShellError | SandboxInstallError | OSError,
) -> AppShellError:
    if isinstance(exc, AppShellError):
        return exc
    if isinstance(exc, SandboxInstallError):
        return AppShellError(f"Sandbox promotion failed: {exc}")
    return AppShellError(f"Sandbox promotion failed: {exc}")


def _remove_path_for_promotion_rollback(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _restore_import_item_state_label(state: str) -> str:
    labels = {
        "safe_to_restore_later": "Safe later",
        "needs_review": "Needs review",
        "blocked": "Blocked",
    }
    return labels.get(state, state.replace("_", " ").title())


def _restore_import_mod_state_label(state: str) -> str:
    labels = {
        "missing_locally": "Missing locally",
        "same_version": "Same version",
        "different_version": "Different version",
        "bundle_unusable": "Bundle unusable",
        "destination_not_ready": "Destination not ready",
        "ambiguous_match": "Ambiguous",
    }
    return labels.get(state, state.replace("_", " ").title())


def _restore_import_config_state_label(state: str) -> str:
    labels = {
        "missing_locally": "Missing locally",
        "same_content": "Same content",
        "different_content": "Different content",
        "bundle_unusable": "Bundle unusable",
        "destination_not_ready": "Destination not ready",
    }
    return labels.get(state, state.replace("_", " ").title())


def build_mods_compare_text(result: ModsCompareResult) -> str:
    counts = Counter(entry.state for entry in result.entries)
    lines = [
        "Real vs sandbox Mods compare",
        f"Real Mods path: {result.real_mods_path}",
        f"Sandbox Mods path: {result.sandbox_mods_path}",
        f"Only in real: {counts.get('only_in_real', 0)}",
        f"Only in sandbox: {counts.get('only_in_sandbox', 0)}",
        f"Same version: {counts.get('same_version', 0)}",
        f"Version mismatch: {counts.get('version_mismatch', 0)}",
        f"Ambiguous match: {counts.get('ambiguous_match', 0)}",
    ]
    parse_warning_total = (
        len(result.real_inventory.parse_warnings) + len(result.sandbox_inventory.parse_warnings)
    )
    if parse_warning_total:
        lines.append(
            f"Additional scan warnings outside direct compare rows: {parse_warning_total}"
        )

    lines.extend(
        (
            "",
            "Category guide:",
            "- only in real / only in sandbox: the mod exists on one side only.",
            "- version mismatch: the same UniqueID exists in both places, but the versions differ.",
            "- ambiguous match: duplicate folders share a UniqueID, so compare cannot identify one clean match.",
            "- same version: the same UniqueID and version exist in both places.",
        )
    )

    lines.extend(("", "Compared rows:"))
    if not result.entries:
        lines.append("- No installed mods were found in either location.")
        return "\n".join(lines)

    for entry in result.entries:
        real_version = entry.real_mod.version if entry.real_mod is not None else "-"
        sandbox_version = entry.sandbox_mod.version if entry.sandbox_mod is not None else "-"
        note = f" | {entry.note}" if entry.note else ""
        lines.append(
            f"- {entry.name} ({entry.unique_id}) [{_mods_compare_state_label(entry.state)}] "
            f"real={real_version} sandbox={sandbox_version}{note}"
        )
    return "\n".join(lines)


def build_restore_import_planning_text(result: RestoreImportPlanningResult) -> str:
    mod_entries_by_item: dict[str, list[RestoreImportPlanningModEntry]] = {}
    for entry in result.mod_entries:
        mod_entries_by_item.setdefault(entry.bundle_item_key, []).append(entry)
    config_entries_by_item: dict[str, list[RestoreImportPlanningConfigEntry]] = {}
    for entry in result.config_entries:
        config_entries_by_item.setdefault(entry.bundle_item_key, []).append(entry)

    lines = [
        "Cinderleaf restore/import planning",
        f"Bundle artifact: {result.bundle_path}",
        f"Inspection summary: {result.inspection.message}",
        f"Planning summary: {result.message}",
        (
            "Matching rule: bundled real/sandbox mod folders are matched to the current local "
            "destination by canonicalized UniqueID."
        ),
        "Safe later: bundle content is missing locally or already matches locally.",
        "Needs review: local versions differ, config differs, or local data already exists.",
        "Blocked: bundle content is structurally unusable, not included, or the local destination is not ready.",
        f"Item summary: safe {result.safe_item_count}, review {result.review_item_count}, blocked {result.blocked_item_count}",
        f"Bundled mod rows: safe {result.safe_mod_count}, review {result.review_mod_count}, blocked {result.blocked_mod_count}",
        f"Bundled config artifacts: safe {result.safe_config_count}, review {result.review_config_count}, blocked {result.blocked_config_count}",
    ]

    if result.warnings:
        lines.extend(("", "Warnings:"))
        lines.extend(f"- {warning}" for warning in result.warnings)

    if result.items:
        lines.extend(("", "Planned items:"))
        for item in result.items:
            local_target = str(item.local_target_path) if item.local_target_path is not None else "<none>"
            note_text = f" | {item.note}" if item.note else ""
            lines.append(
                f"- {item.label} [{_restore_import_item_state_label(item.state)}]: "
                f"{item.message} | bundle={item.bundle_relative_path} | local={local_target}{note_text}"
            )
            for entry in mod_entries_by_item.get(item.key, []):
                local_version = entry.local_version or "-"
                bundle_version = entry.bundle_version or "-"
                mod_note = f" | {entry.note}" if entry.note else ""
                lines.append(
                    f"  - {entry.name} ({entry.unique_id}) "
                    f"[{_restore_import_mod_state_label(entry.state)}] "
                    f"bundle={bundle_version} local={local_version}{mod_note}"
                )
            for entry in config_entries_by_item.get(item.key, []):
                local_target = (
                    str(entry.local_target_path)
                    if entry.local_target_path is not None
                    else "<none>"
                )
                config_note = f" | {entry.note}" if entry.note else ""
                lines.append(
                    f"  - config {entry.relative_path} "
                    f"[{_restore_import_config_state_label(entry.state)}] "
                    f"local={local_target}{config_note}"
                )
    else:
        lines.extend(("", "Planned items:", "- No readable bundle items were available for planning."))

    return "\n".join(lines)


def build_restore_import_execution_result_text(
    result: RestoreImportExecutionResult,
) -> str:
    missing_mod_count = result.restored_mod_count - result.replaced_mod_count
    missing_config_count = result.restored_config_count
    lines = [
        "Cinderleaf restore/import execution",
        f"Bundle artifact: {result.bundle_path}",
        f"Summary: {result.message}",
        "Execution rule: missing content may be restored directly, while reviewed conflicts use archive-aware mod-folder replacement.",
        "No file merge behavior was used in this stage.",
        f"Restored mod folders: {result.restored_mod_count} (missing restores: {missing_mod_count}, reviewed replaces: {result.replaced_mod_count})",
        f"Restored config artifacts: {result.restored_config_count} (missing restores: {missing_config_count}, conflict-driven replaces: {result.replaced_config_count})",
        f"Archived local targets before replacement: {len(result.archived_target_paths)}",
        f"Config artifacts already covered by restored mod folders: {result.covered_config_count}",
        f"Skipped review entries: {result.skipped_review_entry_count}",
        f"Skipped blocked entries: {result.skipped_blocked_entry_count}",
        f"Deferred non-execution bundle items: {result.deferred_item_count}",
    ]

    if result.warnings:
        lines.extend(("", "Warnings:"))
        lines.extend(f"- {warning}" for warning in result.warnings)

    if result.restored_mod_paths:
        lines.extend(("", "Restored mod folders:"))
        lines.extend(f"- {path}" for path in result.restored_mod_paths)

    if result.restored_config_paths:
        lines.extend(("", "Restored config artifacts:"))
        lines.extend(f"- {path}" for path in result.restored_config_paths)

    if result.archived_target_paths:
        lines.extend(("", "Archived local targets:"))
        lines.extend(f"- {path}" for path in result.archived_target_paths)

    if not result.restored_mod_paths and not result.restored_config_paths:
        lines.extend(
            (
                "",
                "Restored content:",
                "- No content was written.",
            )
        )

    return "\n".join(lines)


def build_backup_bundle_inspection_text(result: BackupBundleInspectionResult) -> str:
    declared_counts = Counter(item.declared_status for item in result.items)
    structure_counts = Counter(item.structure_state for item in result.items)
    lines = [
        "Cinderleaf backup bundle inspection",
        f"Bundle artifact: {result.bundle_path}",
        f"Bundle storage: {result.bundle_storage_kind}",
        (
            "Manifest entry: manifest.json inside the zip bundle"
            if result.bundle_storage_kind == "zip"
            else f"Manifest: {result.manifest_path}"
        ),
        (
            "Summary entry: README.txt inside the zip bundle"
            if result.bundle_storage_kind == "zip"
            else f"Summary: {result.summary_path}"
        ),
        (
            f"Bundle format: {result.bundle_format} (v{result.format_version})"
            if result.bundle_format is not None and result.format_version is not None
            else "Bundle format: unavailable"
        ),
        f"Created at (UTC): {result.created_at_utc or '-'}",
        f"Structurally usable for future restore/import: {'yes' if result.structurally_usable else 'no'}",
        f"Declared copied items: {declared_counts.get('copied', 0)}",
        f"Present copied items: {structure_counts.get('present', 0)}",
        f"Missing expected copied items: {structure_counts.get('missing_expected', 0)}",
        f"Unexpected present items: {structure_counts.get('unexpected_present', 0)}",
    ]
    if result.bundle_storage_kind == "zip":
        lines.append(
            "Read mode: zip bundle is inspected from a temporary extracted working copy."
        )
    if result.warnings:
        lines.extend(("", "Warnings:"))
        lines.extend(f"- {warning}" for warning in result.warnings)
    if result.items:
        lines.extend(("", "Bundle items:"))
        for item in result.items:
            note_text = f" | {item.note}" if item.note else ""
            lines.append(
                f"- {item.label}: declared={item.declared_status}, actual={item.structure_state}, "
                f"path={item.relative_path}{note_text}"
            )
    else:
        lines.extend(("", "Bundle items:", "- No readable manifest items were available."))
    if result.intentionally_not_included:
        lines.extend(("", "Intentionally not included:"))
        lines.extend(f"- {item}" for item in result.intentionally_not_included)
    return "\n".join(lines)


def build_backup_bundle_export_text(result: BackupBundleExportResult) -> str:
    copied_items = tuple(item for item in result.items if item.status == "copied")
    unavailable_items = tuple(item for item in result.items if item.status != "copied")
    lines = [
        "Cinderleaf backup export",
        f"Created at (UTC): {result.created_at_utc}",
        f"Bundle artifact: {result.bundle_path}",
        f"Bundle storage: {result.bundle_storage_kind}",
        (
            "Manifest entry: manifest.json inside the zip bundle"
            if result.bundle_storage_kind == "zip"
            else f"Manifest: {result.manifest_path}"
        ),
        (
            "Summary entry: README.txt inside the zip bundle"
            if result.bundle_storage_kind == "zip"
            else f"Summary: {result.summary_path}"
        ),
        "",
        "Copied into this bundle:",
    ]
    if copied_items:
        for item in copied_items:
            note = f" ({item.note})" if item.note else ""
            if item.source_path is None:
                lines.append(f"- {item.label}: {item.relative_path}{note}")
                continue
            lines.append(f"- {item.label}: {item.relative_path} <- {item.source_path}{note}")
    else:
        lines.append("- Nothing was copied.")

    lines.extend(("", "Unavailable or skipped:"))
    if unavailable_items:
        for item in unavailable_items:
            note = f" ({item.note})" if item.note else ""
            source_path = str(item.source_path) if item.source_path is not None else "<none>"
            lines.append(
                f"- {item.label}: {item.status} | source={source_path} | bundle={item.relative_path}{note}"
            )
    else:
        lines.append("- None.")

    lines.extend(
        (
            "",
            "This export intentionally does not include:",
            "- Game binaries, Steam files, or SMAPI runtime executables.",
            "- Watcher download folders or unmanaged caches.",
            "- Only the artifact groups selected in the export dialog are included; unselected groups are recorded as not_present in the manifest.",
            "- Transient UI state such as selections, filters, or pending plans.",
            "- Restore/import automation. This bundle is export-only in this stage.",
        )
    )
    return "\n".join(lines) + "\n"


def _derive_install_operation_recovery_entry(
    operation: InstallOperationRecord,
    entry: InstallOperationEntryRecord,
) -> InstallRecoveryPlanEntry:
    if entry.action == INSTALL_NEW:
        if _operation_record_contains_path(operation.installed_targets, entry.target_path):
            return InstallRecoveryPlanEntry(
                name=entry.name,
                unique_id=entry.unique_id,
                version=entry.version,
                action="remove_installed_target",
                target_path=entry.target_path,
                archive_path=entry.archive_path,
                recoverable=True,
                message=f"Remove installed target recorded for {entry.name}.",
                warnings=entry.warnings,
            )
        return InstallRecoveryPlanEntry(
            name=entry.name,
            unique_id=entry.unique_id,
            version=entry.version,
            action="not_recoverable",
            target_path=entry.target_path,
            archive_path=entry.archive_path,
            recoverable=False,
            message=(
                f"{entry.name} is not safely recoverable: the install history does not "
                "record the installed target for removal."
            ),
            warnings=entry.warnings,
        )

    if entry.action == OVERWRITE_WITH_ARCHIVE:
        if entry.archive_path is None:
            return InstallRecoveryPlanEntry(
                name=entry.name,
                unique_id=entry.unique_id,
                version=entry.version,
                action="not_recoverable",
                target_path=entry.target_path,
                archive_path=entry.archive_path,
                recoverable=False,
                message=(
                    f"{entry.name} is not safely recoverable: no archived target was recorded "
                    "for restoration."
                ),
                warnings=entry.warnings,
            )
        if not _operation_record_contains_path(operation.archived_targets, entry.archive_path):
            return InstallRecoveryPlanEntry(
                name=entry.name,
                unique_id=entry.unique_id,
                version=entry.version,
                action="not_recoverable",
                target_path=entry.target_path,
                archive_path=entry.archive_path,
                recoverable=False,
                message=(
                    f"{entry.name} is not safely recoverable: the recorded archive target "
                    "cannot be matched for restoration."
                ),
                warnings=entry.warnings,
            )
        return InstallRecoveryPlanEntry(
            name=entry.name,
            unique_id=entry.unique_id,
            version=entry.version,
            action="restore_from_archive",
            target_path=entry.target_path,
            archive_path=entry.archive_path,
            recoverable=True,
            message=f"Restore archived target recorded for {entry.name}.",
            warnings=entry.warnings,
        )

    return InstallRecoveryPlanEntry(
        name=entry.name,
        unique_id=entry.unique_id,
        version=entry.version,
        action="not_recoverable",
        target_path=entry.target_path,
        archive_path=entry.archive_path,
        recoverable=False,
        message=(
            f"{entry.name} is not safely recoverable: recorded action "
            f"{entry.action!r} is not supported for recovery."
        ),
        warnings=entry.warnings,
    )


def _operation_record_contains_path(paths: tuple[Path, ...], expected: Path) -> bool:
    return any(_paths_deterministically_match(path, expected) for path in paths)


def _review_install_recovery_entry(
    entry: InstallRecoveryPlanEntry,
) -> InstallRecoveryExecutionReviewEntry:
    if entry.action == "remove_installed_target":
        if entry.target_path.exists():
            return InstallRecoveryExecutionReviewEntry(
                plan_entry=entry,
                executable=True,
                decision_code="removal_ready",
                message=f"Removal target exists for {entry.name}.",
            )
        return InstallRecoveryExecutionReviewEntry(
            plan_entry=entry,
            executable=False,
            decision_code="removal_target_missing",
            message=f"Removal target is missing for {entry.name}.",
        )

    if entry.action == "restore_from_archive":
        if entry.archive_path is not None and entry.archive_path.exists():
            return InstallRecoveryExecutionReviewEntry(
                plan_entry=entry,
                executable=True,
                decision_code="restore_ready",
                message=f"Archive source exists for restoring {entry.name}.",
            )
        return InstallRecoveryExecutionReviewEntry(
            plan_entry=entry,
            executable=False,
            decision_code="restore_archive_missing",
            message=f"Archive source is missing for restoring {entry.name}.",
        )

    return InstallRecoveryExecutionReviewEntry(
        plan_entry=entry,
        executable=False,
        decision_code="entry_not_recoverable",
        message=entry.message,
    )


def _remove_recovery_target(target_path: Path) -> None:
    if target_path.is_dir():
        shutil.rmtree(target_path)
        return
    target_path.unlink()


def _annotate_archive_retention_entries(
    entries: tuple[ArchivedModEntry, ...],
    *,
    keep_latest_count: int,
) -> tuple[ArchivedModEntry, ...]:
    if not entries:
        return tuple()

    grouped_entries: dict[tuple[str, str, str], list[ArchivedModEntry]] = {}
    for entry in entries:
        grouped_entries.setdefault(_archive_retention_group_key(entry), []).append(entry)

    annotated_entries: list[ArchivedModEntry] = []
    for group_entries in grouped_entries.values():
        sorted_group = sorted(
            group_entries,
            key=_archive_retention_sort_key,
            reverse=True,
        )
        total_entries = len(sorted_group)
        for position, entry in enumerate(sorted_group, start=1):
            annotated_entries.append(
                replace(
                    entry,
                    retention_position=position,
                    retention_total=total_entries,
                    retention_keep_limit=keep_latest_count,
                    retention_cleanup_candidate=position > keep_latest_count,
                )
            )

    annotated_entries.sort(
        key=lambda entry: (
            0 if entry.source_kind == ARCHIVE_SOURCE_REAL else 1,
            entry.target_folder_name.casefold(),
            entry.retention_cleanup_candidate,
            entry.retention_position,
            entry.archived_folder_name.casefold(),
        )
    )
    return tuple(annotated_entries)


def _build_archive_retention_groups(
    entries: tuple[ArchivedModEntry, ...],
    *,
    keep_latest_count: int,
    only_cleanup_groups: bool,
) -> tuple[ArchiveRetentionGroup, ...]:
    grouped_entries: dict[tuple[str, str, str], list[ArchivedModEntry]] = {}
    for entry in entries:
        grouped_entries.setdefault(_archive_retention_group_key(entry), []).append(entry)

    groups: list[ArchiveRetentionGroup] = []
    for group_entries in grouped_entries.values():
        sorted_group = sorted(
            group_entries,
            key=_archive_retention_sort_key,
            reverse=True,
        )
        cleanup_candidate_count = sum(
            1 for entry in sorted_group if entry.retention_cleanup_candidate
        )
        if only_cleanup_groups and cleanup_candidate_count == 0:
            continue

        first_entry = sorted_group[0]
        groups.append(
            ArchiveRetentionGroup(
                source_kind=first_entry.source_kind,
                target_folder_name=first_entry.target_folder_name,
                mod_name=first_entry.mod_name,
                unique_id=first_entry.unique_id,
                total_entries=len(sorted_group),
                kept_entry_count=min(len(sorted_group), keep_latest_count),
                cleanup_candidate_count=max(len(sorted_group) - keep_latest_count, 0),
            )
        )

    groups.sort(
        key=lambda group: (
            0 if group.source_kind == ARCHIVE_SOURCE_REAL else 1,
            group.target_folder_name.casefold(),
            (group.mod_name or "").casefold(),
            (group.unique_id or "").casefold(),
        )
    )
    return tuple(groups)


def _archive_retention_group_key(entry: ArchivedModEntry) -> tuple[str, str, str]:
    unique_id = entry.unique_id.strip() if entry.unique_id else ""
    identity_key = (
        canonicalize_unique_id(unique_id)
        if unique_id
        else f"folder:{entry.target_folder_name.casefold()}"
    )
    return (
        entry.source_kind,
        identity_key,
        entry.target_folder_name.casefold(),
    )


def _archive_retention_sort_key(entry: ArchivedModEntry) -> tuple[int, int, float, str]:
    sequence_number = _archive_sequence_number(entry.archived_folder_name)
    return (
        1 if sequence_number is not None else 0,
        sequence_number or -1,
        _safe_path_mtime(entry.archived_path),
        entry.archived_folder_name.casefold(),
    )


def _archive_sequence_number(archived_folder_name: str) -> int | None:
    match = _ARCHIVE_SUFFIX_SEQUENCE_PATTERN.match(archived_folder_name)
    if match is None:
        return None
    try:
        return int(match.group("sequence"))
    except ValueError:
        return None


def _safe_path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def _new_operation_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _build_intake_flow_messages(
    *,
    intake: DownloadsIntakeResult,
    actionable: bool,
    comparison_target_label: str,
    comparison_state: str,
    version_comparisons: tuple[IntakeVersionComparison, ...],
    matched_update_available: tuple[str, ...],
    matched_guided: tuple[str, ...],
) -> tuple[str, str]:
    if not actionable:
        return (
            "Detected package is unusable for install planning.",
            "Fix or replace this package before planning (non-actionable).",
        )

    if comparison_state == "target_inventory_unavailable":
        return (
            f"Packages are set to compare against {comparison_target_label}, but that inventory has not been scanned in this session yet.",
            f"Scan {comparison_target_label} if you want truthful version comparison, or use Open Install for a manual plan now.",
        )

    if comparison_state == "newer_than_installed":
        detail = _first_version_comparison_detail(version_comparisons)
        if matched_guided:
            joined = ", ".join(matched_guided)
            return (
                f"Package is newer than the installed version in {comparison_target_label}. {detail} Guided target match: {joined}.",
                f"Use Open as update for {comparison_target_label}, then confirm the archive-aware replace plan.",
            )
        if matched_update_available:
            joined = ", ".join(matched_update_available)
            return (
                f"Package is newer than the installed version in {comparison_target_label}. {detail} Update-available match: {joined}.",
                f"Use Open as update for {comparison_target_label}, then confirm the archive-aware replace plan.",
            )
        return (
            f"Package is newer than the installed version in {comparison_target_label}. {detail}",
            f"Use Open as update for {comparison_target_label}, then confirm the archive-aware replace plan.",
        )

    if comparison_state == "same_version_installed":
        return (
            f"Same version is already installed in {comparison_target_label}. {_first_version_comparison_detail(version_comparisons)}",
            "Open Install stays available for inspection, but this package is not a truthful update candidate.",
        )

    if comparison_state == "older_than_installed":
        return (
            f"Installed version in {comparison_target_label} is newer than this package. {_first_version_comparison_detail(version_comparisons)}",
            "Open Install if you still need a manual check, but Open as update stays off for older packages.",
        )

    if comparison_state == "not_installed_in_target":
        return (
            f"This package is not installed in {comparison_target_label} yet.",
            f"Use Open Install to plan it as a new install against {comparison_target_label}.",
        )

    if comparison_state == "version_comparison_unavailable":
        return (
            f"Version comparison against {comparison_target_label} is unavailable for this package. {_first_version_comparison_detail(version_comparisons)}",
            "Open Install if you need manual inspection. Open as update stays off until the version comparison is clear.",
        )

    if comparison_state == "mixed_version_state":
        return (
            f"This package has mixed install/update state against {comparison_target_label}. {_first_version_comparison_detail(version_comparisons)}",
            "Open Install for a manual inspection. Open as update stays off because the package is not a clear newer-than-installed update.",
        )

    if intake.classification == "multi_mod_package":
        return (
            f"Detected package contains multiple mods for {comparison_target_label}.",
            "Open Install and inspect the per-entry plan before any write action.",
        )

    return (
        f"Detected package is ready to install against {comparison_target_label}.",
        "Use Open Install to continue into the read-only install plan.",
    )


def _build_legacy_intake_flow_messages(
    *,
    intake: DownloadsIntakeResult,
    actionable: bool,
    matched_update_available: tuple[str, ...],
    matched_guided: tuple[str, ...],
) -> tuple[str, str]:
    if not actionable:
        return (
            "Detected package is unusable for install planning.",
            "Fix or replace this package before planning (non-actionable).",
        )

    if matched_guided:
        joined = ", ".join(matched_guided)
        return (
            f"Detected package matches a guided update target: {joined}.",
            "Open as update for archive-aware planning before install.",
        )

    if matched_update_available:
        joined = ", ".join(matched_update_available)
        return (
            f"Detected package matches an installed mod with an update available: {joined}.",
            "Open as update for archive-aware planning before install.",
        )

    if intake.classification == "new_install_candidate":
        return (
            "Detected package is a new install candidate.",
            "Open Install to plan install and inspect the read-only summary.",
        )

    if intake.classification == "multi_mod_package":
        return (
            "Detected package contains multiple mods.",
            "Open Install to inspect the per-entry install plan before any write action.",
        )

    return (
        "Detected package is ready to install.",
        "Open Install to continue into the read-only install plan.",
    )


def _packages_comparison_target_label(target: ScanTargetKind | None) -> str:
    if target == SCAN_TARGET_SANDBOX_MODS:
        return "Sandbox Mods"
    return "Real Mods"


def _compare_intake_against_inventory(
    *,
    intake: DownloadsIntakeResult,
    inventory: ModsInventory | None,
) -> tuple[IntakeVersionComparison, ...]:
    if inventory is None:
        return tuple()

    installed_by_unique_id = {
        canonicalize_unique_id(mod.unique_id): mod
        for mod in inventory.mods
    }
    comparisons: list[IntakeVersionComparison] = []
    for package_mod in intake.mods:
        installed = installed_by_unique_id.get(canonicalize_unique_id(package_mod.unique_id))
        if installed is None:
            comparisons.append(
                IntakeVersionComparison(
                    package_name=package_mod.name,
                    package_unique_id=package_mod.unique_id,
                    package_version=package_mod.version,
                    installed_name=None,
                    installed_unique_id=None,
                    installed_version=None,
                    state="not_installed",
                )
            )
            continue

        comparison = compare_versions(installed.version, package_mod.version)
        if comparison is None:
            comparison_state = "unavailable"
        elif comparison < 0:
            comparison_state = "newer"
        elif comparison == 0:
            comparison_state = "same"
        else:
            comparison_state = "older"
        comparisons.append(
            IntakeVersionComparison(
                package_name=package_mod.name,
                package_unique_id=package_mod.unique_id,
                package_version=package_mod.version,
                installed_name=installed.name,
                installed_unique_id=installed.unique_id,
                installed_version=installed.version,
                state=comparison_state,
            )
        )
    return tuple(comparisons)


def _resolve_package_comparison_state(
    *,
    inventory: ModsInventory | None,
    comparisons: tuple[IntakeVersionComparison, ...],
) -> str:
    if inventory is None:
        return "target_inventory_unavailable"
    if not comparisons:
        return "not_installed_in_target"

    states = {entry.state for entry in comparisons}
    if states == {"not_installed"}:
        return "not_installed_in_target"
    if states == {"newer"}:
        return "newer_than_installed"
    if states == {"same"}:
        return "same_version_installed"
    if states == {"older"}:
        return "older_than_installed"
    if "unavailable" in states:
        return "version_comparison_unavailable"
    return "mixed_version_state"


def _first_version_comparison_detail(
    comparisons: tuple[IntakeVersionComparison, ...],
) -> str:
    if not comparisons:
        return "No installed comparison details are available yet."
    entry = comparisons[0]
    target_label = entry.installed_unique_id or entry.package_unique_id
    if entry.state == "not_installed":
        return f"{target_label} is not installed yet."
    if entry.state == "newer":
        return (
            f"{target_label}: installed {entry.installed_version or 'unknown'} -> "
            f"package {entry.package_version or 'unknown'}."
        )
    if entry.state == "same":
        return f"{target_label}: installed {entry.installed_version or 'unknown'} matches the package version."
    if entry.state == "older":
        return (
            f"{target_label}: installed {entry.installed_version or 'unknown'} is newer than "
            f"package {entry.package_version or 'unknown'}."
        )
    return (
        f"{target_label}: package {entry.package_version or 'unknown'} could not be compared against "
        f"installed {entry.installed_version or 'unknown'}."
    )


def _evaluate_sandbox_plan_dependencies(
    *,
    plan: SandboxInstallPlan,
    base_findings: tuple[DependencyPreflightFinding, ...],
    installed_inventory: ModsInventory,
) -> tuple[DependencyPreflightFinding, ...]:
    if not base_findings:
        return tuple()

    available_dependency_keys = {
        canonicalize_unique_id(mod.unique_id) for mod in installed_inventory.mods
    }
    available_dependency_keys.update(_installable_plan_dependency_keys(plan))

    findings: list[DependencyPreflightFinding] = []
    for finding in base_findings:
        dependency_key = canonicalize_unique_id(finding.dependency_unique_id)
        if dependency_key in available_dependency_keys:
            state = SATISFIED
        elif finding.required:
            state = MISSING_REQUIRED_DEPENDENCY
        else:
            state = OPTIONAL_DEPENDENCY_MISSING

        findings.append(
            replace(
                finding,
                source="sandbox_plan",
                state=state,
            )
        )

    findings.sort(
        key=lambda item: (
            item.source,
            item.state,
            canonicalize_unique_id(item.required_by_unique_id),
            canonicalize_unique_id(item.dependency_unique_id),
        )
    )
    return tuple(findings)


def _installable_plan_dependency_keys(plan: SandboxInstallPlan) -> set[str]:
    return {
        canonicalize_unique_id(entry.unique_id)
        for entry in plan.entries
        if entry.can_install and entry.action != BLOCKED
    }


def _apply_dependency_preflight_to_plan(
    plan: SandboxInstallPlan,
    dependency_findings: tuple[DependencyPreflightFinding, ...],
) -> SandboxInstallPlan:
    if not dependency_findings:
        return replace(plan, dependency_findings=tuple())

    required_missing_by_mod: dict[str, list[str]] = {}
    optional_missing_by_mod: dict[str, list[str]] = {}
    unresolved_by_mod: dict[str, list[str]] = {}

    for finding in dependency_findings:
        mod_key = canonicalize_unique_id(finding.required_by_unique_id)
        if finding.state == MISSING_REQUIRED_DEPENDENCY:
            required_missing_by_mod.setdefault(mod_key, []).append(finding.dependency_unique_id)
            continue
        if finding.state == OPTIONAL_DEPENDENCY_MISSING:
            optional_missing_by_mod.setdefault(mod_key, []).append(finding.dependency_unique_id)
            continue
        if finding.state == UNRESOLVED_DEPENDENCY_CONTEXT:
            unresolved_by_mod.setdefault(mod_key, []).append(finding.dependency_unique_id)

    updated_entries = []
    for entry in plan.entries:
        entry_warnings = list(entry.warnings)
        mod_key = canonicalize_unique_id(entry.unique_id)
        blocked = False

        missing_required_ids = sorted(set(required_missing_by_mod.get(mod_key, [])), key=str.casefold)
        if missing_required_ids:
            blocked = True
            deps_text = ", ".join(missing_required_ids)
            entry_warnings.append(
                f"Missing required dependencies: {deps_text}. Install dependencies first."
            )

        optional_missing_ids = sorted(set(optional_missing_by_mod.get(mod_key, [])), key=str.casefold)
        if optional_missing_ids:
            deps_text = ", ".join(optional_missing_ids)
            entry_warnings.append(
                f"Optional dependencies missing: {deps_text}. Mod may still load with reduced features."
            )

        unresolved_ids = sorted(set(unresolved_by_mod.get(mod_key, [])), key=str.casefold)
        if unresolved_ids:
            deps_text = ", ".join(unresolved_ids)
            entry_warnings.append(
                f"Dependency context unresolved: {deps_text}. Verify dependencies manually before install."
            )

        updated_entries.append(
            replace(
                entry,
                action=("blocked" if blocked else entry.action),
                can_install=(False if blocked else entry.can_install),
                warnings=tuple(entry_warnings),
            )
        )

    plan_warnings = list(plan.plan_warnings)
    missing_messages = summarize_missing_required_dependencies(dependency_findings)
    if missing_messages:
        plan_warnings.append(
            f"Dependency preflight found {len(missing_messages)} missing required dependency relation(s)."
        )
        for message in missing_messages:
            plan_warnings.append(f"Dependency: {message}")

    optional_missing_count = sum(
        1 for finding in dependency_findings if finding.state == OPTIONAL_DEPENDENCY_MISSING
    )
    if optional_missing_count:
        plan_warnings.append(
            f"Dependency preflight found {optional_missing_count} optional missing dependency relation(s)."
        )

    unresolved_count = sum(
        1 for finding in dependency_findings if finding.state == UNRESOLVED_DEPENDENCY_CONTEXT
    )
    if unresolved_count:
        plan_warnings.append(
            f"Dependency preflight found {unresolved_count} unresolved dependency relation(s)."
        )

    return replace(
        plan,
        entries=tuple(updated_entries),
        plan_warnings=tuple(plan_warnings),
        dependency_findings=dependency_findings,
    )


def _normalize_sandbox_profile_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise AppShellError("Sandbox profile name is required.")
    return normalized


def _normalized_sandbox_profile_folder_name(folder_name: str) -> str:
    normalized = folder_name.strip()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if not normalized:
        raise AppShellError("Sandbox profile entry must resolve to a non-empty folder name.")
    return normalized


def _normalize_sandbox_mod_profile_catalog(
    catalog: SandboxModProfileCatalog,
) -> SandboxModProfileCatalog:
    default_profile = SandboxModProfile(
        profile_id=DEFAULT_SANDBOX_PROFILE_ID,
        name=DEFAULT_SANDBOX_PROFILE_NAME,
        is_default=True,
    )
    profiles_by_id: dict[str, SandboxModProfile] = {}
    for profile in catalog.profiles:
        profiles_by_id[profile.profile_id] = profile
    profiles_by_id.setdefault(DEFAULT_SANDBOX_PROFILE_ID, default_profile)
    profiles = tuple(
        sorted(
            profiles_by_id.values(),
            key=lambda item: (0 if item.is_default else 1, item.name.casefold(), item.profile_id),
        )
    )
    active_profile_id = catalog.active_profile_id or DEFAULT_SANDBOX_PROFILE_ID
    if active_profile_id not in {profile.profile_id for profile in profiles}:
        active_profile_id = DEFAULT_SANDBOX_PROFILE_ID
    return SandboxModProfileCatalog(
        profiles=profiles,
        active_profile_id=active_profile_id,
    )


def _normalize_real_mod_profile_catalog(
    catalog: SandboxModProfileCatalog,
) -> SandboxModProfileCatalog:
    default_profile = SandboxModProfile(
        profile_id=DEFAULT_REAL_PROFILE_ID,
        name=DEFAULT_REAL_PROFILE_NAME,
        is_default=True,
    )
    profiles_by_id: dict[str, SandboxModProfile] = {}
    for profile in catalog.profiles:
        profiles_by_id[profile.profile_id] = profile
    profiles_by_id.setdefault(DEFAULT_REAL_PROFILE_ID, default_profile)
    profiles = tuple(
        sorted(
            profiles_by_id.values(),
            key=lambda item: (0 if item.is_default else 1, item.name.casefold(), item.profile_id),
        )
    )
    active_profile_id = catalog.active_profile_id or DEFAULT_REAL_PROFILE_ID
    if active_profile_id not in {profile.profile_id for profile in profiles}:
        active_profile_id = DEFAULT_REAL_PROFILE_ID
    return SandboxModProfileCatalog(
        profiles=profiles,
        active_profile_id=active_profile_id,
    )


def _path_lookup_key(path: Path) -> str:
    key = str(Path(os.path.abspath(os.path.normpath(str(path.expanduser())))))
    if os.name == "nt":
        return key.casefold()
    return key


def _merge_profile_scan_entry_findings(*inventories: ModsInventory) -> tuple:
    merged = []
    seen: set[tuple[str, str, tuple[str, ...], str]] = set()
    for inventory in inventories:
        for finding in inventory.scan_entry_findings:
            key = (
                finding.kind,
                _path_lookup_key(finding.entry_path),
                tuple(_path_lookup_key(path) for path in finding.mod_paths),
                finding.message,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(finding)
    return tuple(
        sorted(
            merged,
            key=lambda finding: (
                finding.kind,
                _path_lookup_key(finding.entry_path),
                tuple(_path_lookup_key(path) for path in finding.mod_paths),
            ),
        )
    )


def _build_profile_entry_state_maps(
    *,
    inventory: ModsInventory,
    root: Path,
) -> tuple[dict[str, _ProfileEntryState], dict[str, _ProfileEntryState]]:
    expected_root_key = _path_lookup_key(root)
    row_by_path: dict[str, tuple[InstalledMod, bool]] = {}
    for mod, enabled in (
        *((mod, True) for mod in inventory.mods),
        *((mod, False) for mod in inventory.disabled_mods),
    ):
        row_by_path[_path_lookup_key(mod.folder_path)] = (mod, enabled)

    state_by_folder: dict[str, _ProfileEntryState] = {}
    state_by_mod_path: dict[str, _ProfileEntryState] = {}
    consumed_mod_paths: set[str] = set()

    def add_state(
        *,
        folder_name: str,
        entry_path: Path,
        enabled: bool,
        mods: tuple[InstalledMod, ...],
    ) -> None:
        entry_key = folder_name.casefold()
        existing = state_by_folder.get(entry_key)
        normalized_entry_path = Path(os.path.abspath(os.path.normpath(str(entry_path.expanduser()))))
        if existing is not None and _path_lookup_key(existing.entry_path) != _path_lookup_key(
            normalized_entry_path
        ):
            raise AppShellError(
                "Profile entry state is ambiguous because multiple top-level entries map to "
                f"{folder_name}."
            )
        state = _ProfileEntryState(
            folder_name=folder_name,
            entry_path=normalized_entry_path,
            enabled=enabled,
            mods=mods,
        )
        state_by_folder[entry_key] = state
        for mod in mods:
            state_by_mod_path[_path_lookup_key(mod.folder_path)] = state

    for finding in inventory.scan_entry_findings:
        if finding.kind not in {DIRECT_MOD, NESTED_MOD_CONTAINER, MULTI_MOD_CONTAINER}:
            continue
        entry_path = Path(os.path.abspath(os.path.normpath(str(finding.entry_path.expanduser()))))
        if _path_lookup_key(entry_path.parent) != expected_root_key:
            continue
        matched_rows: list[tuple[InstalledMod, bool]] = []
        for mod_path in finding.mod_paths:
            row = row_by_path.get(_path_lookup_key(mod_path))
            if row is None:
                continue
            matched_rows.append(row)
        if not matched_rows:
            continue
        mods = tuple(mod for mod, _ in matched_rows)
        enabled = any(flag for _, flag in matched_rows)
        add_state(
            folder_name=_normalized_sandbox_profile_folder_name(entry_path.name),
            entry_path=entry_path,
            enabled=enabled,
            mods=mods,
        )
        consumed_mod_paths.update(_path_lookup_key(mod.folder_path) for mod, _ in matched_rows)

    for mod, enabled in (
        *((mod, True) for mod in inventory.mods),
        *((mod, False) for mod in inventory.disabled_mods),
    ):
        mod_key = _path_lookup_key(mod.folder_path)
        if mod_key in consumed_mod_paths:
            continue
        if _path_lookup_key(mod.folder_path.parent) != expected_root_key:
            continue
        add_state(
            folder_name=_normalized_sandbox_profile_folder_name(mod.folder_path.name),
            entry_path=mod.folder_path,
            enabled=enabled,
            mods=(mod,),
        )

    return state_by_folder, state_by_mod_path


def _profile_entry_state_for_mod(
    *,
    inventory: ModsInventory,
    root: Path,
    mod_folder_path: Path,
) -> _ProfileEntryState | None:
    _, state_by_mod_path = _build_profile_entry_state_maps(
        inventory=inventory,
        root=root,
    )
    return state_by_mod_path.get(_path_lookup_key(mod_folder_path))


def _upsert_sandbox_mod_profile(
    existing_profiles: tuple[SandboxModProfile, ...],
    profile: SandboxModProfile,
) -> tuple[SandboxModProfile, ...]:
    retained = tuple(
        existing
        for existing in existing_profiles
        if existing.profile_id != profile.profile_id
        and existing.name.casefold() != profile.name.casefold()
    )
    ordered = (*retained, profile)
    return tuple(
        sorted(
            ordered,
            key=lambda item: (0 if item.is_default else 1, item.name.casefold(), item.profile_id),
        )
    )


def _create_directory_link(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise OSError(detail or f"mklink /J failed for {link_path}")
        return
    os.symlink(target_path, link_path, target_is_directory=True)


def _launch_command_mods_override(command: LaunchCommand) -> Path | None:
    argv = tuple(command.argv)
    for index, value in enumerate(argv[:-1]):
        if value == "--mods-path":
            return Path(argv[index + 1]).expanduser()
    return None


def _remove_directory_link(link_path: Path) -> None:
    if not link_path.exists():
        return
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "rmdir", str(link_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise OSError(detail or f"rmdir failed for {link_path}")
        return
    link_path.unlink()


def _inspect_package_mod_entries(package_path: Path) -> tuple[PackageModEntry, ...]:
    inspection = inspect_zip_package(package_path)
    return inspection.mods
