# Roadmap

## Completed or effectively closed

### 1. Core Workflow Foundation

Implemented:

- configuration and scan path setup
- local mod inventory scan
- duplicate and dependency visibility
- package inspection and downloads intake
- install planning and execution review
- sandbox install execution
- guarded real-Mods execution
- install history
- recovery derivation, review, and execution
- recovery history with stable IDs

### 2. Guided Manual Update Flow

Implemented:

- update check awareness flow
- selected-row remote-page handoff
- intake staging into `Plan & Install`
- local workflow output in owning tabs
- install-to-recovery continuity

### 3. Managed Live Mods Safety Baseline

Implemented baseline:

- persistent destination safety context
- explicit confirmation for real-Mods execution
- stronger live destination messaging before execution
- constrained-height resilience in `Plan & Install`

### 4. History / Recovery UX Baseline

Implemented baseline:

- readable recovery selector
- newest-first recovery record display
- recovery summary cues
- recovery filtering
- recovery execution path with status continuity

## Current phase

### 5. Dependency / Conflict / Update Ergonomics

Completed inside this phase so far:

- inventory update-actionability filter
- selected-row update guidance
- selected-row remote action enablement
- `Plan & Install` review summary, explanation, and facts
- initial selected-row update-source diagnostics surface

### Current priority inside this phase

Promote update-source diagnostics below the UI so the Inventory diagnostics surface stops inferring structured meaning from user-facing strings.

That means:

- add typed update-source diagnostics in the domain/app/service layer
- bind the Inventory UI to that typed contract
- explicitly distinguish unsupported key format, missing key, missing remote link, provider-mapping failure, and metadata lookup failure

## Next phase

### 6A. Update Source Diagnostics Contract

Scope:

- promote update-source diagnostics into a typed contract
- remove UI-side string reconstruction for diagnostics
- keep this phase read-only from the user's perspective

Validation gate:

- update-source failure categories are testable below the UI
- Inventory diagnostics are driven by structured state, not message parsing

Explicitly out of scope:

- metadata editing
- manual source association
- provider automation

### 6B. Update Source Repair UX

Scope:

- only after diagnostics are reliable, design whether users need repair actions for unsupported or missing update sources

Validation gate:

- a user can understand what is wrong with an update source and what, if anything, is fixable

Explicitly out of scope:

- automatic remote repair
- automatic downloads

## Later planned phases

### 7. UI/UX Consolidation and Release Readiness

Planned audits:

1. duplicate-information / ownership audit
2. redesign-necessity / interaction audit
3. visual feedback / polish audit

Entry criteria:

- update-source diagnostics are a typed contract
- current workflow surfaces are no longer changing every few days
- `Plan & Install` information ownership is stable enough to audit

### 8. Public Release Hardening

Planned scope:

- packaging
- installer strategy
- code signing
- CI
- persistence migration discipline
- first-run/onboarding clarity

### 9. Provider-Compliant Automation

Planned scope:

- official provider mechanisms only
- user-owned auth
- no scraping
- no premium bypass
- no one-click install-from-search until explicitly designed and approved
