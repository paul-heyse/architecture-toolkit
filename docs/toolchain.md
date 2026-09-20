# Toolchain

## Python

Python 3.14.7 and uv 0.12.7; one pyproject, lockfile and environment. Core libraries are Pydantic,
PyArrow, deltalake, DataFusion, NetworkX, ruamel.yaml, Jinja2 and lxml. Dev tools are pytest,
Hypothesis, ty and Ruff. MkDocs is a dependency group in the same project, not a second app.
`uv.lock` is the exact dependency authority. Use `uv sync --locked --all-groups`.

## Vendor tools

Run `uv run python scripts/bootstrap_tools.py`. `tools.lock.json` pins HTTPS source URLs,
versions and SHA256 checksums. Downloads stay in ignored `.tools/`; JRE extraction preserves
vendor notices and uses Python's safe tar filter. The bootstrap does not start services or
modify system Java. Initial installation needs internet; the qualification script runs locally.

| Tool | Pin | Use |
| --- | --- | --- |
| Temurin JRE | 21.0.12.1+1 | Local Java runtime, macOS ARM64 / Linux x86-64 |
| PlantUML MIT build | 1.2026.8 | ArchiMate, selected UML/ERD renderers |
| Structurizr unified WAR | 2026.06.28 | Free validate/export commands for generated C4 DSL |
| OMG BPMN XSD set | BPMN 2.0.2, 20100501 files | Local XML Schema validation |
| Graphviz | Host package; version recorded by qualification | PlantUML graph layout |

Install Graphviz with `brew install graphviz` on macOS or `sudo apt-get install graphviz` on
Ubuntu. The application bootstrap intentionally does not request system privileges. Graphviz
is not locked across platforms yet: byte-identical SVGs are not guaranteed. Exact render
reproducibility needs a future pinned runtime image and recorded fonts/layout versions.

The Structurizr pin follows the official binary documentation, not a claim that it is the
latest source release. The unified distribution replaces the old CLI/Lite setup. Only free
validate/export commands are used. No server, account or paid license is provisioned.

GitHub release digests verify the JRE and PlantUML downloads. Structurizr and OMG hashes were
recorded from their official HTTPS distributions on 2026-09-20; they are reproducibility pins,
not independently signed upstream attestations. Review URL, license and checksums on upgrades.

## BPMN rendering and optional Kroki

The scaffold includes an XSD-valid synthetic BPMN file with diagram coordinates. Its browser
render is not yet qualified. Use bpmn-js through a locally hosted vendor bundle or a locally
pinned Kroki BPMN companion in milestone 4. Do not add a second Node application project just
to wrap a renderer. Record a specific version/digest, notices and an SVG import/render test
before enabling that adapter. Docker was not running on the setup host; no daemon was started.
Public Kroki endpoints are not a default data destination.

## Upgrade process

Update pins deliberately, download from official sources, verify upstream or newly reviewed
hashes, run both platform CI jobs and vendor qualification, then record changed capabilities
and limitations. Do not check binaries, extracted tools or caches into Git.
