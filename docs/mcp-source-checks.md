# Public MCP source checks

Checked on 6 November 2026 using netmed's generic MCP source type and MCP Python
SDK 1.30.0. All five additions use only registry entries: no provider-specific
adapters, schema overrides or generated wrapper implementations were needed.

| Registry name | Provider / endpoint | Tools | Negotiated protocol | Small read-only check |
| --- | --- | ---: | --- | --- |
| `opentargets_mcp` | [Open Targets](https://github.com/opentargets/platform-mcp), `https://mcp.platform.opentargets.org/mcp` | 5 | 2025-06-18 | `search_entities` for EGFR returned target `ENSG00000146648` and other entity types. |
| `gwas_mcp` | [GWAS Catalog](https://github.com/gwas-catalog/mcp), `https://www.ebi.ac.uk/gwas/mcp` | 3 | 2025-11-25 | `gwascatalog_get_traits` with `efo_trait="Celiac disease", size=1` returned one record and explicit pagination for two matches. |
| `ols_mcp` | [EMBL-EBI OLS](https://github.com/EBISPOT/ols4), `https://www.ebi.ac.uk/ols4/api/mcp` | 12 | 2025-03-26 | `searchClasses` with `query="diabetes", ontologyId="efo", pageSize=1` returned an ontology class. |
| `expasy_mcp` | [SIB / ExPASy](https://github.com/sib-swiss/sparql-llm), `https://chat.expasy.org/mcp` | 19 | 2025-11-25 | `get_protein` with accession `P00533` returned human EGFR information. |
| `biocontext_mcp` | [BioContextAI Knowledgebase](https://biocontext.ai/docs), `https://biocontext-kb.fastmcp.app/mcp` | 49 | 2025-11-25 | `get_uniprot_id_by_protein_symbol` with EGFR and species 9606 returned reviewed accession `P00533`. |

Each discovery and selected tool's cached `--help` completed successfully. Every
data call above exited zero, reported `isError=false`, and its result content was
inspected. BioContextAI is a community proof of concept with usage limits, not an
official UniProt endpoint; its test result comes from its UniProt wrapper.
ExPASy's interactive visualization tools were discovered but not tested or rendered.

The first GWAS query used `efo_id="EFO_0001360", size=1` and returned an explicit
empty result, not an execution error. The follow-up above confirmed nonempty data.
This does not establish why the original ID filter matched nothing or prove
complete/correct disease coverage. The documented MCP-2.x-client wording did not
prevent this deployed server from negotiating protocol 2025-11-25 with our client.

Observed discovery wall times were approximately 1.1–2.7 seconds per source;
initial data calls took approximately 1.0–3.3 seconds including CLI startup and
connection negotiation. These were single small calls, some run concurrently,
not a controlled performance benchmark. No broad network queries or analysis jobs
were submitted, and no automatic tool retries were used.

The sources are registered in `sources.toml` alongside the existing `hippie`
source. A combined test catalog was built for all six MCP sources and used to
check cross-source search. Published/previously installed CLI bundles are not
modified by editing this registry; a new bundle must include the updated catalog.

Tests used source mode on macOS. Windows/Linux and every individual exposed tool
were not exercised. Existing REST/GraphQL sources remain available separately,
including `opentargets` and `ols4`; their MCP counterparts have distinct names.
