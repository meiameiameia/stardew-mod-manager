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
