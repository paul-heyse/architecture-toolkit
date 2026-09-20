# Third-party materials

Python dependencies are resolved by uv.lock and retain their own package licenses.
Vendor binaries and standards schemas are downloaded from official sources into ignored
.tools/; they are not redistributed as repository content. Preserve bundled license and
notice files when packaging an export or a future installer.

- Temurin OpenJDK JRE: upstream GPLv2 with Classpath Exception; retain archive notices.
- PlantUML: the explicitly selected MIT distribution; consult its bundled notices.
- Structurizr: consult the selected distribution and component licenses. The free
  validate/export functionality is used; commercial server features are outside setup.
- OMG BPMN schemas: consult OMG's specification and schema terms before redistribution.
- Graphviz and optional bpmn-js/Kroki: separately installed, with their respective licenses.

Public reference links are citations, not license grants. No license is yet selected for
this project's own code. Review licensing before a distributable toolkit release.
