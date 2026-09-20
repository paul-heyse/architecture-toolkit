"""Assert reference/plan-waves.json partitions the acceptance index exactly once.

Standard library only (DATA-32). Requirement definitions are static contracts; this script
checks that every one of them is scheduled, not that any of them passes.
"""

from __future__ import annotations

import re
from pathlib import Path

from _common import ROOT, load_json, report

HANDOFF = ROOT / "docs" / "agent-handoff.md"

WAVE_ID = re.compile(r"^W\d+[a-z]?$")
RANGE = re.compile(r"([A-Z]+)-(\d+)\.\.(?:[A-Z]+-)?(\d+)$")
FAMILIES = ("CORE", "DATA", "PROJ")

MILESTONE_HEADING = re.compile(r"^## (M\d) ", re.MULTILINE)
INPUTS_BLOCK = re.compile(r"^### Inputs\n(.*?)(?=^#{2,3} )", re.MULTILINE | re.DOTALL)
ID_TOKEN = re.compile(r"(?:CORE|DATA|PROJ)-\d+(?:\.\.(?:(?:CORE|DATA|PROJ)-)?\d+)?")


def milestone_inputs(text: str) -> dict[str, set[str]]:
    """Parse the read scope of each milestone from the '### Inputs' blocks of the handoff.

    Parsed rather than transcribed so an edit to the handoff cannot silently drift from this
    check. Milestone inheritance ("M1;") is deliberately not expanded: only identifiers named
    in a milestone's own Inputs block count as its read scope.
    """
    scope: dict[str, set[str]] = {}
    headings = list(MILESTONE_HEADING.finditer(text))
    for position, heading in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
        section = text[heading.start() : end]
        block = INPUTS_BLOCK.search(section)
        ids: set[str] = set()
        if block:
            for token in ID_TOKEN.findall(block.group(1)):
                ids.update(expand(token))
        scope[heading.group(1)] = ids
    return scope


def expand(spec: str) -> list[str]:
    """Expand a comma-separated spec of bare IDs and FAMILY-nn..nn ranges."""
    out: list[str] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        match = RANGE.match(token)
        if match:
            family, start, end = match.group(1), int(match.group(2)), int(match.group(3))
            out.extend(f"{family}-{n:02d}" for n in range(start, end + 1))
        else:
            out.append(token)
    return out


def normalize(text: str) -> str:
    return " ".join(text.split())


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    index = load_json("reference/requirements.json")
    plan = load_json("reference/plan-waves.json")
    schema = load_json("schemas/requirements.schema.json")

    known = {entry["id"] for entry in index["requirements"]}
    waves = plan["waves"]

    # The declared requirement count lives in the schema, not in this script.
    bounds = schema["properties"]["requirements"]
    if bounds.get("minItems") != bounds.get("maxItems"):
        errors.append("SCHEMA_BOUNDS: requirements minItems and maxItems disagree")
    elif bounds.get("minItems") != len(known):
        errors.append(
            f"SCHEMA_BOUNDS: schema declares {bounds.get('minItems')} requirements, "
            f"index holds {len(known)}"
        )

    # Partition.
    owner: dict[str, str] = {}
    for wave in waves:
        wid = wave["wave_id"]
        seen: set[str] = set()
        for rid in wave["requirements"]:
            if rid not in known:
                errors.append(f"UNKNOWN_REQUIREMENT: {rid} in {wid} is not in the acceptance index")
            if rid in seen:
                errors.append(f"DOUBLE_ASSIGNED: {rid} listed twice within {wid}")
            if rid in owner:
                errors.append(f"DOUBLE_ASSIGNED: {rid} owned by both {owner[rid]} and {wid}")
            seen.add(rid)
            owner.setdefault(rid, wid)

    for rid in sorted(known - set(owner)):
        errors.append(f"UNASSIGNED: {rid} is owned by no wave")

    for family in FAMILIES:
        expected = sum(1 for rid in known if rid.startswith(f"{family}-"))
        actual = sum(1 for rid in owner if rid.startswith(f"{family}-"))
        if expected != actual:
            errors.append(f"FAMILY_COUNT: {family} assigned {actual}, index holds {expected}")

    # Milestone read scope, parsed from the handoff rather than transcribed here.
    inputs = milestone_inputs(HANDOFF.read_text())

    # Ordering.
    order = {wave["wave_id"]: position for position, wave in enumerate(waves)}
    if len(order) != len(waves):
        errors.append("DUPLICATE_WAVE_ID: wave_id values are not unique")
    last_milestone = 0
    for position, wave in enumerate(waves):
        wid = wave["wave_id"]
        if not WAVE_ID.match(wid):
            errors.append(f"MALFORMED_WAVE_ID: {wid}")
        milestone = wave["milestone"]
        if milestone not in inputs:
            errors.append(f"UNKNOWN_MILESTONE: {wid} maps to {milestone}")
            continue
        number = int(milestone[1:])
        if number < last_milestone:
            errors.append(f"MILESTONE_ORDER: {wid} maps to {milestone} after M{last_milestone}")
        last_milestone = max(last_milestone, number)
        for dependency in wave["depends_on"]:
            if dependency not in order:
                errors.append(f"UNKNOWN_DEPENDENCY: {wid} depends on {dependency}")
            elif order[dependency] >= position:
                errors.append(f"FORWARD_DEPENDENCY: {wid} depends on later wave {dependency}")

    # Every identifier must sit in a milestone that reads it, unless an amendment records it.
    amended: set[str] = set()
    for amendment in plan["milestone_amendments"]:
        amended.update(amendment["covers"])
    for wave in waves:
        scope = inputs.get(wave["milestone"], set())
        for rid in wave["requirements"]:
            if rid not in scope and rid not in amended:
                errors.append(
                    f"UNSCHEDULED_IN_MILESTONE: {rid} sits in {wave['wave_id']} "
                    f"({wave['milestone']}) but is in no milestone input list and no amendment"
                )

    # Gate integrity: a quoted gate must still exist in the document it cites.
    for wave in waves:
        gate = wave["hard_gate"]
        source = ROOT / gate["source"]
        if not source.is_file():
            errors.append(f"MISSING_GATE_SOURCE: {wave['wave_id']} cites {gate['source']}")
            continue
        if normalize(gate["statement"]) not in normalize(source.read_text()):
            errors.append(
                f"ORPHANED_GATE: {wave['wave_id']} gate text is absent from {gate['source']}"
            )

    # Plan documents must exist and mention the identifiers they own.
    for wave in waves:
        doc = ROOT / wave["plan_doc"]
        if not doc.is_file():
            errors.append(f"MISSING_PLAN_DOC: {wave['plan_doc']}")
            continue
        if not Path(wave["plan_doc"]).name.startswith(wave["wave_id"].lower()):
            errors.append(f"PLAN_DOC_NAME: {wave['plan_doc']} does not start with wave id")
        body = doc.read_text()
        absent = [rid for rid in wave["requirements"] if rid not in body]
        if absent:
            errors.append(
                f"PLAN_DOC_COVERAGE: {wave['plan_doc']} never mentions {', '.join(absent)}"
            )

    index_doc = ROOT / "docs" / "plans" / "index.md"
    if not index_doc.is_file():
        errors.append("MISSING_PLAN_INDEX: docs/plans/index.md")
    else:
        body = index_doc.read_text()
        for wave in waves:
            if wave["wave_id"] not in body:
                errors.append(f"PLAN_INDEX: docs/plans/index.md omits {wave['wave_id']}")

    # Referential integrity of the supporting lists.
    by_wave = {wave["wave_id"]: set(wave["requirements"]) for wave in waves}
    for wave in waves:
        for rid in wave["policy_only"]:
            if rid not in by_wave[wave["wave_id"]]:
                errors.append(f"POLICY_ONLY: {rid} is not owned by {wave['wave_id']}")
    for entry in plan["deferred_acceptance"]:
        if entry["id"] not in by_wave.get(entry["wave"], set()):
            errors.append(f"DEFERRED: {entry['id']} is not owned by {entry['wave']}")
        elif order.get(entry["enforced_from"], -1) <= order.get(entry["wave"], 0):
            errors.append(f"DEFERRED: {entry['id']} is not enforced after {entry['wave']}")
    for entry in plan["evidence_extensions"]:
        if owner.get(entry["id"]) != entry["owned_by"]:
            errors.append(
                f"EVIDENCE_EXTENSION: {entry['id']} is owned by "
                f"{owner.get(entry['id'])}, not {entry['owned_by']}"
            )
        for later in entry["extended_by"]:
            if later not in order:
                errors.append(f"EVIDENCE_EXTENSION: {entry['id']} names unknown wave {later}")

    # A wave declares the families it legitimately spans; anything outside needs a rationale.
    declared = {entry["id"] for entry in plan["cross_family_placements"]}
    for wave in waves:
        spanned = set(wave["families"])
        if unknown := spanned - set(FAMILIES):
            errors.append(f"UNKNOWN_FAMILY: {wave['wave_id']} declares {sorted(unknown)}")
        used = {rid.split("-")[0] for rid in wave["requirements"]}
        if unused := spanned - used:
            warnings.append(
                f"UNUSED_FAMILY: {wave['wave_id']} declares {sorted(unused)} but owns none"
            )
        for rid in wave["requirements"]:
            if rid.split("-")[0] not in spanned and rid not in declared:
                errors.append(
                    f"UNDECLARED_CROSS_FAMILY: {rid} sits in {wave['wave_id']}, which declares "
                    f"{sorted(spanned)}, and has no cross_family_placements rationale"
                )

    for wave in waves:
        wid, milestone = wave["wave_id"], wave["milestone"]
        print(f"{wid:>4}  {milestone}  {len(wave['requirements']):>3}  {wave['title']}")
    print(f"{'':>4}  --  {len(owner):>3}  requirements assigned across {len(waves)} waves")

    report("Plan coverage", errors, warnings)


if __name__ == "__main__":
    main()
