# prompts

Populated at Increment 6. Versioned agent prompt templates
(`prompts/{agent-id}/{semver}.md`), pinned per run and rendered by
`agents/prompt_render.py::render()` - the single prompt-construction
site in this repo (Section 7.4: "String concatenation of model input
anywhere in the codebase is a review failure").

Every template carries all six required blocks (ROLE, INPUT, RULES,
OUTPUT, UNCERTAINTY, INJECTION) - `load_prompt_template()` raises if any
is missing, so a template that forgets `[INJECTION]` fails at load time,
not silently in production.

- `repository-scout/1.0.0.md` - the real Repository Scout prompt (see
  `agents/repository_scout.py`).
- `semantic-resolver/2.3.0.md` (Increment 7) - Section 7.5.1's blocks
  transcribed verbatim (see `agents/semantic_resolver.py`). Version
  `2.3.0` matches the spec's own literal `--- PROMPT
  semantic-resolver/2.3.0 ---` line.
- `acord-aligner/1.6.0.md` + `canonical-synthesiser/1.9.1.md`
  (Increment 8) - Section 7.5.2/7.5.3's blocks transcribed verbatim,
  each with one addition: the spec's own worked prompt text for both
  has no `[INJECTION]` block at all, despite Section 7.4's own hard
  rule ("Present in every template that reads corpus content") and this
  repo's own `agents/prompt_render.py::load_prompt_template` requiring
  all six blocks - a real inconsistency between the spec's worked
  example and its own stated rule, resolved by adding one, matching
  Repository Scout/Semantic Resolver's own established phrasing.

Schema Interpreter has no template here - `model_tier: n/a` means no
model call, so there is nothing to render (see
`agents/deterministic.py`).
