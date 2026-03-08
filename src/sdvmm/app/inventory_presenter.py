from __future__ import annotations

from sdvmm.domain.models import (
    ModUpdateReport,
    ModsInventory,
    PackageInspectionResult,
    SandboxInstallPlan,
    SandboxInstallResult,
)


def build_findings_text(inventory: ModsInventory) -> str:
    lines: list[str] = []

    if inventory.scan_entry_findings:
        lines.append("Scan entry findings:")
        for finding in inventory.scan_entry_findings:
            kind = finding.kind.replace("_", " ")
            lines.append(f"- [{kind}] {finding.entry_path.name}: {finding.message}")
    else:
        lines.append("Scan entry findings: none")

    lines.append("")

    if inventory.parse_warnings:
        lines.append("Warnings:")
        for warning in inventory.parse_warnings:
            lines.append(
                f"- [{warning.code}] {warning.mod_path.name}: {warning.message}"
            )
    else:
        lines.append("Warnings: none")

    if inventory.duplicate_unique_ids:
        lines.append("")
        lines.append("Duplicate UniqueID findings:")
        for finding in inventory.duplicate_unique_ids:
            folders = ", ".join(path.name for path in finding.folder_paths)
            lines.append(f"- {finding.unique_id} ({folders})")
    else:
        lines.append("")
        lines.append("Duplicate UniqueID findings: none")

    if inventory.missing_required_dependencies:
        lines.append("")
        lines.append("Missing required dependencies:")
        for finding in inventory.missing_required_dependencies:
            lines.append(
                "- "
                f"{finding.required_by_unique_id} requires {finding.missing_unique_id}"
                f" (folder: {finding.required_by_folder.name})"
            )
    else:
        lines.append("")
        lines.append("Missing required dependencies: none")

    return "\n".join(lines)


def build_package_inspection_text(result: PackageInspectionResult) -> str:
    lines: list[str] = []
    lines.append(f"Package: {result.package_path.name}")

    lines.append("")
    if result.mods:
        lines.append("Detected package mods:")
        for mod in result.mods:
            lines.append(
                f"- {mod.name} | {mod.unique_id} | {mod.version} | {mod.manifest_path}"
            )
    else:
        lines.append("Detected package mods: none")

    lines.append("")
    if result.findings:
        lines.append("Package findings:")
        for finding in result.findings:
            kind = finding.kind.replace("_", " ")
            lines.append(f"- [{kind}] {finding.message}")
    else:
        lines.append("Package findings: none")

    lines.append("")
    if result.warnings:
        lines.append("Package warnings:")
        for warning in result.warnings:
            lines.append(f"- [{warning.code}] {warning.manifest_path}: {warning.message}")
    else:
        lines.append("Package warnings: none")

    return "\n".join(lines)


def build_sandbox_install_plan_text(plan: SandboxInstallPlan) -> str:
    lines: list[str] = []
    lines.append(f"Sandbox target: {plan.sandbox_mods_path}")
    lines.append(f"Sandbox archive: {plan.sandbox_archive_path}")
    lines.append(f"Package: {plan.package_path.name}")
    lines.append("")

    if plan.entries:
        lines.append("Install plan entries:")
        for entry in plan.entries:
            status = "new" if not entry.target_exists else "exists"
            action = entry.action.replace("_", " ")
            executable = "installable" if entry.can_install else "blocked"
            lines.append(
                "- "
                f"{entry.name} | {entry.unique_id} | {entry.version}"
                f" -> {entry.target_path.name} ({status}, {action}, {executable})"
            )
            if entry.archive_path is not None:
                lines.append(f"  archive: {entry.archive_path}")
            for warning in entry.warnings:
                lines.append(f"  warning: {warning}")
    else:
        lines.append("Install plan entries: none")

    lines.append("")
    if plan.plan_warnings:
        lines.append("Plan warnings:")
        for warning in plan.plan_warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("Plan warnings: none")

    lines.append("")
    if plan.package_findings:
        lines.append("Package findings:")
        for finding in plan.package_findings:
            lines.append(f"- [{finding.kind}] {finding.message}")
    else:
        lines.append("Package findings: none")

    return "\n".join(lines)


def build_sandbox_install_result_text(result: SandboxInstallResult) -> str:
    lines: list[str] = []
    lines.append("Sandbox install completed.")
    lines.append(f"Scan context: {result.scan_context_path}")
    lines.append(f"Installed targets: {len(result.installed_targets)}")

    for target in result.installed_targets:
        lines.append(f"- {target}")

    lines.append("")
    lines.append(f"Archived targets: {len(result.archived_targets)}")
    for target in result.archived_targets:
        lines.append(f"- {target}")

    lines.append("")
    lines.append(build_findings_text(result.inventory))
    return "\n".join(lines)


def build_update_report_text(report: ModUpdateReport) -> str:
    lines: list[str] = []
    lines.append("Mod metadata/update status:")

    if not report.statuses:
        lines.append("- No installed mods in current inventory.")
        return "\n".join(lines)

    for status in report.statuses:
        remote_version = status.remote_version or "unknown"
        lines.append(
            "- "
            f"{status.name} | {status.unique_id} | "
            f"installed={status.installed_version} | remote={remote_version} | state={status.state}"
        )
        if status.remote_link is not None:
            lines.append(f"  remote: {status.remote_link.page_url}")
        if status.message:
            lines.append(f"  note: {status.message}")

    return "\n".join(lines)
