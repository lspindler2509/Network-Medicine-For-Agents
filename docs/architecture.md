# Architecture and next steps

The TOML registry identifies sources, not individual functions. OpenAPI import generates an operation catalog; Python discovery and help delegate to Fire on demand. Native signatures and schemas remain visible. This shared catalog is a routing description, not a universal biomedical data model.

Importers discover interfaces. Runtime executes them. `netmed` routes user/agent requests. A detached worker launches the same CLI, so background execution does not need tool-specific code.

Next steps, in order:
1. Contract tests against Drugst.one and a real OpenAPI source; audit discovery completeness and output formats.
2. JSON/file arguments, reliable serialization of package objects and CLI diagnostics.
3. Version-pinned managed environments and a downloadable launcher. Virtual environments are dependency isolation, not security sandboxes.
4. Provider-scoped credentials with host binding; uniform secret redaction and per-process environment allowlists. The initial HTTP runner refuses secured operations.
5. Progress events, cancellation, stale-worker detection and explicit checkpoint protocols.
6. R and GraphQL importers.
7. Scheduled LLM-assisted discovery: candidate URLs/packages with evidence, deterministic validation, isolated smoke tests, reviewed catalog updates.

Do not infer resumability from background support: an arbitrary function cannot be resumed after its process dies. Existing pagination in a package remains usable, but checkpoints need an explicit package/runtime protocol. Automatic long-job detection is heuristic; source policy or an explicit flag is dependable.

No LLM orchestration or permanently hosted service is required for execution. Weekly discovery can run in CI later. Discovered packages must not be automatically executed in a credential-bearing process.
