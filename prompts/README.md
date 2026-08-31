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

Schema Interpreter has no template here - `model_tier: n/a` means no
model call, so there is nothing to render (see
`agents/deterministic.py`).
