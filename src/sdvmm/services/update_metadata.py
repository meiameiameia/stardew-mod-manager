from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sdvmm.domain.models import (
    InstalledMod,
    ModUpdateReport,
    ModUpdateStatus,
    ModsInventory,
    RemoteModLink,
)
from sdvmm.domain.update_codes import (
    GITHUB_PROVIDER,
    JSON_PROVIDER,
    METADATA_UNAVAILABLE,
    NEXUS_PROVIDER,
    NO_REMOTE_LINK,
    UPDATE_AVAILABLE,
    UP_TO_DATE,
)


class MetadataFetchError(ValueError):
    """Raised when remote metadata cannot be retrieved or parsed."""


class JsonMetadataFetcher(Protocol):
    def fetch_json(self, url: str, timeout_seconds: float) -> dict[str, Any]:
        """Fetch JSON from a remote URL."""


class UrllibJsonMetadataFetcher:
    def fetch_json(self, url: str, timeout_seconds: float) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": "sdvmm/0.1 (+local metadata check)",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise MetadataFetchError(str(exc)) from exc

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MetadataFetchError(f"Invalid metadata JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise MetadataFetchError("Metadata payload must be a JSON object")

        return data


def check_updates_for_inventory(
    inventory: ModsInventory,
    *,
    fetcher: JsonMetadataFetcher | None = None,
    timeout_seconds: float = 8.0,
) -> ModUpdateReport:
    active_fetcher = fetcher or UrllibJsonMetadataFetcher()

    statuses: list[ModUpdateStatus] = []
    for mod in inventory.mods:
        statuses.append(
            _check_single_mod(
                mod=mod,
                fetcher=active_fetcher,
                timeout_seconds=timeout_seconds,
            )
        )

    statuses.sort(key=lambda status: (status.name.casefold(), status.folder_path.name.casefold()))
    return ModUpdateReport(statuses=tuple(statuses))


def compare_versions(installed_version: str, remote_version: str) -> int | None:
    left = _tokenize_version(installed_version)
    right = _tokenize_version(remote_version)

    if not left or not right:
        return None

    max_len = max(len(left), len(right))
    for idx in range(max_len):
        left_token = left[idx] if idx < len(left) else 0
        right_token = right[idx] if idx < len(right) else 0

        if left_token == right_token:
            continue

        left_key = _token_key(left_token)
        right_key = _token_key(right_token)
        if left_key < right_key:
            return -1
        return 1

    return 0


def _check_single_mod(
    mod: InstalledMod,
    *,
    fetcher: JsonMetadataFetcher,
    timeout_seconds: float,
) -> ModUpdateStatus:
    link = resolve_remote_link(mod.update_keys)
    base_status = ModUpdateStatus(
        unique_id=mod.unique_id,
        name=mod.name,
        folder_path=mod.folder_path,
        installed_version=mod.version,
        remote_version=None,
        state=NO_REMOTE_LINK,
        remote_link=link,
        message=None,
    )

    if link is None:
        return base_status

    if link.metadata_url is None:
        return replace(
            base_status,
            state=METADATA_UNAVAILABLE,
            message="Metadata endpoint is not supported for this remote link provider.",
        )

    try:
        payload = fetcher.fetch_json(link.metadata_url, timeout_seconds)
    except MetadataFetchError as exc:
        return replace(
            base_status,
            state=METADATA_UNAVAILABLE,
            message=f"Could not load remote metadata: {exc}",
        )

    remote_version = _extract_remote_version(link.provider, payload)
    page_url = _extract_remote_page_url(payload)
    if page_url:
        link = replace(link, page_url=page_url)

    if remote_version is None:
        return replace(
            base_status,
            state=METADATA_UNAVAILABLE,
            remote_link=link,
            message="Remote metadata does not provide a usable version field.",
        )

    comparison = compare_versions(mod.version, remote_version)
    if comparison is None:
        return replace(
            base_status,
            state=METADATA_UNAVAILABLE,
            remote_link=link,
            remote_version=remote_version,
            message="Installed or remote version format is not comparable.",
        )

    if comparison < 0:
        return replace(
            base_status,
            state=UPDATE_AVAILABLE,
            remote_link=link,
            remote_version=remote_version,
            message="Remote version is newer than installed version.",
        )

    return replace(
        base_status,
        state=UP_TO_DATE,
        remote_link=link,
        remote_version=remote_version,
        message="Installed version is up to date.",
    )


def resolve_remote_link(update_keys: tuple[str, ...]) -> RemoteModLink | None:
    candidates: list[RemoteModLink] = []

    for raw_key in update_keys:
        provider, value = _parse_update_key(raw_key)
        if provider is None:
            continue

        if provider == GITHUB_PROVIDER and "/" in value:
            repo = value.strip()
            candidates.append(
                RemoteModLink(
                    provider=GITHUB_PROVIDER,
                    key=repo,
                    page_url=f"https://github.com/{repo}",
                    metadata_url=f"https://api.github.com/repos/{repo}/releases/latest",
                )
            )

        if provider == NEXUS_PROVIDER and value.strip():
            mod_id = value.strip()
            candidates.append(
                RemoteModLink(
                    provider=NEXUS_PROVIDER,
                    key=mod_id,
                    page_url=f"https://www.nexusmods.com/stardewvalley/mods/{mod_id}",
                    metadata_url=None,
                )
            )

        if provider == JSON_PROVIDER and _looks_like_url(value):
            url = value.strip()
            candidates.append(
                RemoteModLink(
                    provider=JSON_PROVIDER,
                    key=url,
                    page_url=url,
                    metadata_url=url,
                )
            )

    for provider in (JSON_PROVIDER, GITHUB_PROVIDER, NEXUS_PROVIDER):
        for candidate in candidates:
            if candidate.provider == provider:
                return candidate

    return None


def _parse_update_key(raw_key: str) -> tuple[str | None, str]:
    if ":" not in raw_key:
        return None, ""

    prefix, value = raw_key.split(":", 1)
    provider = prefix.strip().casefold()
    return provider, value.strip()


def _tokenize_version(version: str) -> list[int | str]:
    chunks = [chunk for chunk in re.split(r"[^0-9A-Za-z]+", version.strip()) if chunk]
    tokens: list[int | str] = []
    for chunk in chunks:
        if chunk.isdigit():
            tokens.append(int(chunk))
        else:
            tokens.append(chunk.casefold())

    return tokens


def _token_key(value: int | str) -> tuple[int, int | str]:
    if isinstance(value, int):
        return (0, value)
    return (1, value)


def _extract_remote_version(provider: str, payload: dict[str, Any]) -> str | None:
    if provider == GITHUB_PROVIDER:
        tag_name = payload.get("tag_name")
        if isinstance(tag_name, str) and tag_name.strip():
            stripped = tag_name.strip()
            if stripped.startswith(("v", "V")) and len(stripped) > 1 and stripped[1].isdigit():
                return stripped[1:]
            return stripped

    for key in ("version", "Version", "latest_version", "latestVersion"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _extract_remote_page_url(payload: dict[str, Any]) -> str | None:
    for key in ("html_url", "page_url", "url"):
        value = payload.get(key)
        if isinstance(value, str) and _looks_like_url(value):
            return value.strip()
    return None


def _looks_like_url(value: str) -> bool:
    lowered = value.strip().casefold()
    return lowered.startswith("https://") or lowered.startswith("http://")
