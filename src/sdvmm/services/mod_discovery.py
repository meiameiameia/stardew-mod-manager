from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
import re
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sdvmm.domain.discovery_codes import (
    ABANDONED,
    COMPATIBILITY_UNKNOWN,
    COMPATIBLE,
    COMPATIBLE_WITH_CAVEAT,
    DISCOVERY_SOURCE_CUSTOM_URL,
    DISCOVERY_SOURCE_GITHUB,
    DISCOVERY_SOURCE_NEXUS,
    DISCOVERY_SOURCE_NONE,
    INCOMPATIBLE,
    OBSOLETE,
    SMAPI_COMPATIBILITY_LIST_PROVIDER,
    UNOFFICIAL_UPDATE,
    WORKAROUND_AVAILABLE,
)
from sdvmm.domain.models import ModDiscoveryEntry, ModDiscoveryResult

SMAPI_COMPATIBILITY_INDEX_URL = (
    "https://raw.githubusercontent.com/Pathoschild/SmapiCompatibilityList/develop/data/mods.jsonc"
)

DISCOVERY_INVALID_QUERY = "invalid_query"
DISCOVERY_REQUEST_FAILURE = "request_failure"
DISCOVERY_INVALID_PAYLOAD = "invalid_payload"


class DiscoveryServiceError(ValueError):
    """Raised when mod discovery cannot complete."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class DiscoveryTextFetcher(Protocol):
    def fetch_text(self, url: str, timeout_seconds: float) -> str:
        """Fetch raw text from a remote URL."""


class UrllibDiscoveryTextFetcher:
    def fetch_text(self, url: str, timeout_seconds: float) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "sdvmm/0.1 (+local discovery)",
                "Accept": "application/json,text/plain,*/*",
            },
        )

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            raise DiscoveryServiceError(
                DISCOVERY_REQUEST_FAILURE,
                f"HTTP {exc.code}: {exc.reason or 'request failed'}",
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DiscoveryServiceError(DISCOVERY_REQUEST_FAILURE, str(exc)) from exc


@dataclass(frozen=True, slots=True)
class _IndexedEntry:
    mod: ModDiscoveryEntry
    searchable_text: str


def search_discoverable_mods(
    query: str,
    *,
    fetcher: DiscoveryTextFetcher | None = None,
    timeout_seconds: float = 10.0,
    max_results: int = 50,
) -> ModDiscoveryResult:
    normalized_query = query.strip()
    if not normalized_query:
        raise DiscoveryServiceError(DISCOVERY_INVALID_QUERY, "Search query is required.")

    if max_results <= 0:
        raise DiscoveryServiceError(
            DISCOVERY_INVALID_QUERY,
            "max_results must be greater than zero.",
        )

    active_fetcher = fetcher or UrllibDiscoveryTextFetcher()
    raw_index_text = active_fetcher.fetch_text(SMAPI_COMPATIBILITY_INDEX_URL, timeout_seconds)
    index_data = _load_index_json(raw_index_text)
    indexed_entries = _normalize_index_entries(index_data)
    matches = _match_entries(indexed_entries, normalized_query, max_results=max_results)

    notes = tuple() if matches else ("No matching mods found in SMAPI compatibility index.",)
    return ModDiscoveryResult(
        query=normalized_query,
        provider=SMAPI_COMPATIBILITY_LIST_PROVIDER,
        results=tuple(match.mod for match in matches),
        notes=notes,
    )


def _load_index_json(raw_text: str) -> Mapping[str, object]:
    try:
        data = json.loads(raw_text)
    except JSONDecodeError:
        try:
            data = json.loads(_normalize_relaxed_json(raw_text))
        except JSONDecodeError as exc:
            raise DiscoveryServiceError(
                DISCOVERY_INVALID_PAYLOAD,
                f"Invalid compatibility index JSON: {exc}",
            ) from exc

    if not isinstance(data, dict):
        raise DiscoveryServiceError(
            DISCOVERY_INVALID_PAYLOAD,
            "Compatibility index payload must be a JSON object.",
        )

    return data


def _normalize_index_entries(index_data: Mapping[str, object]) -> tuple[_IndexedEntry, ...]:
    raw_mods = index_data.get("mods")
    raw_broken_content_packs = index_data.get("brokenContentPacks")

    entries: list[_IndexedEntry] = []
    for raw_group in (raw_mods, raw_broken_content_packs):
        if not isinstance(raw_group, list):
            continue
        for raw_entry in raw_group:
            normalized = _normalize_entry(raw_entry)
            if normalized is not None:
                entries.append(normalized)

    entries.sort(
        key=lambda entry: (
            entry.mod.name.casefold(),
            entry.mod.unique_id.casefold(),
        )
    )
    return tuple(entries)


def _normalize_entry(raw_entry: object) -> _IndexedEntry | None:
    if not isinstance(raw_entry, Mapping):
        return None

    name_raw = raw_entry.get("name")
    id_raw = raw_entry.get("id")
    author_raw = raw_entry.get("author")
    if not isinstance(name_raw, str) or not isinstance(id_raw, str):
        return None

    names = _split_aliases(name_raw)
    unique_ids = _split_aliases(id_raw)
    if not names or not unique_ids:
        return None

    source_provider, source_page_url = _resolve_source_page(raw_entry)
    status_code = _derive_smapi_status(raw_entry)
    compatibility_state = _map_compatibility_state(status_code)
    compatibility_summary = _build_compatibility_summary(raw_entry, status_code)

    author = author_raw.strip() if isinstance(author_raw, str) and author_raw.strip() else "Unknown author"
    mod = ModDiscoveryEntry(
        name=names[0],
        unique_id=unique_ids[0],
        author=author,
        provider=SMAPI_COMPATIBILITY_LIST_PROVIDER,
        source_provider=source_provider,
        source_page_url=source_page_url,
        compatibility_state=compatibility_state,
        compatibility_status=status_code,
        compatibility_summary=compatibility_summary,
        alternate_names=tuple(names[1:]),
        alternate_unique_ids=tuple(unique_ids[1:]),
    )

    searchable_parts = [mod.name, mod.unique_id, mod.author]
    searchable_parts.extend(mod.alternate_names)
    searchable_parts.extend(mod.alternate_unique_ids)
    searchable_text = " ".join(part for part in searchable_parts if part).casefold()
    return _IndexedEntry(mod=mod, searchable_text=searchable_text)


def _split_aliases(value: str) -> tuple[str, ...]:
    aliases = [part.strip() for part in value.split(",")]
    deduped: dict[str, str] = {}
    for alias in aliases:
        if not alias:
            continue
        key = alias.casefold()
        if key not in deduped:
            deduped[key] = alias
    return tuple(deduped.values())


def _resolve_source_page(raw_entry: Mapping[str, object]) -> tuple[str, str | None]:
    nexus_value = raw_entry.get("nexus")
    if isinstance(nexus_value, int) and nexus_value > 0:
        return (
            DISCOVERY_SOURCE_NEXUS,
            f"https://www.nexusmods.com/stardewvalley/mods/{nexus_value}",
        )

    github_value = raw_entry.get("github")
    if isinstance(github_value, str) and _looks_like_repo_slug(github_value):
        return (
            DISCOVERY_SOURCE_GITHUB,
            f"https://github.com/{github_value.strip()}",
        )

    for field in ("url", "source"):
        value = raw_entry.get(field)
        if isinstance(value, str) and _looks_like_url(value):
            return (DISCOVERY_SOURCE_CUSTOM_URL, value.strip())

    return (DISCOVERY_SOURCE_NONE, None)


def _derive_smapi_status(raw_entry: Mapping[str, object]) -> str:
    status = raw_entry.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().casefold()

    unofficial_update = raw_entry.get("unofficialUpdate")
    if isinstance(unofficial_update, Mapping):
        return "unofficial"

    broke_in = raw_entry.get("brokeIn")
    if isinstance(broke_in, str) and broke_in.strip():
        return "broken"

    return "ok"


def _map_compatibility_state(status_code: str) -> str:
    mapping = {
        "ok": COMPATIBLE,
        "optional": COMPATIBLE_WITH_CAVEAT,
        "unofficial": UNOFFICIAL_UPDATE,
        "workaround": WORKAROUND_AVAILABLE,
        "broken": INCOMPATIBLE,
        "abandoned": ABANDONED,
        "obsolete": OBSOLETE,
        "unknown": COMPATIBILITY_UNKNOWN,
    }
    return mapping.get(status_code, COMPATIBILITY_UNKNOWN)


def _build_compatibility_summary(raw_entry: Mapping[str, object], status_code: str) -> str | None:
    summary = raw_entry.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    broke_in = raw_entry.get("brokeIn")
    if status_code in {"broken", "workaround"} and isinstance(broke_in, str) and broke_in.strip():
        return f"Reported incompatible since {broke_in.strip()}."

    if status_code == "optional":
        return "This mod has caveats; use the recommended optional variant when required."

    if status_code == "unofficial":
        update = raw_entry.get("unofficialUpdate")
        if isinstance(update, Mapping):
            version = update.get("version")
            if isinstance(version, str) and version.strip():
                return f"Use unofficial update version {version.strip()}."
        return "Use an unofficial update for compatibility."

    if status_code == "abandoned":
        reason = raw_entry.get("abandonedReason")
        if isinstance(reason, str) and reason.strip():
            return f"Marked abandoned ({reason.strip()})."
        return "Marked abandoned by compatibility index."

    return None


def _match_entries(
    entries: tuple[_IndexedEntry, ...],
    query: str,
    *,
    max_results: int,
) -> tuple[_IndexedEntry, ...]:
    query_key = query.casefold().strip()
    terms = tuple(part for part in re.split(r"\s+", query_key) if part)

    scored: list[tuple[int, _IndexedEntry]] = []
    for entry in entries:
        score = _entry_match_score(entry, query_key, terms)
        if score < 0:
            continue
        scored.append((score, entry))

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].mod.name.casefold(),
            item[1].mod.unique_id.casefold(),
        )
    )
    return tuple(entry for _, entry in scored[:max_results])


def _entry_match_score(entry: _IndexedEntry, query_key: str, terms: tuple[str, ...]) -> int:
    mod = entry.mod
    if query_key in {
        mod.unique_id.casefold(),
        *(alias.casefold() for alias in mod.alternate_unique_ids),
    }:
        return 100

    if query_key == mod.name.casefold():
        return 95

    if mod.unique_id.casefold().startswith(query_key):
        return 85

    if mod.name.casefold().startswith(query_key):
        return 80

    if query_key in mod.name.casefold():
        return 70

    if query_key in mod.unique_id.casefold():
        return 65

    if query_key in mod.author.casefold():
        return 55

    if query_key in entry.searchable_text:
        return 45

    if terms and all(term in entry.searchable_text for term in terms):
        return 40

    return -1


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


def _looks_like_repo_slug(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value.strip()) is not None


def _looks_like_url(value: str) -> bool:
    lowered = value.strip().casefold()
    return lowered.startswith("https://") or lowered.startswith("http://")
