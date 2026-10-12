# Nice-to-have: weitere biomedizinische Quellen

Stand: 9. Oktober 2026. Diese Liste ist ein Backlog für spätere Integrationsentscheidungen; sie fügt keine neuen aktiven Sources hinzu. Ziel bleibt eine generische Anbindung über veröffentlichte OpenAPI-3-/GraphQL-Schemas oder einen gepflegten nativen Python-Client. Ein öffentliches REST-Endpoint allein reicht dem aktuellen Importer nicht zur Erzeugung von Befehlen.

## Noch nicht eingebundene Kandidaten

| Quelle | Nutzen für Netzwerkmedizin | Aktueller Befund | Möglicher nächster Schritt |
| --- | --- | --- | --- |
| **openFDA** | Arzneimittel, Nebenwirkungsmeldungen und Produktinformationen | Öffentliche REST-API vorhanden; kein kompatibles offizielles OpenAPI-3-Schema verifiziert. | Anbieter-Schema oder gepflegten Python-Client prüfen; andernfalls Aufwand einer generischen zusätzlichen Schnittstellenunterstützung bewerten. |
| **Human Protein Atlas** | Proteinexpression, Gewebeverteilung und zelluläre Lokalisation | JSON/XML/TSV-Datenzugriff und Such-Exports vorhanden; kein kompatibles HTTP-API-Schema verifiziert. | Nativen Client oder generischen Zugriff auf tabellarische Downloads prüfen. Ein Schema für Datendateien ist kein OpenAPI-Schema für HTTP-Operationen. |
| **PubTator3** | Text-Mining von Genen, Krankheiten, Wirkstoffen und Beziehungen in Publikationen | Dokumentierte REST-API vorhanden; kein kompatibles veröffentlichtes OpenAPI-Schema verifiziert. | Verfügbarkeit eines Anbieter-Schemas oder eines gepflegten Python-Clients klären. |
| **InterPro** | Protein-Familien, Domänen und funktionelle Annotationen | Dokumentierte REST-Hierarchie vorhanden; kein kompatibles aktuelles OpenAPI-3-Schema verifiziert. | Anbieter-Schema oder geeigneten nativen Client prüfen. |

„Nicht verifiziert“ bedeutet nicht, dass es grundsätzlich kein Schema gibt. Die Suche und die konkrete Nutzbarkeit müssten vor einer Integration erneut geprüft werden. Es wurden keine eigenen Anbieter-Schemas oder Request-Wrapper erstellt.

Offizielle Dokumentation: [openFDA](https://open.fda.gov/apis/query-parameters/), [Human Protein Atlas](https://www.proteinatlas.org/about/help/dataaccess), [PubTator3](https://www.ncbi.nlm.nih.gov/research/pubtator3/api), [InterPro](https://interpro-documentation.readthedocs.io/en/latest/api.html).

## Weitere Verbesserungen an vorhandenen Sources

- pybiomart: HTTPS-Präfixfehler upstream beheben oder einen gepflegten alternativen Client prüfen; HTML-Ausfallseiten werden vom Paket nicht zuverlässig erkannt.
- OmniPath: Die tatsächliche Optionalität der Parameter in erzeugten Signaturen korrekt darstellen. Explizites None ist ein getesteter nativer Workaround.
- IntAct/Restish: Die verschachtelte Request-Schema-Referenz bei der Body-Validierung untersuchen. Die genaue Ursache von HTTP 403 bei breiten Netzwerkqueries bleibt offen.

Details und native Beispiele stehen in der [Source-Dokumentation](sources.md). Dafür gibt es keine Anbieter-Patches im netmed-Kern.
