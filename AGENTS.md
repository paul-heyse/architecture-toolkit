# Agent operating contract

Read, in order:

1. `README.md`
2. `docs/implementation-contract.md`
3. `docs/contracts/core.md`
4. `docs/contracts/data.md`
5. `docs/contracts/projections.md`
6. `docs/agent-handoff.md`
7. `reference/requirements.json`

If `.context/workspace.json` is present and access is authorized, read the linked private
Notion specifications and current plan. Narrative rationale, research and decisions belong in
Notion. Git contains executable contracts, schemas, tests, concise runbooks and public references.
Do not commit private Notion URLs, transcripts, client data, credentials or proprietary sources.

Use one Python 3.14 uv project, one `pyproject.toml`, one `uv.lock` and one `.venv`.
Source/domain models are canonical. Arrow/Delta, NetworkX, generated notation, rendered artifacts
and the portal are derived representations. Stable identities are distinct from display names.

D-032 selects Pyrefly as the target type checker. The checked-in `pyproject.toml` currently uses
ty; treat repository state as executable truth until the migration lands. Do not silently change
architecture, dependency boundaries or qualification semantics while implementing a requirement.

Do not resolve published releases from implicit latest Delta versions. Do not enable native
Delta/DataFusion FFI under an incompatible lock. Do not vacuum versions referenced by retained
release manifests. Do not send confidential models to public render services or sync live stores.

A vendor smoke test is not a generated projection. Distinguish canonical validation, cross-model
semantics, notation/schema validity, renderer validity and real-world correctness. Preserve
unknowns, evidence gaps and manual activities. Do not fabricate facts to satisfy structural rules.

Each PR must identify requirement IDs, executable checks, remaining gaps and material design
questions. Preserve unrelated edits. Ask the owner only for material architecture/scope changes,
credentials or decisions not already established by the accepted specifications.
