from __future__ import annotations

import errno
from dataclasses import replace
from pathlib import Path, PurePosixPath
import shutil
import uuid
import zipfile

from sdvmm.domain.install_codes import BLOCKED, INSTALL_NEW, OVERWRITE_WITH_ARCHIVE
from sdvmm.domain.models import (
    PackageInspectionResult,
    SandboxInstallPlan,
    SandboxInstallPlanEntry,
    SandboxInstallResult,
)
from sdvmm.services.mod_scanner import scan_mods_directory
from sdvmm.services.package_inspector import inspect_zip_package

_CONFIG_ARTIFACT_NAMES = ("config.json", "config", "configs")


class SandboxInstallError(ValueError):
    """Raised when plan creation or install execution cannot proceed safely."""


class SandboxFileLockError(SandboxInstallError):
    """Raised when Windows is likely still holding a handle inside the target folder."""

    def __init__(self, message: str, *, technical_detail: str) -> None:
        super().__init__(message)
        self.technical_detail = technical_detail


_LOCK_ERRNOS = {errno.EACCES, errno.EPERM}
_LOCK_WINERRORS = {5, 32, 33}


def build_sandbox_install_plan(
    package_path: Path,
    sandbox_mods_path: Path,
    sandbox_archive_path: Path,
    *,
    allow_overwrite: bool,
) -> SandboxInstallPlan:
    inspection = inspect_zip_package(package_path)

    entries: list[SandboxInstallPlanEntry] = []
    overwrite_entries_with_preserved_config = 0

    for mod in inspection.mods:
        source_root = str(PurePosixPath(mod.manifest_path).parent)
        if source_root == "":
            source_root = "."

        target_folder_name = _derive_target_folder_name(source_root, mod.unique_id, mod.name)
        target_path = sandbox_mods_path / target_folder_name

        warnings: list[str] = []
        can_install = True
        action = INSTALL_NEW
        archive_path: Path | None = None

        if source_root == ".":
            warnings.append(
                "Manifest is at package root; install extracts package root files into one target folder."
            )
            if len(inspection.mods) > 1:
                warnings.append(
                    "Package-root manifest with multiple detected mods is unsupported for sandbox install."
                )
                can_install = False

        target_exists = target_path.exists()
        if target_exists:
            if allow_overwrite and can_install:
                action = OVERWRITE_WITH_ARCHIVE
                archive_path = _build_archive_destination(
                    archive_root=sandbox_archive_path,
                    target_folder_name=target_path.name,
                )
                warnings.append(
                    f"Target folder already exists and will be archived to '{archive_path.name}' before overwrite."
                )
                preserved_artifact_names = _config_artifact_names(target_path)
                if preserved_artifact_names:
                    overwrite_entries_with_preserved_config += 1
                    warnings.append(
                        "Existing config artifacts will be preserved during replace: "
                        f"{', '.join(preserved_artifact_names)}."
                    )
            else:
                warnings.append("Target folder already exists. Overwrite is disabled for this plan.")
                can_install = False

        if not can_install:
            action = BLOCKED
            archive_path = None

        entries.append(
            SandboxInstallPlanEntry(
                name=mod.name,
                unique_id=mod.unique_id,
                version=mod.version,
                source_package_path=package_path,
                source_manifest_path=mod.manifest_path,
                source_root_path=source_root,
                target_path=target_path,
                action=action,
                target_exists=target_exists,
                archive_path=archive_path,
                can_install=can_install,
                warnings=tuple(warnings),
            )
        )

    entries = _mark_duplicate_targets(entries)
    entries.sort(key=lambda item: (item.target_path.name.lower(), item.unique_id.casefold()))

    plan_warnings = _build_plan_warnings(entries, inspection, allow_overwrite=allow_overwrite)
    if overwrite_entries_with_preserved_config > 0:
        target_label = "target" if overwrite_entries_with_preserved_config == 1 else "targets"
        plan_warnings.append(
            "Config preservation is enabled for "
            f"{overwrite_entries_with_preserved_config} overwrite {target_label}; "
            "existing config artifacts will be copied back after replacement."
        )

    return SandboxInstallPlan(
        package_path=package_path,
        sandbox_mods_path=sandbox_mods_path,
        sandbox_archive_path=sandbox_archive_path,
        entries=tuple(entries),
        package_findings=inspection.findings,
        package_warnings=inspection.warnings,
        plan_warnings=tuple(plan_warnings),
        dependency_findings=inspection.dependency_findings,
        package_paths=(package_path,),
    )


def execute_sandbox_install_plan(plan: SandboxInstallPlan) -> SandboxInstallResult:
    if not plan.sandbox_mods_path.exists() or not plan.sandbox_mods_path.is_dir():
        raise SandboxInstallError(f"Sandbox Mods directory is not accessible: {plan.sandbox_mods_path}")

    _ensure_archive_root(plan.sandbox_archive_path)

    installable_entries = [entry for entry in plan.entries if entry.can_install]
    blocked_entries = [entry for entry in plan.entries if not entry.can_install]

    if not installable_entries:
        raise SandboxInstallError("No installable entries in plan. Resolve preflight warnings first.")

    if blocked_entries:
        names = ", ".join(entry.target_path.name for entry in blocked_entries)
        raise SandboxInstallError(
            "Plan has blocked entries and cannot execute conservatively; "
            f"resolve conflicts first: {names}"
        )

    staging_root = plan.sandbox_mods_path / f".sdvmm-stage-{uuid.uuid4().hex[:10]}"
    installed_targets: list[Path] = []
    archived_targets: list[Path] = []

    try:
        staging_root.mkdir(parents=False, exist_ok=False)

        installable_entries_by_package: dict[Path, list[SandboxInstallPlanEntry]] = {}
        package_order: list[Path] = []
        for entry in installable_entries:
            source_package_path = entry.source_package_path
            if source_package_path not in installable_entries_by_package:
                installable_entries_by_package[source_package_path] = []
                package_order.append(source_package_path)
            installable_entries_by_package[source_package_path].append(entry)

        for package_path in package_order:
            with zipfile.ZipFile(package_path, "r") as archive:
                for entry in installable_entries_by_package[package_path]:
                    staged_target = staging_root / entry.target_path.name
                    staged_target.mkdir(parents=True, exist_ok=False)
                    _extract_mod_root(
                        archive=archive,
                        source_root=entry.source_root_path,
                        destination=staged_target,
                    )

        for entry in installable_entries:
            staged_target = staging_root / entry.target_path.name
            if entry.action == INSTALL_NEW:
                _install_new_target(staged_target=staged_target, target_path=entry.target_path)
                installed_targets.append(entry.target_path)
                continue

            if entry.action == OVERWRITE_WITH_ARCHIVE:
                if entry.archive_path is None:
                    raise SandboxInstallError(
                        f"Overwrite entry missing archive path for target: {entry.target_path}"
                    )

                _overwrite_target_with_archive(
                    staged_target=staged_target,
                    target_path=entry.target_path,
                    archive_path=entry.archive_path,
                )
                installed_targets.append(entry.target_path)
                archived_targets.append(entry.archive_path)
                continue

            raise SandboxInstallError(
                f"Blocked entry cannot be executed: {entry.target_path}"
            )

    except Exception as exc:
        if isinstance(exc, SandboxInstallError):
            raise
        raise SandboxInstallError(f"Sandbox install failed: {exc}") from exc
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)

    inventory = scan_mods_directory(
        plan.sandbox_mods_path,
        excluded_paths=(plan.sandbox_archive_path, plan.sandbox_mods_path / ".sdvmm-archive"),
    )
    return SandboxInstallResult(
        plan=plan,
        installed_targets=tuple(sorted(installed_targets, key=lambda path: path.name.lower())),
        archived_targets=tuple(sorted(archived_targets, key=lambda path: path.name.lower())),
        scan_context_path=plan.sandbox_mods_path,
        inventory=inventory,
        destination_kind=plan.destination_kind,
    )


def remove_mod_to_archive(
    *,
    target_mod_path: Path,
    mods_root: Path,
    archive_root: Path,
) -> Path:
    mods_root_resolved = mods_root.resolve()
    target_mod_resolved = target_mod_path.resolve()

    if not mods_root.exists() or not mods_root.is_dir():
        raise SandboxInstallError(f"Mods directory is not accessible: {mods_root}")

    if not target_mod_path.exists() or not target_mod_path.is_dir():
        raise SandboxInstallError(f"Selected mod folder is not accessible: {target_mod_path}")

    if target_mod_resolved.parent != mods_root_resolved:
        raise SandboxInstallError(
            "Selected mod folder must be a direct child of the selected Mods destination."
        )

    _ensure_archive_root(archive_root)
    archive_path = _build_archive_destination(
        archive_root=archive_root,
        target_folder_name=target_mod_path.name,
    )
    try:
        _move_path(target_mod_path, archive_path)
    except Exception as exc:
        detail = f"Could not move mod folder to archive: {target_mod_path} -> {archive_path}: {exc}"
        if _is_likely_windows_lock_error(exc):
            raise SandboxFileLockError(
                _sandbox_file_lock_message(),
                technical_detail=detail,
            ) from exc
        raise SandboxInstallError(
            detail
        ) from exc

    return archive_path


def _mark_duplicate_targets(entries: list[SandboxInstallPlanEntry]) -> list[SandboxInstallPlanEntry]:
    buckets: dict[str, list[SandboxInstallPlanEntry]] = {}
    for entry in entries:
        key = entry.target_path.name.casefold()
        buckets.setdefault(key, []).append(entry)

    updated: list[SandboxInstallPlanEntry] = []
    for entry in entries:
        grouped = buckets[entry.target_path.name.casefold()]
        if len(grouped) < 2:
            updated.append(entry)
            continue

        warnings = list(entry.warnings)
        warnings.append("Multiple package mods map to the same target folder.")
        updated.append(
            replace(
                entry,
                action=BLOCKED,
                archive_path=None,
                can_install=False,
                warnings=tuple(warnings),
            )
        )

    return updated


def _build_plan_warnings(
    entries: list[SandboxInstallPlanEntry],
    inspection: PackageInspectionResult,
    *,
    allow_overwrite: bool,
) -> list[str]:
    warnings: list[str] = []

    if not inspection.mods:
        warnings.append("Package inspection found no installable mods.")

    has_existing_targets = any(entry.target_exists for entry in entries)
    has_overwrite_entries = any(entry.action == OVERWRITE_WITH_ARCHIVE for entry in entries)

    if has_existing_targets and not allow_overwrite:
        warnings.append(
            "One or more target folders already exist. Enable overwrite mode and rebuild plan to replace them."
        )

    if has_overwrite_entries:
        warnings.append(
            "Overwrite mode will archive existing target folders before replacement. "
            "Recovery is best-effort per entry and not a full transaction."
        )
        warnings.append(
            "Overwrite updates preserve existing config artifacts by default when present."
        )

    if any(not entry.can_install for entry in entries):
        warnings.append("Plan has blocked entries; execution requires all entries to be installable.")

    return warnings


def _derive_target_folder_name(source_root: str, unique_id: str, name: str) -> str:
    root_path = PurePosixPath(source_root)
    if source_root != "." and root_path.name:
        return root_path.name

    base = _sanitize_name(unique_id) or _sanitize_name(name)
    return base or "installed_mod"


def _sanitize_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("._")


def _build_archive_destination(archive_root: Path, target_folder_name: str) -> Path:
    for idx in range(1, 10_000):
        candidate = archive_root / f"{target_folder_name}__sdvmm_archive_{idx:03d}"
        if not candidate.exists():
            return candidate

    raise SandboxInstallError(
        f"Could not allocate archive path for target '{target_folder_name}' under {archive_root}."
    )


def _ensure_archive_root(archive_root: Path) -> None:
    if archive_root.exists() and not archive_root.is_dir():
        raise SandboxInstallError(f"Sandbox archive path is not a directory: {archive_root}")

    archive_root.mkdir(parents=True, exist_ok=True)


def _install_new_target(staged_target: Path, target_path: Path) -> None:
    if target_path.exists():
        raise SandboxInstallError(
            f"Install plan is stale: target already exists, rebuild plan first: {target_path}"
        )

    _move_path(staged_target, target_path)


def _overwrite_target_with_archive(staged_target: Path, target_path: Path, archive_path: Path) -> None:
    if not target_path.exists() or not target_path.is_dir():
        raise SandboxInstallError(
            f"Install plan is stale: overwrite target is not an existing directory: {target_path}"
        )

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        raise SandboxInstallError(f"Archive path already exists; rebuild plan first: {archive_path}")

    try:
        _move_path(target_path, archive_path)
    except Exception as exc:
        detail = (
            f"Could not archive existing target before overwrite: "
            f"{target_path} -> {archive_path}: {exc}"
        )
        if _is_likely_windows_lock_error(exc):
            raise SandboxFileLockError(
                _sandbox_file_lock_message(),
                technical_detail=detail,
            ) from exc
        raise SandboxInstallError(
            detail
        ) from exc

    try:
        _move_path(staged_target, target_path)
        _restore_preserved_config_artifacts(archived_target=archive_path, target_path=target_path)
    except Exception as replace_exc:
        cleanup_errors: list[str] = []

        if target_path.exists():
            try:
                _remove_path(target_path)
            except Exception as cleanup_exc:
                cleanup_errors.append(f"cleanup failed: {cleanup_exc}")

        recovered = False
        try:
            _move_path(archive_path, target_path)
            recovered = True
        except Exception as restore_exc:
            cleanup_errors.append(f"restore failed: {restore_exc}")

        details = ""
        if cleanup_errors:
            details = " Details: " + "; ".join(cleanup_errors)

        if recovered:
            raise SandboxInstallError(
                "Replacement failed after archive. Best-effort recovery restored original target. "
                f"Replace error: {replace_exc}.{details}"
            ) from replace_exc

        raise SandboxInstallError(
            "Replacement failed after archive and best-effort recovery could not restore original target. "
            f"Replace error: {replace_exc}.{details}"
        ) from replace_exc


def _config_artifact_names(mod_root: Path) -> tuple[str, ...]:
    return tuple(path.name for path in _iter_config_artifacts(mod_root))


def _iter_config_artifacts(mod_root: Path) -> tuple[Path, ...]:
    artifacts: list[Path] = []
    for candidate_name in _CONFIG_ARTIFACT_NAMES:
        candidate_path = mod_root / candidate_name
        if not candidate_path.exists():
            continue
        if candidate_path.is_file() or candidate_path.is_dir():
            artifacts.append(candidate_path)
    return tuple(artifacts)


def _restore_preserved_config_artifacts(*, archived_target: Path, target_path: Path) -> None:
    for artifact in _iter_config_artifacts(archived_target):
        relative_path = artifact.relative_to(archived_target)
        destination_path = target_path / relative_path
        if artifact.is_file():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            if destination_path.exists() and destination_path.is_dir():
                _remove_path(destination_path)
            shutil.copy2(artifact, destination_path)
            continue

        if destination_path.exists() and destination_path.is_file():
            _remove_path(destination_path)
        destination_path.mkdir(parents=True, exist_ok=True)
        for source_file in artifact.rglob("*"):
            if not source_file.is_file():
                continue
            nested_relative_path = source_file.relative_to(artifact)
            nested_destination_path = destination_path / nested_relative_path
            nested_destination_path.parent.mkdir(parents=True, exist_ok=True)
            if nested_destination_path.exists() and nested_destination_path.is_dir():
                _remove_path(nested_destination_path)
            shutil.copy2(source_file, nested_destination_path)


def _move_path(source: Path, destination: Path) -> None:
    source.rename(destination)


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return

    path.unlink(missing_ok=True)


def _extract_mod_root(archive: zipfile.ZipFile, source_root: str, destination: Path) -> None:
    root = PurePosixPath(source_root)
    destination_resolved = destination.resolve()
    extracted_any = False

    for info in sorted(archive.infolist(), key=lambda item: item.filename.lower()):
        normalized = _normalize_zip_member(info.filename)
        if normalized is None:
            continue

        relative = _relative_to_source_root(normalized, root)
        if relative is None or relative == PurePosixPath("."):
            continue

        target_path = destination.joinpath(*relative.parts)
        target_resolved = target_path.resolve()
        if not target_resolved.is_relative_to(destination_resolved):
            raise SandboxInstallError(f"Unsafe zip entry path: {info.filename}")

        if info.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as src, target_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        extracted_any = True

    if not extracted_any or not (destination / "manifest.json").exists():
        raise SandboxInstallError(
            f"No usable files extracted for source root '{source_root}'."
        )


def _normalize_zip_member(filename: str) -> PurePosixPath | None:
    normalized = filename.replace("\\", "/").lstrip("/")
    if not normalized:
        return None

    path = PurePosixPath(normalized)
    if any(part == ".." for part in path.parts):
        raise SandboxInstallError(f"Unsafe zip entry path: {filename}")

    return path


def _relative_to_source_root(path: PurePosixPath, source_root: PurePosixPath) -> PurePosixPath | None:
    if str(source_root) == ".":
        return path

    path_parts = path.parts
    root_parts = source_root.parts

    if len(path_parts) < len(root_parts):
        return None

    if tuple(part.casefold() for part in path_parts[: len(root_parts)]) != tuple(
        part.casefold() for part in root_parts
    ):
        return None

    tail = path_parts[len(root_parts) :]
    if not tail:
        return PurePosixPath(".")

    return PurePosixPath(*tail)


def _is_likely_windows_lock_error(exc: BaseException) -> bool:
    queue: list[BaseException] = [exc]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))

        if isinstance(current, PermissionError):
            return True

        if isinstance(current, OSError):
            if current.errno in _LOCK_ERRNOS:
                return True
            if getattr(current, "winerror", None) in _LOCK_WINERRORS:
                return True
            lowered = str(current).casefold()
            if (
                "being used by another process" in lowered
                or "access is denied" in lowered
                or "permission denied" in lowered
            ):
                return True

        cause = getattr(current, "__cause__", None)
        if isinstance(cause, BaseException):
            queue.append(cause)
        context = getattr(current, "__context__", None)
        if isinstance(context, BaseException):
            queue.append(context)

    return False


def _sandbox_file_lock_message() -> str:
    return (
        "Sandbox write failed because Windows is still using files in the target mod folder. "
        "Close Explorer windows or preview panes for that folder, any editor or terminal using the mod, "
        "and the sandbox game or SMAPI if it is still running, then try again."
    )
