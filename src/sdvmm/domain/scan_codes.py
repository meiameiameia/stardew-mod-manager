from __future__ import annotations

from typing import Literal

ScanEntryKind = Literal[
    "direct_mod",
    "nested_mod_container",
    "multi_mod_container",
    "missing_manifest",
    "invalid_manifest",
    "ambiguous_entry",
]

DIRECT_MOD: ScanEntryKind = "direct_mod"
NESTED_MOD_CONTAINER: ScanEntryKind = "nested_mod_container"
MULTI_MOD_CONTAINER: ScanEntryKind = "multi_mod_container"
MISSING_MANIFEST_ENTRY: ScanEntryKind = "missing_manifest"
INVALID_MANIFEST_ENTRY: ScanEntryKind = "invalid_manifest"
AMBIGUOUS_ENTRY: ScanEntryKind = "ambiguous_entry"
