"""Structured, secure, canonical standards XML (CORE-39..CORE-43).

lxml owns BPMN and ArchiMate Exchange XML. Jinja does not touch either — CORE-38 — and the
separation is structural rather than remembered: this module builds trees with `QName` and
`ElementMaker`, and there is no string to interpolate into.

**`no_network=True` is not a refusal.** This is the finding the whole resolver design rests on,
measured both ways against libxml2 2.14.6. A schema whose `xsd:import` names a URL that cannot be
fetched is a *silent warning* when the imported namespace is unused, and a *fatal parse error*
when it is used. Neither of those says "this was not the schema we pinned". Only a resolver that
raises does — which is exactly what CORE-41 asks for, and why `no_network` is a second line rather
than the mechanism.

`archimate3_Model.xsd` makes the point concrete: it imports `http://www.w3.org/2001/xml.xsd`, so
without a resolver serving pinned bytes it does not build at all.

**Two parsers, because the resolver is asked about the document too.** lxml calls the resolver for
every URL the parser loads, the top-level document included — so a parser whose resolver refuses
everything unpinned refuses to parse an ordinary instance document. `schema_parser` carries the
pinned resolver and is used only to load schemas; `instance_parser` carries none and is used for
everything else. Both set the same five security flags explicitly.

**C14N 2.0 with `strip_text`, pinned deliberately.** CORE-43 wants formatting-only XML changes not
to masquerade as semantic changes, and the obvious readings do not deliver it: measured on one
document serialized flat and pretty-printed, `method="c14n"` and plain `method="c14n2"` both give
*different* digests, because indentation survives as text nodes. `c14n2` with `strip_text=True`
gives the same digest and still preserves meaningful text — it trims leading and trailing
whitespace in a text node, it does not discard content. The version is recorded on the artifact
because these digests become durable at W8.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Final

from lxml import etree
from lxml.builder import ElementMaker

from architecture_toolkit.domain.identifiers import Digest
from architecture_toolkit.domain.source import SourceLocation
from architecture_toolkit.projections.errors import ProjectionError
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.taxonomy import Severity

__all__ = [
    "C14N_VERSION",
    "NAMESPACES",
    "PINNED_PREFIX",
    "XML_PREIMAGE",
    "PinnedSchemas",
    "SchemaValidator",
    "UnpinnedSchemaError",
    "XmlDigests",
    "instance_parser",
    "maker",
    "qname",
    "schema_parser",
    "xml_digests",
]


class UnpinnedSchemaError(ProjectionError):
    """A schema reference that is not in the reviewed local set (CORE-41).

    Not a `Diagnostic`. A diagnostic says something about the model; this says the validation was
    about to be performed against bytes nobody reviewed, which makes its result meaningless rather
    than negative.
    """


NAMESPACES: Final[Mapping[str, str]] = MappingProxyType(
    {
        # BPMN 2.0.2. The OMG's own version skew is preserved rather than corrected: the schema
        # files are published under `/20100501/` and declare `20100524` namespaces.
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        # ArchiMate Exchange. The 3.1 schema set serves both ArchiMate 3.1 and 3.2, and its
        # target namespace says 3.0 — again the publisher's, not ours to renumber.
        "archimate": "http://www.opengroup.org/xsd/archimate/3.0/",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xml": "http://www.w3.org/XML/1998/namespace",
    }
)
"""One registry, so a prefix means one thing everywhere (CORE-39).

Generators take their `ElementMaker` from `maker()` rather than declaring a namespace inline. A
second spelling of a namespace URI is the defect this prevents: the document would still be
well-formed, would still validate if the prefix bound correctly, and would carry element names
that no XPath assertion written against the registry could find.
"""

XML_PREIMAGE: Final[str] = "architecture-toolkit/xml-canonical/v1\n"
"""Prefixed like every other digest here, so two digest kinds cannot collide."""

C14N_VERSION: Final[str] = "c14n2-strip-text"
"""Which canonicalization produced a canonical digest. Recorded on the artifact, not assumed.

lxml offers C14N 1.0 and 2.0 and they differ in ways that change digests — 2.0 drops namespace
declarations nobody uses, 1.0 keeps them — so a digest that did not say which it used would be
uncheckable the first time the choice was revisited.
"""


def _secure_parser() -> etree.XMLParser:
    """The CORE-40 baseline, spelled once (`no_network`, `load_dtd`, `resolve_entities`,
    `huge_tree`, `recover`).

    All five are explicit even where they match lxml's current default, because a default is a
    fact about the installed version and this is a claim about the toolkit.
    `rules/secure-xml-parser.yml` refuses the unsafe spelling of each, including `recover=True`.

    One function rather than a flags mapping spread into two constructors: a `**mapping` spread
    is unchecked, so a typo in a key would silently construct a parser with a default the caller
    believed it had overridden — which is the whole failure mode this baseline exists to prevent.
    """
    return etree.XMLParser(
        no_network=True,
        load_dtd=False,
        resolve_entities=False,
        huge_tree=False,
        recover=False,
    )


_XSD: Final[str] = "http://www.w3.org/2001/XMLSchema"
"""The schema-of-schemas namespace, for finding `import`, `include` and `redefine`."""

PINNED_PREFIX: Final[str] = "pinned:///"
"""Base URI for schema bytes served from memory, so a relative reference inside one resolves back
through the resolver rather than against a filesystem path that may not exist."""


def qname(prefix: str, local: str) -> etree.QName:
    """A namespaced name from the registry. `KeyError` for a prefix nobody declared."""
    return etree.QName(NAMESPACES[prefix], local)


def maker(prefix: str, *, nsmap: Sequence[str] = ()) -> ElementMaker:
    """An `ElementMaker` bound to one registered namespace (CORE-39).

    `nsmap` names the other prefixes the document will use, so they are declared once on the root
    rather than repeated on every element that happens to need one first.
    """
    declared = {name: NAMESPACES[name] for name in (prefix, *nsmap)}
    return ElementMaker(namespace=NAMESPACES[prefix], nsmap=declared)


def instance_parser() -> etree.XMLParser:
    """For generated and received documents. No resolver: an instance references nothing."""
    return _secure_parser()


@dataclass(frozen=True, slots=True)
class PinnedSchemas:
    """The reviewed local schema set a validator may resolve from (CORE-41).

    Constructed from explicit paths and digests rather than from a repository layout. `src/` does
    not know where `.tools/` is, and should not: a toolkit installed as a wheel has no repository
    around it, and a caller that knows where the vendored files are can say so.
    """

    files: Mapping[str, Path]
    """Resolved absolute path by file name, e.g. `BPMN20.xsd`."""

    digests: Mapping[str, str]
    """Expected bare sha256 hex by the same file name, as `tools.lock.json` records it."""

    aliases: Mapping[str, str] = MappingProxyType({})
    """Absolute URIs a schema may import, mapped to a file name in `files`.

    `archimate3_Model.xsd` imports `http://www.w3.org/2001/xml.xsd`, and the W3C serves that under
    both `http` and `https`, so both spellings map to the one pinned copy.
    """

    def name_for(self, system_url: str) -> str:
        """Which pinned file a reference names, or `UnpinnedSchemaError`."""
        if system_url in self.aliases:
            return self.aliases[system_url]
        name = system_url.rsplit("/", 1)[-1]
        if name not in self.files:
            message = (
                f"schema reference {system_url!r} is not in the reviewed local set "
                f"{sorted(self.files)}; resolving it would validate against unreviewed bytes"
            )
            raise UnpinnedSchemaError(message)
        return name

    def closure(self, entry: str) -> tuple[str, ...]:
        """Every pinned file reachable from `entry`, refusing any reference that is not pinned.

        Run **before** `XMLSchema` is constructed, and that ordering is the point. lxml converts
        an exception raised inside a resolver during schema construction into an
        `XMLSchemaParseError` whose message is "Failed to parse the XML resource <url>" —
        measured. That is loud, but it cannot distinguish "this reference is not in the reviewed
        set" from "the network is down", and CORE-41 is about the first. Walking the references
        first means the refusal names the referring file and the reference, as a typed error.

        The resolver stays as the second line: it is what stops a reference this walk did not see
        — one synthesised by libxml2, or a schema edited between the walk and the build.
        """
        seen: list[str] = []
        queue = [entry]
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.append(name)
            document = etree.fromstring(self.read(name), _secure_parser())
            for reference in document.iterfind(f".//{{{_XSD}}}*[@schemaLocation]"):
                location = reference.get("schemaLocation")
                if location is None:  # pragma: no cover - the predicate selected on it
                    continue
                try:
                    queue.append(self.name_for(location))
                except UnpinnedSchemaError as unpinned:
                    message = f"{name} references {location!r}, which is not pinned"
                    raise UnpinnedSchemaError(message) from unpinned
        return tuple(sorted(seen))

    def read(self, name: str) -> bytes:
        """The pinned bytes, checked against the recorded digest on every read."""
        payload = self.files[name].read_bytes()
        observed = sha256(payload).hexdigest()
        if observed != self.digests[name]:
            message = (
                f"pinned schema {name} hashes to {observed}, not the recorded "
                f"{self.digests[name]}; the vendored copy has changed"
            )
            raise UnpinnedSchemaError(message)
        return payload


class _PinnedResolver(etree.Resolver):
    """Serves exactly the pinned set, from memory, and raises for anything else."""

    def __init__(self, pinned: PinnedSchemas) -> None:
        super().__init__()
        self._pinned = pinned

    # pyrefly: ignore[bad-override]
    # `Resolver.resolve` is declared as returning `_InputDocument | None`, lxml's opaque resolver
    # result. `types-lxml` marks that class `@type_check_only` and does not re-export it from
    # `lxml.etree` — only `Resolver` itself is exported — so the return type of the method we are
    # required to override cannot be named without importing `lxml.etree._docloader`, a private
    # module this repo has rules against reaching into. `object` is the honest alternative and an
    # override may not widen a return type, hence the narrowest possible suppression (CORE-60).
    def resolve(self, system_url: str | None, public_id: str | None, context: object, /) -> object:
        del public_id
        if system_url is None:  # pragma: no cover - lxml always supplies one here
            message = "a schema reference with no system URL cannot be pinned"
            raise UnpinnedSchemaError(message)
        name = self._pinned.name_for(system_url)
        return self.resolve_string(self._pinned.read(name), context, base_url=PINNED_PREFIX)


def schema_parser(pinned: PinnedSchemas) -> etree.XMLParser:
    """For schema documents only. Refuses any reference outside the pinned set."""
    parser = _secure_parser()
    parser.resolvers.add(_PinnedResolver(pinned))
    return parser


@dataclass(frozen=True, slots=True)
class XmlDigests:
    """Both identities CORE-43 asks for, and which canonicalization produced the second."""

    literal: Digest
    canonical: Digest
    c14n_version: str = C14N_VERSION


def xml_digests(element: etree._Element) -> XmlDigests:
    """The literal serialization digest and the canonical one (CORE-43).

    The literal digest is over the bytes actually written, so a reader can check the file in front
    of them. The canonical digest is over C14N 2.0 with text trimmed, so pretty-printing — which
    `projections.md` calls presentation — does not move it.
    """
    literal = etree.tostring(element)
    canonical = etree.tostring(element, method="c14n2", strip_text=True)
    return XmlDigests(
        literal=f"sha256:{sha256(XML_PREIMAGE.encode() + literal).hexdigest()}",
        canonical=f"sha256:{sha256(XML_PREIMAGE.encode() + canonical).hexdigest()}",
    )


@dataclass(frozen=True, slots=True)
class SchemaValidator:
    """One pinned standards schema, and its findings as `Diagnostic`s (CORE-42).

    The schema is loaded once through the pinned resolver; instance documents are parsed with the
    resolver-free parser. lxml's `_LogEntry` carries everything the common diagnostic envelope
    wants — including `path`, an XPath, which is what `field_path` means for a generated document.
    """

    schema: etree.XMLSchema
    source_id: str

    @classmethod
    def load(cls, pinned: PinnedSchemas, entry: str) -> SchemaValidator:
        """Build a validator from the pinned set, starting at one schema file."""
        pinned.closure(entry)
        parser = schema_parser(pinned)
        document = etree.fromstring(pinned.read(entry), parser)
        return cls(schema=etree.XMLSchema(document), source_id=entry)

    def validate(
        self, document: etree._Element, *, notation_object_id: str | None = None
    ) -> tuple[Diagnostic, ...]:
        """Every finding, or an empty tuple. Never raises on an invalid document.

        An invalid document is a fact about the generator's output, which is what a `Diagnostic`
        is for. Refusing would leave a caller unable to report more than the first problem.

        The loop reads `_LogEntry` attributes directly rather than through `getattr`, so every one
        of them is type-checked against `types-lxml`: `message`, `line`, `column`, `path`,
        `domain_name`, `type_name` and `level_name` are all declared there, and `path` is an XPath,
        which is what `field_path` means for a generated document.
        """
        if self.schema.validate(document):
            return ()
        found: list[Diagnostic] = []
        for entry in self.schema.error_log:
            found.append(
                build_diagnostic(
                    "CORE.SCHEMA.NOTATION_DOCUMENT_INVALID",
                    message=entry.message,
                    field_path=entry.path,
                    notation_object_id=notation_object_id,
                    severity=Severity.WARNING if entry.level_name == "WARNING" else None,
                    source_location=SourceLocation(
                        source_id=self.source_id,
                        semantic_path=entry.path,
                        line=entry.line or None,
                        column=entry.column or None,
                    ),
                    context=(
                        ("domain", entry.domain_name),
                        ("level", entry.level_name),
                        ("type", entry.type_name),
                    ),
                )
            )
        return tuple(found)
