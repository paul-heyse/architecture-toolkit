"""Offline vendor-tool smoke checks on explicitly synthetic, handwritten fixtures."""

import json
import shutil
import subprocess
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
OUTPUT = ROOT / ".runtime" / "toolchain-qualification"


def run(*args: str) -> None:
    subprocess.run(args, check=True, cwd=ROOT, timeout=120)


def main() -> None:
    java = (TOOLS / "java-path.txt").read_text().strip()
    if not shutil.which("dot"):
        raise SystemExit("Graphviz dot is required; see docs/toolchain.md")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run(java, "-version")
    run("dot", "-V")
    fixture = ROOT / "examples/toolchain"
    run(
        java,
        "-Djava.awt.headless=true",
        "-jar",
        str(TOOLS / "plantuml.jar"),
        "-failfast2",
        "-tsvg",
        "-o",
        str(OUTPUT),
        str(fixture / "architecture.puml"),
    )
    svg = OUTPUT / "architecture.svg"
    if not svg.exists() or b"<svg" not in svg.read_bytes():
        raise RuntimeError("PlantUML produced no SVG")
    for command in ("validate", "export"):
        args = [
            java,
            "-jar",
            str(TOOLS / "structurizr.war"),
            command,
            "-workspace",
            str(fixture / "workspace.dsl"),
        ]
        if command == "export":
            args += ["-format", "plantuml", "-output", str(OUTPUT / "c4")]
        run(*args)
    if not list((OUTPUT / "c4").glob("*.puml")):
        raise RuntimeError("Structurizr produced no PlantUML views")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    xsd = etree.XMLSchema(etree.parse(str(TOOLS / "bpmn/BPMN20.xsd"), parser))
    xsd.assertValid(etree.parse(str(fixture / "process.bpmn"), parser))
    report = {
        "plantuml_archimate_svg": "passed",
        "structurizr_validate_export": "passed",
        "bpmn_xml_schema": "passed",
        "bpmn_browser_render": "not_qualified",
        "canonical_model_projections": "not_implemented",
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
