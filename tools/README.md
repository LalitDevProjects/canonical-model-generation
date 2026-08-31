# tools

Populated at Increment 6. The tool gateway (Section 7.2): "Agents reach
everything through typed tools. The gateway holds the registry,
enforces per-agent authorisation, validates arguments and results
against schema, and audits every call."

- `registry.py` - `ToolDefinition` (matches the spec's own fully-worked
  example, `acord.lookup`, exactly: name/description/input_schema/
  output_schema/authorisation/audit) and `TOOL_REGISTRY`, all 9 tools
  named in Section 7.2's table. Authorisation is by explicit agent-id
  list, except `authorised_agents="*"` for the two tools the spec's own
  summary table marks "All families" (`artefact.write`, `substrate.query`).
  `substrate.neighbours` gained `"semantic-resolver"` at Increment 7
  (Section 7.5.1's own tools list names it, though the real
  `SemanticResolverAgent` doesn't call it through the gateway yet -
  `assemble_context` reads via `SubstrateApi.search` directly, the same
  precedent Repository Scout already set for reading fields without a
  tool call).
- `gateway.py` - `ToolGateway.call(agent_id, tool_name, args, run_id)`:
  authorisation check (denies + journals `tool.denied` on failure) ->
  argument schema validation -> the real handler -> result schema
  validation -> `tool.call` journalling. Real handlers exist now for
  `artefact.write` (every agent's own write path, invoke() step 9),
  `spec.parse` (wraps `parsers/router.py::parse`), and
  `substrate.query`/`substrate.neighbours`/`acord.lookup` (thin wrappers
  over the already-real `substrate/api.py::SubstrateApi`).
  `repo.search`/`repo.read`/`kb.search`/`catalogue.query` are registered
  but have no real handler yet (`NotImplementedError`) - none of them
  would function without a real search index this repo doesn't have;
  honestly deferred, not silently stubbed.

`ToolGateway.call()` takes explicit `run_id`/`agent_id` rather than a
full `RunContext` (defined in `agents/base.py`) specifically to avoid a
circular import - `agents/base.py` needs `ToolGateway` for
`RunContext`'s own `tools` field, so this module must not need
`agents/base.py` in return.

See `docs/increments.md` for what Increment 6 built and verified.
