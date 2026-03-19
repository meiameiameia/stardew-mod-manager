# Roadmap

## Product direction after `0.6.0`

The app is now a local-first Stardew Valley mod workflow manager with a sandbox-first safety model.

Its strongest lane is:

- safe local workflow
- dev-loop trust around sandbox launch, sync, promotion, and compare
- migration trust through local backup export, backup-bundle inspection, and restore/import planning

It is not trying to become, in the near term:

- a one-click downloader
- a broad profile or instance manager
- a broad shell-polish project divorced from workflow value

## Shipped through `0.6.0`

### Core workflow and safety baseline

Shipped:

- setup/config + inventory scan
- update awareness + guided manual remote-page flow
- package inspection/intake -> plan/review -> explicit execution
- install history + recovery derivation/review/execution
- guarded real-Mods writes with archive/recovery semantics

### Update-source intent and diagnostics

Shipped:

- typed update-source diagnostics
- persisted update-source intent overlay (`local/private`, `no-tracking`, `manual source association`)
- manual source association participation in update checks
- atomic app-state/history writes and explicit critical history-failure handling

### Daily-use ergonomics and sandbox dev loop

Shipped:

- session persistence ergonomics for practical setup/session fields
- sandbox-only launch (SMAPI with sandbox Mods path)
- explicit selected-mod `real -> sandbox` sync
- explicit selected-mod `sandbox -> real` promotion with preview/review
- archive-aware replace on live conflicts (no blind overwrite)
- partial-failure safety handling for promotion paths
- multi-zip batch inspection with per-package visibility
- explicit single-package staging (no opaque batch install)
- second watcher-path support feeding the same intake flow

### Compare and migration-trust baseline

Shipped:

- dedicated compare surface for configured `real Mods` vs `sandbox Mods`
- clear baseline categories:
  - only in real
  - only in sandbox
  - same version
  - version mismatch
  - ambiguous match for duplicate/unclear UniqueID grouping
- compare remains visibility-first in this stage (no compare-driven writes)
- explicit backup export baseline for local migration/recovery groundwork
- explicit read-only inspection of exported backup bundle folders
- manifest/version/item-status visibility before any restore behavior exists
- structural usability reporting for future restore/import work
- explicit read-only restore/import planning against the current local machine
- clear planning states for safe later vs needs review vs blocked
- no restore/apply behavior in this baseline

### Information architecture simplification (paused)

Implemented enough for now:

- bottom area is output-only
- setup moved into main workspace ownership
- duplicated detail scaffolding reduced

Still paused because workflow completion and trust are higher-value than more decomposition.

## Near-term priorities

### 1. Open-folder conveniences

- add narrow local convenience actions that reduce friction in everyday workflow
- prefer actions that support trust and orientation, such as opening the relevant mods/archive/export folders
- keep these conveniences explicit and local rather than automating decisions

### 2. Restore/import execution baseline

- add the first restore/apply path now that restore/import planning is visible and trustworthy
- keep execution explicit, reviewable, and non-destructive by default where possible
- preserve real-vs-sandbox safety semantics

Why this is next:

- export, inspection, and planning now exist as a coherent trust chain
- execution is the next product step that turns migration trust into practical recovery
- it should still follow smaller local ergonomics wins where those reduce setup friction without changing safety semantics

### 3. Steam prelaunch best-effort behavior

- support best-effort launch behavior that works with Steam ownership constraints without implying guaranteed automation
- keep launch intent explicit and sandbox-safe
- surface when fallback/manual launch is required

## Later or deferred

### Compare follow-up

- keep the shipped compare view readable and trustworthy as a first-class drift/orientation surface
- defer richer compare actions until safety semantics are explicitly designed
- no compare-driven bulk sync/promotion shortcuts yet

### Icon/taskbar refinement

- continue icon/taskbar polish only after higher-value workflow usability items above
- treat as quality polish, not a workflow blocker

### Public release hardening

- installer/signing/distribution hardening
- CI/release gating maturity
- migration discipline for broader audience rollout

### Provider-compliant automation (still constrained)

- official provider mechanisms only
- explicit user-owned auth
- no scraping, no premium bypass, no one-click install-from-search until explicitly approved

### Profile/instance systems

- remain outside near-term scope
- revisit only if the local workflow manager direction stops fitting the product

## Guardrails that remain non-negotiable

- preserve asymmetry: `real -> sandbox` sync vs managed `sandbox -> real` promotion
- no raw bidirectional mirroring
- no blind overwrite into real Mods
- no profile/instance broadening unless explicitly approved
