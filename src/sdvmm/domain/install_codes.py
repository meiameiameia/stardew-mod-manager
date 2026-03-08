from __future__ import annotations

from typing import Literal

SandboxInstallAction = Literal[
    "install_new",
    "overwrite_with_archive",
    "blocked",
]

INSTALL_NEW: SandboxInstallAction = "install_new"
OVERWRITE_WITH_ARCHIVE: SandboxInstallAction = "overwrite_with_archive"
BLOCKED: SandboxInstallAction = "blocked"
