from __future__ import annotations

from typing import Final

import pytest

from sdvmm.services.mod_discovery import (
    DISCOVERY_INVALID_PAYLOAD,
    DISCOVERY_INVALID_QUERY,
    DiscoveryServiceError,
    search_discoverable_mods,
)


class StubTextFetcher:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def fetch_text(self, url: str, timeout_seconds: float) -> str:
        _ = timeout_seconds
        self.calls.append(url)
        return self._payload


BASE_INDEX_JSONC: Final[str] = """
{
  // compatibility index fixture
  "mods": [
    {
      "name": "SpaceCore, Space Core",
      "author": "spacechase0",
      "id": "spacechase0.SpaceCore, spacechase0.SpaceCoreLegacy",
      "nexus": 1348,
      "github": "spacechase0/SpaceCore"
    },
    {
      "name": "Optional Helper",
      "author": "SampleAuthor",
      "id": "sample.OptionalHelper",
      "nexus": null,
      "github": "owner/helper",
      "status": "optional"
    },
    {
      "name": "Broken Legacy",
      "author": "Legacy",
      "id": "legacy.Broken",
      "nexus": 10,
      "github": null,
      "brokeIn": "Stardew Valley 1.6"
    },
    {
      "name": "Unofficial Needed",
      "author": "Legacy",
      "id": "legacy.Unofficial",
      "nexus": null,
      "github": null,
      "unofficialUpdate": {
        "version": "1.2.4-unofficial.1-pathoschild",
        "url": "https://example.test/unofficial"
      },
      "url": "https://example.test/mod"
    }
  ],
  "brokenContentPacks": [
    {
      "name": "Old Pack",
      "author": "Pack Author",
      "id": "pack.OldPack",
      "nexus": 999,
      "github": null,
      "status": "workaround",
      "summary": "use [new pack](#) instead."
    },
  ],
}
"""


def test_search_normalizes_aliases_and_matches_alternate_unique_id() -> None:
    fetcher = StubTextFetcher(BASE_INDEX_JSONC)

    result = search_discoverable_mods(
        "spacecorelegacy",
        fetcher=fetcher,
    )

    assert len(result.results) == 1
    entry = result.results[0]
    assert entry.name == "SpaceCore"
    assert entry.unique_id == "spacechase0.SpaceCore"
    assert entry.alternate_unique_ids == ("spacechase0.SpaceCoreLegacy",)
    assert entry.compatibility_state == "compatible"
    assert entry.source_provider == "nexus"
    assert entry.source_page_url == "https://www.nexusmods.com/stardewvalley/mods/1348"


def test_search_maps_smapi_compatibility_states() -> None:
    fetcher = StubTextFetcher(BASE_INDEX_JSONC)

    result = search_discoverable_mods("legacy", fetcher=fetcher, max_results=10)
    by_id = {entry.unique_id: entry for entry in result.results}

    assert by_id["legacy.Broken"].compatibility_state == "incompatible"
    assert by_id["legacy.Broken"].compatibility_summary == "Reported incompatible since Stardew Valley 1.6."
    assert by_id["legacy.Unofficial"].compatibility_state == "unofficial_update"
    assert "unofficial update version" in (by_id["legacy.Unofficial"].compatibility_summary or "").casefold()

    pack_result = search_discoverable_mods("old pack", fetcher=fetcher, max_results=10)
    pack_by_id = {entry.unique_id: entry for entry in pack_result.results}
    assert pack_by_id["pack.OldPack"].compatibility_state == "workaround_available"


def test_search_maps_source_page_fallbacks() -> None:
    fetcher = StubTextFetcher(BASE_INDEX_JSONC)

    result = search_discoverable_mods("helper", fetcher=fetcher, max_results=10)

    assert len(result.results) == 1
    entry = result.results[0]
    assert entry.unique_id == "sample.OptionalHelper"
    assert entry.source_provider == "github"
    assert entry.source_page_url == "https://github.com/owner/helper"
    assert entry.compatibility_state == "compatible_with_caveat"


def test_search_rejects_blank_query() -> None:
    with pytest.raises(DiscoveryServiceError) as exc_info:
        _ = search_discoverable_mods("   ", fetcher=StubTextFetcher(BASE_INDEX_JSONC))

    assert exc_info.value.reason == DISCOVERY_INVALID_QUERY


def test_search_reports_invalid_payload() -> None:
    with pytest.raises(DiscoveryServiceError) as exc_info:
        _ = search_discoverable_mods("spacecore", fetcher=StubTextFetcher("{ not json"))

    assert exc_info.value.reason == DISCOVERY_INVALID_PAYLOAD
