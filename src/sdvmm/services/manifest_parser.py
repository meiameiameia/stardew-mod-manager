from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

from sdvmm.domain.models import (
    ManifestDependency,
    ManifestParseResult,
    ModManifest,
    ParseWarning,
)
from sdvmm.domain.warning_codes import (
    INVALID_DEPENDENCIES,
    INVALID_DEPENDENCY_ENTRY,
    INVALID_MANIFEST,
    MALFORMED_MANIFEST,
    MANIFEST_READ_ERROR,
    MISSING_MANIFEST,
)


def parse_manifest_for_mod_dir(mod_dir: Path) -> ManifestParseResult:
    manifest_path = mod_dir / "manifest.json"
    return parse_manifest_file(manifest_path=manifest_path, mod_dir=mod_dir)


def parse_manifest_file(manifest_path: Path, mod_dir: Path) -> ManifestParseResult:
    if not manifest_path.exists():
        return ManifestParseResult(
            manifest=None,
            warnings=(
                ParseWarning(
                    code=MISSING_MANIFEST,
                    message="manifest.json not found",
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                ),
            ),
        )

    try:
        # utf-8-sig handles BOM-prefixed manifests used by some real mods.
        raw_text = manifest_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return ManifestParseResult(
            manifest=None,
            warnings=(
                ParseWarning(
                    code=MALFORMED_MANIFEST,
                    message=f"manifest.json is not valid UTF-8 text: {exc}",
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                ),
            ),
        )
    except OSError as exc:
        return ManifestParseResult(
            manifest=None,
            warnings=(
                ParseWarning(
                    code=MANIFEST_READ_ERROR,
                    message=f"Could not read manifest.json: {exc}",
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                ),
            ),
        )

    return parse_manifest_text(raw_text=raw_text, mod_dir=mod_dir, manifest_path=manifest_path)


def parse_manifest_text(raw_text: str, mod_dir: Path, manifest_path: Path) -> ManifestParseResult:
    raw_data, decode_error = _load_manifest_json(raw_text)
    if decode_error is not None:
        return ManifestParseResult(
            manifest=None,
            warnings=(
                ParseWarning(
                    code=MALFORMED_MANIFEST,
                    message=(
                        f"Invalid JSON at line {decode_error.lineno}, "
                        f"column {decode_error.colno}: {decode_error.msg}"
                    ),
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                ),
            ),
        )

    assert raw_data is not None
    if not isinstance(raw_data, dict):
        return _invalid_manifest(
            mod_dir,
            manifest_path,
            f"Manifest root must be a JSON object (got {type(raw_data).__name__})",
        )

    unique_id, _ = _get_manifest_field(raw_data, "UniqueID", "UniqueId")
    if not isinstance(unique_id, str) or not unique_id.strip():
        return _invalid_manifest(
            mod_dir,
            manifest_path,
            f"UniqueID must be a non-empty string (got {_describe_value_type(unique_id)})",
            raw_data,
        )

    name, _ = _get_manifest_field(raw_data, "Name")
    if not isinstance(name, str) or not name.strip():
        return _invalid_manifest(
            mod_dir,
            manifest_path,
            f"Name must be a non-empty string (got {_describe_value_type(name)})",
            raw_data,
        )

    version, _ = _get_manifest_field(raw_data, "Version")
    if not isinstance(version, str) or not version.strip():
        return _invalid_manifest(
            mod_dir,
            manifest_path,
            f"Version must be a non-empty string (got {_describe_value_type(version)})",
            raw_data,
        )

    dependencies, warnings = _parse_dependencies(raw_data.get("Dependencies"), mod_dir, manifest_path)
    update_keys = _parse_update_keys(raw_data.get("UpdateKeys"))

    manifest = ModManifest(
        unique_id=unique_id.strip(),
        name=name.strip(),
        version=version.strip(),
        dependencies=dependencies,
        update_keys=update_keys,
    )

    return ManifestParseResult(manifest=manifest, warnings=tuple(warnings))


def _load_manifest_json(raw_text: str) -> tuple[object | None, JSONDecodeError | None]:
    try:
        return json.loads(raw_text), None
    except JSONDecodeError as strict_error:
        relaxed_text = _normalize_relaxed_json(raw_text)
        if relaxed_text == raw_text:
            return None, strict_error

        try:
            return json.loads(relaxed_text), None
        except JSONDecodeError as relaxed_error:
            return None, relaxed_error


def _normalize_relaxed_json(raw_text: str) -> str:
    without_comments = _strip_json_comments(raw_text)
    without_trailing_commas = _strip_trailing_commas(without_comments)
    return without_trailing_commas


def _strip_json_comments(raw_text: str) -> str:
    out: list[str] = []
    idx = 0
    in_string = False
    escaped = False
    length = len(raw_text)

    while idx < length:
        char = raw_text[idx]
        nxt = raw_text[idx + 1] if idx + 1 < length else ""

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            idx += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            idx += 1
            continue

        if char == "/" and nxt == "/":
            out.extend([" ", " "])
            idx += 2
            while idx < length and raw_text[idx] not in "\r\n":
                out.append(" ")
                idx += 1
            continue

        if char == "/" and nxt == "*":
            out.extend([" ", " "])
            idx += 2
            while idx < length:
                if raw_text[idx] == "*" and idx + 1 < length and raw_text[idx + 1] == "/":
                    out.extend([" ", " "])
                    idx += 2
                    break

                comment_char = raw_text[idx]
                out.append(comment_char if comment_char in "\r\n" else " ")
                idx += 1
            continue

        out.append(char)
        idx += 1

    return "".join(out)


def _strip_trailing_commas(raw_text: str) -> str:
    out: list[str] = []
    idx = 0
    in_string = False
    escaped = False
    length = len(raw_text)

    while idx < length:
        char = raw_text[idx]

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            idx += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            idx += 1
            continue

        if char == ",":
            lookahead = idx + 1
            while lookahead < length and raw_text[lookahead].isspace():
                lookahead += 1

            if lookahead < length and raw_text[lookahead] in "]}":
                idx += 1
                continue

        out.append(char)
        idx += 1

    return "".join(out)


def _get_manifest_field(raw_data: dict[str, object], *names: str) -> tuple[object | None, str | None]:
    for name in names:
        if name in raw_data:
            return raw_data[name], name

    targets = {name.casefold() for name in names}
    for key, value in raw_data.items():
        if key.casefold() in targets:
            return value, key

    return None, None


def _parse_dependencies(
    raw_dependencies: object,
    mod_dir: Path,
    manifest_path: Path,
) -> tuple[tuple[ManifestDependency, ...], list[ParseWarning]]:
    if raw_dependencies is None:
        return tuple(), []

    if not isinstance(raw_dependencies, list):
        warning = ParseWarning(
            code=INVALID_DEPENDENCIES,
            message="Dependencies must be a list when present",
            mod_path=mod_dir,
            manifest_path=manifest_path,
        )
        return tuple(), [warning]

    dependencies: list[ManifestDependency] = []
    warnings: list[ParseWarning] = []

    for idx, item in enumerate(raw_dependencies):
        if not isinstance(item, dict):
            warnings.append(
                ParseWarning(
                    code=INVALID_DEPENDENCY_ENTRY,
                    message=f"Dependency entry at index {idx} is not an object",
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                )
            )
            continue

        dep_unique_id, _ = _get_manifest_field(item, "UniqueID", "UniqueId")
        if not isinstance(dep_unique_id, str) or not dep_unique_id.strip():
            warnings.append(
                ParseWarning(
                    code=INVALID_DEPENDENCY_ENTRY,
                    message=f"Dependency entry at index {idx} has invalid UniqueID",
                    mod_path=mod_dir,
                    manifest_path=manifest_path,
                )
            )
            continue

        required = item.get("IsRequired", True)
        dependencies.append(
            ManifestDependency(unique_id=dep_unique_id.strip(), required=bool(required))
        )

    return tuple(dependencies), warnings


def _parse_update_keys(raw_update_keys: object) -> tuple[str, ...]:
    if raw_update_keys is None:
        return tuple()
    if not isinstance(raw_update_keys, list):
        return tuple()

    keys: list[str] = []
    for item in raw_update_keys:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value:
            keys.append(value)

    return tuple(keys)


def _invalid_manifest(
    mod_dir: Path,
    manifest_path: Path,
    reason: str,
    raw_data: dict[str, object] | None = None,
) -> ManifestParseResult:
    details = reason
    if raw_data is not None:
        visible_keys = ", ".join(sorted(raw_data.keys())[:8])
        details = f"{reason}; available keys: {visible_keys or '<none>'}"

    warning = ParseWarning(
        code=INVALID_MANIFEST,
        message=details,
        mod_path=mod_dir,
        manifest_path=manifest_path,
    )
    return ManifestParseResult(manifest=None, warnings=(warning,))


def _describe_value_type(value: object) -> str:
    if value is None:
        return "null"
    return type(value).__name__
