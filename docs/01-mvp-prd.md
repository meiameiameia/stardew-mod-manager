# MVP PRD

## Problem statement

Stardew Valley players on Linux often manage SMAPI mods manually with ad hoc folder copies, archive extraction, and profile switching. That creates avoidable failure modes: duplicate mods, incompatible versions, missing dependencies, hard-to-reverse installs, and slow diagnosis when the game or SMAPI reports errors.

## Target user

Primary user: Linux desktop Stardew Valley player using SMAPI mods who wants a local-first tool to inspect, install, organize, and troubleshoot mods without relying on browser automation or automatic download flows.

Secondary user: technically comfortable player maintaining multiple save or mod profiles and wanting safer rollback and conflict visibility.

## Goals

- Show a reliable local inventory of installed mods.
- Detect duplicate mod IDs, obvious conflicts, and missing dependencies from local metadata.
- Support manual-download-assisted installation from local archive files.
- Preserve rollback history through archive and snapshot mechanisms.
- Support multiple mod profiles with explicit switching behavior.
- Parse SMAPI logs locally and surface actionable diagnostics.
- Keep behavior deterministic and inspectable on Linux filesystems.

## Non-goals

- Automatic downloading of mods from remote services.
- Browser automation, scraping, or bypass of premium or gated download flows.
- Cloud sync, multi-user collaboration, or online accounts.
- Full mod compatibility resolution beyond metadata and explicit heuristics.
- Rich UI polish in MVP.
- Save-file editing or broader Stardew game management outside mods and logs.

## Core user flows

1. User points the app at a Stardew Valley install and Mods directory.
2. App scans installed mods and shows inventory, duplicates, dependencies, and parse warnings.
3. User selects a downloaded archive file from disk and installs it into the active profile through a safe local pipeline.
4. App snapshots affected state before changes and allows rollback.
5. User switches between profiles and sees what changes will be applied.
6. User imports or opens a SMAPI log file and reviews local diagnostics.
7. User checks whether installed mods appear out of date using allowed metadata lookups, without downloading files automatically.

## MVP features

- Initial configuration for game path, Mods path, and app data path.
- Local mod inventory scan using manifest metadata.
- Duplicate mod detection by unique mod ID.
- Dependency visibility from manifests, including missing and mismatched required dependencies when discoverable locally.
- Manual archive import and install from `.zip` files stored on disk.
- Pre-change snapshot and rollback for installs, removals, and profile switches.
- Profile creation, activation, and listing.
- SMAPI log file import and basic diagnostic classification.
- Update check using allowed metadata flow only, with user-facing indication that downloads remain manual.
- Basic activity/error log for app actions.

## Major risks

- Mod packaging is inconsistent; many archives contain extra top-level folders, mixed content packs, or partial installs.
- Manifest metadata can be incomplete, stale, or missing, limiting conflict and dependency accuracy.
- Profile switching can be destructive if the active Mods directory is not treated transactionally.
- Symlink-heavy approaches may behave differently across filesystems or confuse users and future Windows support.
- Update checks may be rate-limited or constrained by what metadata sources are legitimately allowed.
- SMAPI log parsing rules can drift with SMAPI versions.
