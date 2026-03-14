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

Promote update-source diagnostics below the UI and bind the Inventory surface to that typed contract.

That means:

- add typed update-source diagnostics in the domain/app/service layer
- bind the Inventory UI to that typed contract
- explicitly distinguish unsupported key format, missing key, missing remote link, provider-mapping failure, and metadata lookup failure
- eliminate UI-side reconstruction of source diagnostics from user-facing strings

## Next phase

### 6. Update Source Diagnostics Contract

Scope:

- promote update-source diagnostics into a typed contract
- keep user-facing update-check behavior read-only
- preserve current status/message behavior unless a small wording fix is required for correctness

Validation gate:

- update-source failure categories are testable below the UI
- Inventory diagnostics can stop being driven by message parsing in the following increment

Explicitly out of scope:

- metadata editing
- manual source association
- provider automation

### 7. Persistence and Release-Safety Foundations

Scope:

- atomic app-state and history writes
- honest handling of install/recovery history write failure
- platform-correct app-state storage behavior
- stronger persistence durability for the app's safety/reversibility promise

Validation gate:

- install and recovery history writes are crash-safer than direct overwrite
- critical history-recording failure is not silently swallowed in paths that claim reversibility
- state-file path behavior is appropriate for the supported desktop platform targets

Explicitly out of scope:

- database introduction
- installer/signing work
- broad release packaging

### 8A. Update Source Association and Local-Private State

Scope:

- add a durable app-level way to distinguish:
  - local/private mods
  - intentionally untracked mods
  - repairable remote-source problems

Validation gate:

- a repeated update check can preserve source-association intent without re-guessing from manifest metadata alone

Explicitly out of scope:

- automatic repair
- automatic downloads

### 8B. Update Source Repair UX

Scope:

- only after diagnostics and source-association state are reliable, add a narrow row-local repair flow for missing or broken update sources

Validation gate:

- a user can understand what is wrong with an update source and what, if anything, is fixable

Explicitly out of scope:

- automatic remote repair
- automatic downloads

## Later planned phases

### 9. Information Architecture Simplification

Planned audits:

1. duplicate-information / ownership audit
2. interaction-model / redesign-necessity audit

Entry criteria:

- update-source diagnostics are a typed contract
- current workflow surfaces are no longer changing every few days
- `Plan & Install` information ownership is stable enough to audit

### 10. Visual Polish and Release UX

Planned scope:

- visual hierarchy cleanup
- warning/disabled-state clarity
- progressive disclosure where the app still feels overly dense
- first-run and advanced-mode UX clarity

### 11. Public Release Hardening

Planned scope:

- packaging
- installer strategy
- code signing
- CI
- persistence migration discipline
- first-run/onboarding clarity

### 12. Provider-Compliant Automation

Planned scope:

- official provider mechanisms only
- user-owned auth
- no scraping
- no premium bypass
- no one-click install-from-search until explicitly designed and approved
- not a first-release requirement
