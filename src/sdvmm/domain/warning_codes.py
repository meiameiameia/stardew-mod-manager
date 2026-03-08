from __future__ import annotations

from typing import Literal

ParseWarningCode = Literal[
    "missing_manifest",
    "malformed_manifest",
    "manifest_read_error",
    "invalid_manifest",
    "invalid_dependencies",
    "invalid_dependency_entry",
]

MISSING_MANIFEST: ParseWarningCode = "missing_manifest"
MALFORMED_MANIFEST: ParseWarningCode = "malformed_manifest"
MANIFEST_READ_ERROR: ParseWarningCode = "manifest_read_error"
INVALID_MANIFEST: ParseWarningCode = "invalid_manifest"
INVALID_DEPENDENCIES: ParseWarningCode = "invalid_dependencies"
INVALID_DEPENDENCY_ENTRY: ParseWarningCode = "invalid_dependency_entry"
