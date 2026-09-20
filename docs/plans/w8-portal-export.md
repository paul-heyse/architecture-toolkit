# Wave 8 — Offline portal and self-contained milestone export

> Milestone: M5 · Requirements: PROJ-35..PROJ-41 · Depends on: W7b

## Purpose

Make a release consumable without a network. This wave generates the offline MkDocs portal with
stable routes derived from canonical IDs, integrates the rich Structurizr C4 and qualified BPMN
views as read-only surfaces, completes the vendor notice and provenance inventory, and fills in the
`outputs/` section of the milestone archive W4 already ships.

The portal is a generated consumption surface. It is never an editable architecture source.

## Contract references

- [projections.md § Portal](../contracts/projections.md) — PROJ-35..PROJ-38.
- [projections.md § Kroki](../contracts/projections.md) — PROJ-39.
- [projections.md § Rendering and provenance](../contracts/projections.md) — PROJ-40, PROJ-41.
- [data.md § Retention and milestone archives](../contracts/data.md) — DATA-25, whose outputs
  section this wave fills.
- Record `ARCH-TOOL-PROJ-001` §9–11 and §14.

## Work items

1. **Material for MkDocs, only after qualification** (PROJ-35). Target Material 9.x as the default
   theme, added to the `docs` group at an exact pinned version after qualification. The current
   lock has plain `mkdocs>=1.6.1` and no theme. If qualification fails, the default theme stays and
   PROJ-35 records the reason — do not add an unpinned dependency.
2. **Offline-first bundle** (PROJ-36). Self-contained static site: locally hosted assets, no
   analytics, no comments, no external fonts or runtime assets, working offline search, portable as
   a directory or zip. Never requires GitHub Pages or any hosted service. Strict build for release
   artifacts, which the repository already sets.
3. **Network-absence assertion** (PROJ-36). A test that scans the built site for external hosts in
   `src`, `href`, `url()` and font declarations, and fails on any. This is the check that makes the
   hard gate real rather than aspirational.
4. **Generated routes** (PROJ-37). Stable routes for elements, relationships where warranted,
   workflows, systems, interfaces, information schemas, views, releases and change sets, and
   validation and qualification summaries. Route identity derives from canonical IDs or
   deterministic slugs tied to them, so a display-name change does not move a page.
5. **Cross-links** (PROJ-37). Detail page to containing views; view page to source objects; system
   to interfaces, workflows and data; release to changed objects and views; traceability result to
   the evidence or reference record.
6. **Rich C4 integration** (PROJ-38). Embed or link the generated Structurizr static export as a
   release artifact or subsite. Its own navigation metadata is not source-of-truth content.
7. **Interactive BPMN** (PROJ-38). If the W7b bpmn-js qualification passed, bundle it locally,
   render the generated BPMN XML, fit the viewport, preserve the bpmn.io watermark and make no
   remote calls. If it did not pass, the portal links the static artifact instead.
8. **Search and tags** (PROJ-36). Index only generated release content intended for the portal.
   Tags may cover object type, layer, status, qualification state and ownership. Search and tag
   indexes are publication derivatives, excluded from semantic identity.
9. **Kroki stays deferred** (PROJ-39). No Kroki in the baseline. A guard test asserts no Kroki host
   appears in any generated asset or configuration; the PROJ-36 network assertion covers the rest.
   If it is ever enabled it must be local, pinned by image digest, restricted, with remote includes
   disabled and output compared against direct-renderer qualification. No public Kroki endpoint
   ever processes a confidential model.
10. **Vendor notice and provenance inventory** (PROJ-40). Machine- and human-readable, recording
    version, checksum, licence and security configuration for the PlantUML MIT distribution,
    Structurizr, the Temurin JRE, Graphviz, the bpmn-js family, Material for MkDocs, optional Kroki
    and the standards schemas as their terms permit. W7b wrote a provenance row at each first
    vendor use, so this is a completeness check over existing rows plus the licence text in
    `THIRD_PARTY_NOTICES.md`.
11. **Release artifact pinning** (PROJ-41). Populate the manifest fields W4 reserved: view
    definition digests, mapping profile versions, projection artifact digests, layout and render
    digests where the release policy preserves them, validation artifact reports, and the portal
    bundle digest with its toolchain provenance. Semantic release identity still excludes renderer
    bytes unless the policy explicitly treats a rendered artifact as a preserved deliverable.
12. **Complete the milestone export** (DATA-25, owned by W4). Fill the `outputs/` section of the
    archive writer with generated projections, renders and the portal bundle. The format does not
    change.
13. **Complete the `output` CLI verb** (DATA-38, owned by W6). Replace the typed not-implemented
    diagnostic with the real implementation.

## Hard gate

> No external runtime assets/network calls are required for the canonical offline bundle.
> — [agent handoff](../agent-handoff.md), M5 hard gates

Verified by building the bundle, scanning it for external hosts, and opening it from a directory
with networking unavailable. Also required: live stores are never synced.

## Policy only

PROJ-39 — Kroki is a documented deferral with a guard test. No feature is built for it.

## Executable checks

```sh
uv run --group docs mkdocs build --strict
uv run pytest -m "interop or vendor or qualification"
uv run architecture output --release <release>
uv run pyrefly check
```

## Evidence

Requirement markers throughout. The load-bearing artifacts are the offline-bundle network scan
(PROJ-36), the no-broken-internal-link strict build (PROJ-37), and the completed vendor notice
inventory (PROJ-40).

## Risks and open questions

- **Material for MkDocs pulls a dependency tree** and its offline plugin may be distribution-gated.
  Qualify the exact version before adding it; a failed qualification is an acceptable outcome that
  PROJ-35 records.
- **Offline search** typically ships a prebuilt index. Confirm the index is generated locally and
  loads from a `file://` origin, which is stricter than serving over HTTP.
- **Portal scale** is untested. Per-element pages for a large model may make a strict build slow;
  measure before adding pagination or filtering.
- **Preserved-deliverable policy** — which rendered artifacts count as part of release identity —
  is an owner decision that PROJ-41 encodes.
