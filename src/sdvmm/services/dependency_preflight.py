from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from sdvmm.domain.dependency_codes import (
    MISSING_REQUIRED_DEPENDENCY,
    OPTIONAL_DEPENDENCY_MISSING,
    SATISFIED,
    UNRESOLVED_DEPENDENCY_CONTEXT,
)
from sdvmm.domain.models import (
    DependencyContextSource,
    DependencyPreflightFinding,
    InstalledMod,
    ManifestDependency,
    PackageModEntry,
)
from sdvmm.domain.unique_id import canonicalize_unique_id


def evaluate_installed_dependencies(
    installed_mods: tuple[InstalledMod, ...],
) -> tuple[DependencyPreflightFinding, ...]:
    installed_keys = {canonicalize_unique_id(mod.unique_id) for mod in installed_mods}
    findings: list[DependencyPreflightFinding] = []

    for mod in installed_mods:
        findings.extend(
            _evaluate_mod_dependencies(
                source="installed_inventory",
                required_by_unique_id=mod.unique_id,
                required_by_name=mod.name,
                dependencies=mod.dependencies,
                available_dependency_keys=installed_keys,
                has_external_context=True,
            )
        )

    return _sort_findings(findings)


def evaluate_package_dependencies(
    package_mods: tuple[PackageModEntry, ...],
    installed_mods: tuple[InstalledMod, ...] | None,
    *,
    source: Literal["package_inspection", "downloads_intake", "sandbox_plan"],
) -> tuple[DependencyPreflightFinding, ...]:
    package_keys = {canonicalize_unique_id(mod.unique_id) for mod in package_mods}
    available_keys = set(package_keys)
    has_external_context = installed_mods is not None
    if installed_mods is not None:
        available_keys.update(canonicalize_unique_id(mod.unique_id) for mod in installed_mods)

    findings: list[DependencyPreflightFinding] = []
    for mod in package_mods:
        findings.extend(
            _evaluate_mod_dependencies(
                source=source,
                required_by_unique_id=mod.unique_id,
                required_by_name=mod.name,
                dependencies=mod.dependencies,
                available_dependency_keys=available_keys,
                has_external_context=has_external_context,
            )
        )

    return _sort_findings(findings)


def summarize_missing_required_dependencies(
    findings: tuple[DependencyPreflightFinding, ...],
) -> tuple[str, ...]:
    messages: list[str] = []

    for finding in findings:
        if finding.state != MISSING_REQUIRED_DEPENDENCY:
            continue
        messages.append(
            (
                f"{finding.required_by_name} ({finding.required_by_unique_id}) is missing required "
                f"dependency {finding.dependency_unique_id}. Install dependency first."
            )
        )

    return tuple(messages)


def _evaluate_mod_dependencies(
    *,
    source: DependencyContextSource,
    required_by_unique_id: str,
    required_by_name: str,
    dependencies: tuple[ManifestDependency, ...],
    available_dependency_keys: set[str],
    has_external_context: bool,
) -> list[DependencyPreflightFinding]:
    findings: list[DependencyPreflightFinding] = []

    for dependency in dependencies:
        dependency_key = canonicalize_unique_id(dependency.unique_id)
        if dependency_key in available_dependency_keys:
            state = SATISFIED
        elif not has_external_context:
            state = UNRESOLVED_DEPENDENCY_CONTEXT
        elif dependency.required:
            state = MISSING_REQUIRED_DEPENDENCY
        else:
            state = OPTIONAL_DEPENDENCY_MISSING

        findings.append(
            DependencyPreflightFinding(
                source=source,
                state=state,
                required_by_unique_id=required_by_unique_id,
                required_by_name=required_by_name,
                dependency_unique_id=dependency.unique_id,
                required=dependency.required,
            )
        )

    return findings


def _sort_findings(
    findings: Iterable[DependencyPreflightFinding],
) -> tuple[DependencyPreflightFinding, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.source,
                finding.state,
                canonicalize_unique_id(finding.required_by_unique_id),
                canonicalize_unique_id(finding.dependency_unique_id),
            ),
        )
    )

