# Stage Plan

## Stage 1

### Scope

- Repository setup confirmation
- app configuration model
- path selection and validation logic
- local mod scan of a chosen Mods directory
- manifest parsing and inventory listing data model

### Validation gate

- Can configure game path, active Mods path, and app data root
- Can scan a real sample Mods directory deterministically
- Produces consistent inventory records and parse warnings

### Explicitly out of scope

- installs
- rollback
- profiles
- remote metadata checks
- SMAPI diagnostics UI beyond placeholders

## Stage 2

### Scope

- duplicate detection
- dependency graph extraction from manifests
- missing dependency and obvious version mismatch reporting

### Validation gate

- Test fixtures cover duplicate IDs, missing dependencies, and malformed manifests
- Findings are reproducible across rescans

### Explicitly out of scope

- automatic conflict resolution
- install pipeline
- profile switching
- remote update lookups

## Stage 3

### Scope

- local archive import
- staging extraction
- installability validation
- safe install execution for local zip files

### Validation gate

- Can install from supported local archives without partial target corruption in normal conditions
- Unsafe archive paths and malformed packages are rejected

### Explicitly out of scope

- remote downloads
- auto-update install
- rollback UI beyond basic operation history

## Stage 4

### Scope

- snapshot creation
- rollback execution
- operation history
- archive retention model definition

### Validation gate

- A completed install or remove operation can be rolled back from created snapshot data
- Failure paths leave enough metadata for manual recovery

### Explicitly out of scope

- aggressive storage optimization
- deduplicated snapshot storage
- advanced retention automation

## Stage 5

### Scope

- profile create/list/activate
- profile materialization into live Mods directory
- profile diff preview before switch

### Validation gate

- Profile switch is deterministic and leaves the live Mods directory matching the selected profile
- Rollback still works after a profile switch operation

### Explicitly out of scope

- symlink-based profiles
- cloud sync
- per-save automatic profile switching

## Stage 6

### Scope

- allowed metadata-based update checks
- SMAPI log import and diagnostic classification
- basic release hardening and packaging assessment

### Validation gate

- Update check does not download files and only uses approved metadata flow
- SMAPI log parser identifies a useful first set of actionable issue categories
- Packaging path for Linux is documented with known gaps

### Explicitly out of scope

- browser automation
- scraping
- premium-flow bypasses
- rich UI polish
- generalized plugin system
