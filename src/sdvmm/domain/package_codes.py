from __future__ import annotations

from typing import Literal

PackageFindingKind = Literal[
    "direct_single_mod_package",
    "nested_single_mod_package",
    "multi_mod_package",
    "invalid_manifest_package",
    "no_usable_manifest_found",
    "too_deep_unsupported_package",
]

DIRECT_SINGLE_MOD_PACKAGE: PackageFindingKind = "direct_single_mod_package"
NESTED_SINGLE_MOD_PACKAGE: PackageFindingKind = "nested_single_mod_package"
MULTI_MOD_PACKAGE: PackageFindingKind = "multi_mod_package"
INVALID_MANIFEST_PACKAGE: PackageFindingKind = "invalid_manifest_package"
NO_USABLE_MANIFEST_FOUND: PackageFindingKind = "no_usable_manifest_found"
TOO_DEEP_UNSUPPORTED_PACKAGE: PackageFindingKind = "too_deep_unsupported_package"
