from __future__ import annotations

from typing import Literal

DiscoveryProvider = Literal[
    "smapi_compatibility_list",
]

SMAPI_COMPATIBILITY_LIST_PROVIDER: DiscoveryProvider = "smapi_compatibility_list"

DiscoveryCompatibilityState = Literal[
    "compatible",
    "compatible_with_caveat",
    "unofficial_update",
    "workaround_available",
    "incompatible",
    "abandoned",
    "obsolete",
    "compatibility_unknown",
]

COMPATIBLE: DiscoveryCompatibilityState = "compatible"
COMPATIBLE_WITH_CAVEAT: DiscoveryCompatibilityState = "compatible_with_caveat"
UNOFFICIAL_UPDATE: DiscoveryCompatibilityState = "unofficial_update"
WORKAROUND_AVAILABLE: DiscoveryCompatibilityState = "workaround_available"
INCOMPATIBLE: DiscoveryCompatibilityState = "incompatible"
ABANDONED: DiscoveryCompatibilityState = "abandoned"
OBSOLETE: DiscoveryCompatibilityState = "obsolete"
COMPATIBILITY_UNKNOWN: DiscoveryCompatibilityState = "compatibility_unknown"

DiscoverySourceProvider = Literal[
    "nexus",
    "github",
    "custom_url",
    "none",
]

DISCOVERY_SOURCE_NEXUS: DiscoverySourceProvider = "nexus"
DISCOVERY_SOURCE_GITHUB: DiscoverySourceProvider = "github"
DISCOVERY_SOURCE_CUSTOM_URL: DiscoverySourceProvider = "custom_url"
DISCOVERY_SOURCE_NONE: DiscoverySourceProvider = "none"
