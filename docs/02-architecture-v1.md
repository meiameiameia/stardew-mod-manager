# Architecture Note v1

## Proposed stack with justification

### Recommendation

Use Python 3.12 plus PySide6 for the desktop app, SQLite for local state, and `pytest` for tests.

### Why this is the safest current choice

- The product is dominated by local filesystem, archive, manifest, and log-processing work. Python handles that domain with low ceremony and strong standard-library support.
- PySide6 is mature, cross-platform, and sufficient for a utilitarian desktop UI without committing to a browser-based desktop shell.
- SQLite is deterministic, local-first, inspectable, and enough for inventory, profile metadata, history, and cache state.
- This avoids introducing a split frontend/backend architecture before it is justified.
- Linux-first delivery is straightforward while still keeping Windows support realistic later.

### Rejected-for-now alternatives

- Tauri plus web UI: viable, but adds cross-language complexity too early for a utility app whose hardest problems are local file operations.
- Electron: higher runtime overhead and no clear advantage for the MVP.
- Pure CLI first: lower initial cost, but profile switching, diagnostics, and inventory review benefit from a simple desktop shell from the start.

## Domain and module boundaries

- `app`: application bootstrap, dependency wiring, config loading, lifecycle.
- `domain`: core entities and rules, independent from UI and filesystem details.
- `services`: orchestration for scan, install, rollback, profile switch, update check, and log analysis.
- `infra.fs`: filesystem reads, writes, archive extraction, snapshot creation, atomic replace helpers.
- `infra.db`: SQLite persistence and repository implementations.
- `infra.metadata`: allowed remote metadata clients and cache handling.
- `ui`: PySide6 windows, dialogs, view models, table models.
- `diagnostics`: SMAPI log parsing, issue classification, remediation hints.

These boundaries are intentionally boring. The domain should not know about PySide6 or raw SQLite.

## Local data model proposal

### Core tables

- `app_config`
  - stores configured game path, active Mods path, app data root, active profile ID
- `profiles`
  - `id`, `name`, `mods_dir_mode`, `path`, `created_at`, `updated_at`
- `mods`
  - canonical installed mod record for the active scan: `id`, `profile_id`, `unique_id`, `name`, `version`, `path`, `manifest_path`, `author`, `description`, `scan_hash`, `last_seen_at`
- `mod_dependencies`
  - `mod_id`, `dependency_unique_id`, `required`, `min_version`, `source`
- `mod_conflicts`
  - derived findings cache: `profile_id`, `kind`, `subject_unique_id`, `details_json`
- `install_history`
  - `id`, `profile_id`, `operation`, `archive_path`, `snapshot_id`, `started_at`, `finished_at`, `status`, `details_json`
- `snapshots`
  - `id`, `profile_id`, `kind`, `storage_path`, `created_at`, `reason`
- `update_cache`
  - `unique_id`, `source`, `remote_version`, `checked_at`, `raw_json`

### Domain objects

- `Profile`
- `InstalledMod`
- `DependencyEdge`
- `ConflictFinding`
- `InstallPlan`
- `SnapshotRecord`
- `LogDiagnostic`

The SQLite schema stores scan results and operation history. It should not be treated as the source of truth for installed files; the filesystem remains authoritative.

## Filesystem model assumptions

- User supplies explicit paths; the app does not guess aggressively.
- Active mod content lives in a real directory on disk, not inside a database.
- The app keeps its own state under an app data root, separate from the game install.
- Extraction and staging happen in temporary directories inside app-managed storage, then move into place.
- Case sensitivity must not be assumed long-term, even if Linux is the first target.
- Symlinks inside user mod directories should be detected and surfaced, not silently rewritten.

## Safe install/update pipeline concept

1. User selects a local archive file.
2. App extracts into a staging directory under app-managed temp storage.
3. App inspects extracted content and identifies candidate manifest roots.
4. App validates installability:
   - manifest present
   - one or more mod roots identified
   - target conflicts known
   - no path traversal or unsafe archive paths
5. App creates a pre-change snapshot of affected directories.
6. App applies changes using deterministic filesystem operations:
   - move or copy staged mod roots into the active profile mod directory
   - avoid partial overwrite when possible
   - record replaced paths explicitly
7. App rescans and records findings.

For update checks, the app may fetch metadata from allowed sources, compare versions, and tell the user an update exists. It does not download archives.

## Rollback and archive concept

- Every mutating operation creates a snapshot record first.
- Snapshot scope is narrow: only affected mod directories and operation metadata, not a blind copy of the whole game tree.
- Snapshots are stored in app-managed archive storage with manifest metadata describing what was changed.
- Rollback replays the inverse operation from snapshot contents and then rescans.
- Old snapshots should be prunable by retention policy, but retention policy is not part of Stage 1.

## Profile strategy options with recommendation

### Option A: Separate real directories per profile

- Each profile owns its own full `Mods` directory copy.
- Pros: simple mental model, robust, easy rollback.
- Cons: disk-heavy, slower switching.

### Option B: Canonical profile store plus active materialization

- Each profile is stored separately under app data or user-selected paths.
- Switching materializes the selected profile into the live game `Mods` directory transactionally.
- Pros: explicit behavior, good rollback boundary, no symlink dependency.
- Cons: switching is slower than pointer-style approaches.

### Option C: Symlink-based profiles

- Active `Mods` directory is assembled from symlinks.
- Pros: fast switching, low disk use.
- Cons: brittle across filesystems, confusing for users, worse future Windows story.

### Recommendation

Choose Option B. It is the safest balance between determinism, rollback clarity, Linux practicality, and future Windows support. Avoid symlink-based design in the MVP.

## Edge cases that must shape the design

- Archives with nested top-level folders before the real mod root.
- Archives containing multiple mods in one package.
- Non-mod files mixed with valid mod folders.
- Duplicate `UniqueID` values across different folders or versions.
- Missing `manifest.json` or malformed manifests.
- Partial overwrite during crash or interruption.
- User-selected Mods path on another filesystem, making atomic rename less reliable.
- Read-only files, permission issues, or unexpected ownership on Linux.
- Active profile content modified outside the app between scans.
- SMAPI logs from different versions or with truncated content.
- Version strings that are non-semantic or custom-formatted.
