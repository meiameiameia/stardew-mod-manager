from __future__ import annotations

from typing import Literal

UpdateState = Literal[
    "up_to_date",
    "update_available",
    "no_remote_link",
    "metadata_unavailable",
]

UP_TO_DATE: UpdateState = "up_to_date"
UPDATE_AVAILABLE: UpdateState = "update_available"
NO_REMOTE_LINK: UpdateState = "no_remote_link"
METADATA_UNAVAILABLE: UpdateState = "metadata_unavailable"

RemoteLinkProvider = Literal[
    "github",
    "nexus",
    "json",
]

GITHUB_PROVIDER: RemoteLinkProvider = "github"
NEXUS_PROVIDER: RemoteLinkProvider = "nexus"
JSON_PROVIDER: RemoteLinkProvider = "json"

UpdateSourceDiagnosticCode = Literal[
    "local_private_mod",
    "missing_update_key",
    "unsupported_update_key_format",
    "no_provider_mapping",
    "remote_metadata_lookup_failed",
    "metadata_source_issue",
]

LOCAL_PRIVATE_MOD: UpdateSourceDiagnosticCode = "local_private_mod"
MISSING_UPDATE_KEY: UpdateSourceDiagnosticCode = "missing_update_key"
UNSUPPORTED_UPDATE_KEY_FORMAT: UpdateSourceDiagnosticCode = "unsupported_update_key_format"
NO_PROVIDER_MAPPING: UpdateSourceDiagnosticCode = "no_provider_mapping"
REMOTE_METADATA_LOOKUP_FAILED: UpdateSourceDiagnosticCode = "remote_metadata_lookup_failed"
METADATA_SOURCE_ISSUE: UpdateSourceDiagnosticCode = "metadata_source_issue"
