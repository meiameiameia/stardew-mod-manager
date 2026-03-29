from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from sdvmm.domain.models import SmapiLogFinding, SmapiLogReport, SmapiMissingDependency
from sdvmm.domain.smapi_log_codes import (
    SMAPI_LOG_ERROR,
    SMAPI_LOG_FAILED_MOD,
    SMAPI_LOG_MISSING_DEPENDENCY,
    SMAPI_LOG_NOT_FOUND,
    SMAPI_LOG_PARSED,
    SMAPI_LOG_RUNTIME_ISSUE,
    SMAPI_LOG_SOURCE_AUTO_DETECTED,
    SMAPI_LOG_SOURCE_MANUAL,
    SMAPI_LOG_SOURCE_NONE,
    SMAPI_LOG_UNABLE_TO_DETERMINE,
    SMAPI_LOG_WARNING,
)

_EXPECTED_LOG_FILENAMES = (
    "SMAPI-latest.txt",
    "SMAPI-crash.txt",
    "SMAPI-crash.previous.txt",
)
_MISSING_DEPENDENCY_PATTERNS = (
    "because it needs",
    "missing dependencies",
    "requires mods which aren't installed",
    "requires these mods",
    "which aren't installed",
)
_RUNTIME_ISSUE_PATTERNS = (
    "unhandled exception",
    "nullreferenceexception",
    "typeloadexception",
    "missingmethodexception",
    "could not load file or assembly",
    "steamapi_init() failed",
    "failed to initialize",
    "game has crashed",
)
_SKIPPED_MOD_BULLET_RE = re.compile(
    r"^\s*(?:\[SMAPI\]\s*)?-\s*(?P<name>.+?)\s+because(?P<reason>.*)$",
    re.IGNORECASE,
)
_FAILED_TO_LOAD_RE = re.compile(
    r"^\s*(?:\[SMAPI\]\s*)?(?P<name>.+?)\s+failed to load\b(?P<reason>.*)$",
    re.IGNORECASE,
)
_DEPENDENCY_ID_RE = re.compile(r"\b(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+\b")
_TRAILING_PARENS_RE = re.compile(r"\((?P<content>[^()]+)\)\s*$")
_MISSING_DEPENDENCY_INLINE_RE = re.compile(
    r"\b(?:needs|requires)\s+(?P<content>.+?),\s+which\s+(?:isn't|aren't)\s+installed\b",
    re.IGNORECASE,
)
_MISSING_DEPENDENCY_COLON_RE = re.compile(
    r"\b(?:missing dependencies|requires these mods)\b\s*:?\s*(?P<content>.+)$",
    re.IGNORECASE,
)
_MOD_IDENTITY_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<unique_id>(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)\)$"
)
_VERSION_ONLY_RE = re.compile(
    r"^v?\d+(?:\.\d+)+(?:\s+(?:or\s+(?:later|newer)|or\s+above|beta|alpha|preview|rc\d*))?$",
    re.IGNORECASE,
)
_MAX_FINDINGS_PER_KIND = 120


def check_smapi_log_troubleshooting(
    *,
    game_path: Path | None,
    manual_log_path: Path | None = None,
) -> SmapiLogReport:
    if manual_log_path is not None:
        return parse_smapi_log_file(
            manual_log_path,
            source=SMAPI_LOG_SOURCE_MANUAL,
            game_path=game_path,
        )

    auto_path = locate_smapi_log(game_path=game_path)
    if auto_path is None:
        return SmapiLogReport(
            state=SMAPI_LOG_NOT_FOUND,
            source=SMAPI_LOG_SOURCE_NONE,
            log_path=None,
            game_path=game_path,
            findings=tuple(),
            notes=(
                "No SMAPI log was found in supported default locations.",
                "Use 'Load SMAPI log' to inspect a specific file manually.",
            ),
            message="SMAPI log not found.",
        )

    return parse_smapi_log_file(
        auto_path,
        source=SMAPI_LOG_SOURCE_AUTO_DETECTED,
        game_path=game_path,
    )


def locate_smapi_log(*, game_path: Path | None) -> Path | None:
    directories = _candidate_log_directories(game_path=game_path)
    for directory in directories:
        expected = _find_expected_log(directory)
        if expected is not None:
            return expected

    candidates: list[Path] = []
    for directory in directories:
        if not directory.exists() or not directory.is_dir():
            continue
        for child in directory.iterdir():
            if not child.is_file():
                continue
            name = child.name.casefold()
            if "smapi" not in name or not name.endswith(".txt"):
                continue
            candidates.append(child)

    if not candidates:
        return None

    candidates.sort(
        key=lambda path: (path.stat().st_mtime, path.name.casefold()),
        reverse=True,
    )
    return candidates[0]


def parse_smapi_log_file(
    log_path: Path,
    *,
    source: str,
    game_path: Path | None,
) -> SmapiLogReport:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return SmapiLogReport(
            state=SMAPI_LOG_UNABLE_TO_DETERMINE,
            source=source,
            log_path=log_path,
            game_path=game_path,
            findings=tuple(),
            notes=(f"Could not read SMAPI log file: {exc}",),
            message="SMAPI log could not be read.",
        )

    return parse_smapi_log_text(
        text,
        log_path=log_path,
        source=source,
        game_path=game_path,
    )


def parse_smapi_log_text(
    text: str,
    *,
    log_path: Path | None,
    source: str,
    game_path: Path | None,
) -> SmapiLogReport:
    lines = text.splitlines()
    if not lines:
        return SmapiLogReport(
            state=SMAPI_LOG_UNABLE_TO_DETERMINE,
            source=source,
            log_path=log_path,
            game_path=game_path,
            findings=tuple(),
            notes=("SMAPI log is empty.",),
            message="SMAPI log is empty; unable to determine troubleshooting status.",
        )

    findings: list[SmapiLogFinding] = []
    counts_by_kind: dict[str, int] = {}
    missing_dependencies: list[SmapiMissingDependency] = []
    missing_dependency_ids: set[str] = set()
    seen_missing_dependency_entries: set[tuple[str | None, str | None, str | None, str | None]] = set()
    in_skipped_mods_block = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            in_skipped_mods_block = False
            continue

        lowered = line.casefold()

        if "skipped mods" in lowered:
            in_skipped_mods_block = True

        if "[error" in lowered or "[fatal" in lowered:
            _append_finding(
                findings=findings,
                counts_by_kind=counts_by_kind,
                kind=SMAPI_LOG_ERROR,
                line_number=line_number,
                message=_compact_log_line(line),
            )
        if "[warn" in lowered:
            _append_finding(
                findings=findings,
                counts_by_kind=counts_by_kind,
                kind=SMAPI_LOG_WARNING,
                line_number=line_number,
                message=_compact_log_line(line),
            )

        skipped_mod_match = _SKIPPED_MOD_BULLET_RE.match(line)
        if in_skipped_mods_block and skipped_mod_match is not None:
            mod_name_text = skipped_mod_match.group("name").strip()
            mod_name, mod_unique_id = _extract_mod_identity(mod_name_text)
            reason = skipped_mod_match.group("reason").strip(" :")
            message = f"{mod_name}: {reason}" if reason else mod_name
            _append_finding(
                findings=findings,
                counts_by_kind=counts_by_kind,
                kind=SMAPI_LOG_FAILED_MOD,
                line_number=line_number,
                message=message,
            )
            _append_missing_dependency_from_line(
                findings=findings,
                counts_by_kind=counts_by_kind,
                line_number=line_number,
                line=line,
                requiring_mod_name=mod_name,
                requiring_mod_unique_id=mod_unique_id,
                missing_dependencies=missing_dependencies,
                missing_dependency_ids=missing_dependency_ids,
                seen_entries=seen_missing_dependency_entries,
            )
            continue

        failed_to_load_match = _FAILED_TO_LOAD_RE.match(line)
        requiring_mod_name: str | None = None
        requiring_mod_unique_id: str | None = None
        if failed_to_load_match is not None:
            mod_name_text = failed_to_load_match.group("name").strip()
            mod_name, mod_unique_id = _extract_mod_identity(mod_name_text)
            reason = failed_to_load_match.group("reason").strip(" :")
            message = f"{mod_name}: failed to load"
            if reason:
                message = f"{message} ({reason})"
            _append_finding(
                findings=findings,
                counts_by_kind=counts_by_kind,
                kind=SMAPI_LOG_FAILED_MOD,
                line_number=line_number,
                message=message,
            )
            requiring_mod_name = mod_name
            requiring_mod_unique_id = mod_unique_id

        _append_missing_dependency_from_line(
            findings=findings,
            counts_by_kind=counts_by_kind,
            line_number=line_number,
            line=line,
            requiring_mod_name=requiring_mod_name,
            requiring_mod_unique_id=requiring_mod_unique_id,
            missing_dependencies=missing_dependencies,
            missing_dependency_ids=missing_dependency_ids,
            seen_entries=seen_missing_dependency_entries,
        )

        if any(keyword in lowered for keyword in _RUNTIME_ISSUE_PATTERNS):
            _append_finding(
                findings=findings,
                counts_by_kind=counts_by_kind,
                kind=SMAPI_LOG_RUNTIME_ISSUE,
                line_number=line_number,
                message=_compact_log_line(line),
            )

    notes: list[str] = []
    if not findings:
        notes.append(
            "No clear errors/warnings/issues were parsed from this log. That does not guarantee the run was healthy."
        )

    summary = _build_summary_message(
        findings,
        missing_dependency_count=len(missing_dependencies),
    )
    return SmapiLogReport(
        state=SMAPI_LOG_PARSED,
        source=source,
        log_path=log_path,
        game_path=game_path,
        findings=tuple(findings),
        missing_dependencies=tuple(missing_dependencies),
        missing_dependency_ids=tuple(sorted(missing_dependency_ids, key=str.casefold)),
        notes=tuple(notes),
        message=summary,
    )


def _candidate_log_directories(*, game_path: Path | None) -> tuple[Path, ...]:
    directories: list[Path] = []
    if game_path is not None:
        directories.append(game_path / "ErrorLogs")

    appdata_raw = os.getenv("APPDATA", "").strip()
    if appdata_raw:
        directories.append(Path(appdata_raw).expanduser() / "StardewValley" / "ErrorLogs")

    local_appdata_raw = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata_raw:
        directories.append(Path(local_appdata_raw).expanduser() / "StardewValley" / "ErrorLogs")

    xdg_config_home_raw = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home_raw:
        directories.append(Path(xdg_config_home_raw).expanduser() / "StardewValley" / "ErrorLogs")

    home_dir = Path.home()
    directories.append(home_dir / ".config" / "StardewValley" / "ErrorLogs")

    deduped: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        key = str(directory.expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(directory)
    return tuple(deduped)


def _find_expected_log(directory: Path) -> Path | None:
    if not directory.exists() or not directory.is_dir():
        return None

    by_name = {child.name.casefold(): child for child in directory.iterdir() if child.is_file()}
    for expected_name in _EXPECTED_LOG_FILENAMES:
        match = by_name.get(expected_name.casefold())
        if match is not None:
            return match
    return None


def _append_missing_dependency_from_line(
    *,
    findings: list[SmapiLogFinding],
    counts_by_kind: dict[str, int],
    line_number: int,
    line: str,
    requiring_mod_name: str | None,
    requiring_mod_unique_id: str | None,
    missing_dependencies: list[SmapiMissingDependency],
    missing_dependency_ids: set[str],
    seen_entries: set[tuple[str | None, str | None, str | None, str | None]],
) -> None:
    lowered = line.casefold()
    if not any(pattern in lowered for pattern in _MISSING_DEPENDENCY_PATTERNS):
        return

    dependency_entries = _extract_missing_dependencies_from_line(
        line,
        requiring_mod_name=requiring_mod_name,
        requiring_mod_unique_id=requiring_mod_unique_id,
    )
    dependency_targets = tuple(
        entry.dependency_target for entry in dependency_entries if entry.dependency_target
    )
    for entry in dependency_entries:
        dedupe_key = (
            entry.requiring_mod_name,
            entry.requiring_mod_unique_id,
            entry.dependency_target,
            entry.required_version,
        )
        if dedupe_key in seen_entries:
            continue
        seen_entries.add(dedupe_key)
        missing_dependencies.append(entry)
        if entry.dependency_unique_id:
            missing_dependency_ids.add(entry.dependency_unique_id)
    if dependency_targets:
        message = f"{_compact_log_line(line)} | detected targets: {', '.join(dependency_targets)}"
    else:
        message = _compact_log_line(line)
    _append_finding(
        findings=findings,
        counts_by_kind=counts_by_kind,
        kind=SMAPI_LOG_MISSING_DEPENDENCY,
        line_number=line_number,
        message=message,
    )


def _extract_dependency_ids(line: str) -> tuple[str, ...]:
    ids = {
        match.group(0)
        for match in _DEPENDENCY_ID_RE.finditer(line)
    }
    if not ids:
        return tuple()
    return tuple(sorted(ids, key=str.casefold))


def _extract_missing_dependencies_from_line(
    line: str,
    *,
    requiring_mod_name: str | None,
    requiring_mod_unique_id: str | None,
) -> tuple[SmapiMissingDependency, ...]:
    segment = _extract_missing_dependency_segment(line)
    if not segment:
        return tuple()

    entries: list[SmapiMissingDependency] = []
    for raw_item in _split_dependency_items(segment):
        dependency_name, dependency_unique_id, required_version = _parse_dependency_descriptor(raw_item)
        if dependency_name is None and dependency_unique_id is None:
            continue
        entries.append(
            SmapiMissingDependency(
                requiring_mod_name=requiring_mod_name,
                requiring_mod_unique_id=requiring_mod_unique_id,
                dependency_name=dependency_name,
                dependency_unique_id=dependency_unique_id,
                required_version=required_version,
                source_text=_compact_log_line(raw_item),
            )
        )
    return tuple(entries)


def _extract_missing_dependency_segment(line: str) -> str:
    trailing_parens = _TRAILING_PARENS_RE.search(line)
    if trailing_parens is not None:
        content = trailing_parens.group("content").strip()
        if content:
            return content

    inline_match = _MISSING_DEPENDENCY_INLINE_RE.search(line)
    if inline_match is not None:
        return inline_match.group("content").strip(" .:")

    colon_match = _MISSING_DEPENDENCY_COLON_RE.search(line)
    if colon_match is not None:
        return colon_match.group("content").strip(" .:")

    return ""


def _split_dependency_items(text: str) -> tuple[str, ...]:
    parts = [part.strip() for part in text.split(",")]
    return tuple(part for part in parts if part)


def _parse_dependency_descriptor(raw_item: str) -> tuple[str | None, str | None, str | None]:
    text = raw_item.strip().strip("-.;:")
    if not text or _looks_like_version_only(text):
        return None, None, None

    parenthetical_match = _TRAILING_PARENS_RE.search(text)
    if parenthetical_match is not None and parenthetical_match.start() > 0:
        inner = parenthetical_match.group("content").strip()
        prefix = text[: parenthetical_match.start()].strip()
        if _looks_like_version_only(inner):
            dependency_name, dependency_unique_id, _ = _parse_dependency_descriptor(prefix)
            return dependency_name, dependency_unique_id, inner
        dependency_name = prefix or None
        dependency_unique_id = _first_dependency_id(inner)
        if dependency_unique_id:
            if dependency_name and dependency_name.casefold() == dependency_unique_id.casefold():
                dependency_name = None
            return dependency_name, dependency_unique_id, None

    dependency_unique_id = _first_dependency_id(text)
    if dependency_unique_id:
        prefix, _, suffix = text.partition(dependency_unique_id)
        dependency_name = prefix.strip(" -:") or None
        required_version = suffix.strip(" -:()") or None
        if required_version and not _looks_like_version_like_requirement(required_version):
            required_version = None
        if dependency_name and dependency_name.casefold() == dependency_unique_id.casefold():
            dependency_name = None
        return dependency_name, dependency_unique_id, required_version

    return text, None, None


def _first_dependency_id(text: str) -> str | None:
    match = _DEPENDENCY_ID_RE.search(text)
    if match is None:
        return None
    return match.group(0)


def _looks_like_version_only(text: str) -> bool:
    return bool(_VERSION_ONLY_RE.fullmatch(text.strip()))


def _looks_like_version_like_requirement(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    if _looks_like_version_only(normalized):
        return True
    if normalized.casefold().startswith(("v", "version ")):
        return True
    return bool(re.match(r"^\d", normalized))


def _extract_mod_identity(text: str) -> tuple[str, str | None]:
    match = _MOD_IDENTITY_RE.match(text.strip())
    if match is None:
        return text.strip(), None
    return match.group("name").strip(), match.group("unique_id").strip()


def _append_finding(
    *,
    findings: list[SmapiLogFinding],
    counts_by_kind: dict[str, int],
    kind: str,
    line_number: int,
    message: str,
) -> None:
    current_count = counts_by_kind.get(kind, 0)
    if current_count >= _MAX_FINDINGS_PER_KIND:
        return

    counts_by_kind[kind] = current_count + 1
    findings.append(
        SmapiLogFinding(
            kind=kind,
            line_number=line_number,
            message=message,
        )
    )


def _build_summary_message(
    findings: Iterable[SmapiLogFinding],
    *,
    missing_dependency_count: int,
) -> str:
    counts = {
        SMAPI_LOG_ERROR: 0,
        SMAPI_LOG_WARNING: 0,
        SMAPI_LOG_FAILED_MOD: 0,
        SMAPI_LOG_RUNTIME_ISSUE: 0,
    }
    for finding in findings:
        if finding.kind == SMAPI_LOG_MISSING_DEPENDENCY:
            continue
        counts[finding.kind] = counts.get(finding.kind, 0) + 1

    return (
        "Parsed SMAPI log: "
        f"errors={counts[SMAPI_LOG_ERROR]}, "
        f"warnings={counts[SMAPI_LOG_WARNING]}, "
        f"failed_mods={counts[SMAPI_LOG_FAILED_MOD]}, "
        f"missing_dependencies={missing_dependency_count}, "
        f"runtime_issues={counts[SMAPI_LOG_RUNTIME_ISSUE]}."
    )


def _compact_log_line(line: str, *, max_length: int = 280) -> str:
    compact = " ".join(line.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3]}..."
