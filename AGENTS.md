# Agent operating contract

Read README.md, docs/agent-handoff.md, docs/implementation-contract.md and the acceptance
index before changes. If `.context/workspace.json` is present and access is authorized,
read the linked Notion specifications and plan. Narrative rationale belongs in Notion;
keep public API contracts, tests and concise runbooks here. Do not copy private pages
or their URLs, transcripts, business data, credentials or proprietary books into Git.

Use one Python 3.14 uv project and the existing lock. No subprojects, independent environments,
client ontology imports or overlapping database/dataframe stacks. Source models are canonical;
diagrams and graphs are disposable derived views. Keep identity distinct from display names.

Follow the five milestones in the handoff. A fixture passing a renderer is not a generated
projection. Distinguish schema validity, cross-model consistency, notation validity and
real-world correctness. Keep unknowns and manual activities explicit. No fabricated evidence.

Do not enable Delta/DataFusion native FFI under the present lock. Use the explicit-version
PyArrow adapter. Do not read latest table versions when resolving a published release.
Do not vacuum files referenced by retained release manifests. Never sync live stores.

Validate each changed contract with appropriate tests, then run the CI checks. Preserve
unrelated edits. Use focused branches/PRs after the initial scaffold. Record requirements,
checks, limitations and next handoff. Ask the owner only for material scope/architecture
changes, credentials or decisions not established in the accepted specifications.
