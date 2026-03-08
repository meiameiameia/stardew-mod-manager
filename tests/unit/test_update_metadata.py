from __future__ import annotations

from pathlib import Path

from sdvmm.domain.models import InstalledMod, ModsInventory
from sdvmm.services.update_metadata import (
    MetadataFetchError,
    check_updates_for_inventory,
    compare_versions,
    resolve_remote_link,
)


class StubFetcher:
    def __init__(self, payloads: dict[str, dict[str, object]] | None = None, *, fail: bool = False) -> None:
        self._payloads = payloads or {}
        self._fail = fail

    def fetch_json(self, url: str, timeout_seconds: float) -> dict[str, object]:
        if self._fail:
            raise MetadataFetchError("simulated fetch failure")
        payload = self._payloads.get(url)
        if payload is None:
            raise MetadataFetchError(f"no payload for {url}")
        return payload


def test_compare_versions_derives_expected_ordering() -> None:
    assert compare_versions("1.0.0", "1.1.0") == -1
    assert compare_versions("1.2.0", "1.2.0") == 0
    assert compare_versions("1.4.0", "1.3.9") == 1


def test_update_available_when_remote_version_is_newer() -> None:
    mod = _mod(
        unique_id="Sample.Mod",
        version="1.0.0",
        update_keys=("Json:https://example.test/mod-a.json",),
    )
    inventory = _inventory((mod,))
    fetcher = StubFetcher(
        payloads={
            "https://example.test/mod-a.json": {
                "version": "1.1.0",
                "page_url": "https://example.test/mod-a",
            }
        }
    )

    report = check_updates_for_inventory(inventory, fetcher=fetcher)

    status = report.statuses[0]
    assert status.state == "update_available"
    assert status.remote_version == "1.1.0"
    assert status.remote_link is not None
    assert status.remote_link.page_url == "https://example.test/mod-a"


def test_up_to_date_when_remote_version_matches_installed() -> None:
    mod = _mod(
        unique_id="Sample.Mod",
        version="2.0.0",
        update_keys=("Json:https://example.test/mod-a.json",),
    )
    inventory = _inventory((mod,))
    fetcher = StubFetcher(
        payloads={
            "https://example.test/mod-a.json": {
                "version": "2.0.0",
                "page_url": "https://example.test/mod-a",
            }
        }
    )

    report = check_updates_for_inventory(inventory, fetcher=fetcher)

    status = report.statuses[0]
    assert status.state == "up_to_date"
    assert status.remote_version == "2.0.0"


def test_no_remote_link_state_when_update_keys_are_missing() -> None:
    mod = _mod(unique_id="Sample.NoLink", version="1.0.0", update_keys=tuple())
    inventory = _inventory((mod,))

    report = check_updates_for_inventory(inventory, fetcher=StubFetcher())

    status = report.statuses[0]
    assert status.state == "no_remote_link"
    assert status.remote_version is None
    assert status.remote_link is None


def test_metadata_unavailable_when_fetch_fails() -> None:
    mod = _mod(
        unique_id="Sample.Mod",
        version="1.0.0",
        update_keys=("Json:https://example.test/mod-a.json",),
    )
    inventory = _inventory((mod,))

    report = check_updates_for_inventory(inventory, fetcher=StubFetcher(fail=True))

    status = report.statuses[0]
    assert status.state == "metadata_unavailable"
    assert status.remote_link is not None
    assert "Could not load remote metadata" in (status.message or "")


def test_resolve_remote_link_prefers_metadata_capable_provider() -> None:
    link = resolve_remote_link(
        (
            "Nexus:12345",
            "GitHub:owner/repo",
        )
    )

    assert link is not None
    assert link.provider == "github"


def _inventory(mods: tuple[InstalledMod, ...]) -> ModsInventory:
    return ModsInventory(
        mods=mods,
        parse_warnings=tuple(),
        duplicate_unique_ids=tuple(),
        missing_required_dependencies=tuple(),
        scan_entry_findings=tuple(),
        ignored_entries=tuple(),
    )


def _mod(unique_id: str, version: str, update_keys: tuple[str, ...]) -> InstalledMod:
    base = Path("/tmp") / unique_id.replace(".", "_")
    return InstalledMod(
        unique_id=unique_id,
        name=unique_id,
        version=version,
        folder_path=base,
        manifest_path=base / "manifest.json",
        dependencies=tuple(),
        update_keys=update_keys,
    )
