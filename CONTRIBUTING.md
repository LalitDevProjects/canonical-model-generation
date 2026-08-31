# Contributing to Canonical Model Generation Platform

## Development Setup

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd CanonicalModel
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install development dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

## Development Workflow

### Contracts-first discipline

Per the PoC Build Guide's sequencing rule ("Contracts before code" -
Section 17.3), `contracts/` is the source of truth and `generated/` is a
build artifact of it:

1. Edit or add a JSON Schema under `contracts/{Cn}/{Name}/{semver}.json`
2. Regenerate: `python scripts/generate_models.py`
3. Commit `contracts/` and `generated/` together, in the same change
4. Add or update fixtures under `tests/fixtures/contracts/{Cn}/{Name}/{positive,negative}/`
5. If the change touches one of the six cross-artefact invariants (I1-I6),
   update `contracts/validators.py` and its tests

CI's `regen-and-diff` job runs `scripts/generate_models.py` fresh and fails
if the result differs from what's committed - `generated/` cannot drift
from `contracts/` and pass CI.

### Code Style

This project uses:
- **Black** for code formatting
- **isort** for import sorting
- **mypy --strict** for type checking (not a relaxed mypy profile - see `[tool.mypy]` in `pyproject.toml`)

Format code before committing:
```bash
black contracts/ config/ tests/ scripts/
isort contracts/ config/ tests/ scripts/
```

Run checks:
```bash
mypy --strict generated contracts config tests
```

`generated/` is included in the mypy run for type-checking purposes but is
never hand-edited - if mypy flags something there, the fix belongs in the
JSON Schema (`contracts/`) or in the codegen invocation
(`scripts/generate_models.py`), not in the generated file itself.

### Testing

Run all tests:
```bash
pytest
```

Run with coverage (fails under 85%, configured in `pyproject.toml`):
```bash
pytest --cov=generated --cov=contracts --cov=config --cov-report=term-missing
```

Run specific tests:
```bash
pytest tests/contracts/test_fixtures.py
pytest tests/unit/test_validators.py::TestI1EvidenceResolvable
```

### Test Categories

- **`tests/contracts/test_fixtures.py`** - every fixture under
  `tests/fixtures/contracts/` validated against both its JSON Schema and
  its generated Pydantic model. Positive fixtures must pass both; negative
  fixtures must fail at least one.
- **`tests/contracts/test_invariants.py`** - the six invariant checks
  (I1-I6) run against multi-record bundle fixtures under
  `tests/fixtures/invariants/`.
- **`tests/unit/test_validators.py`** - hand-written pass/fail-branch tests
  for `contracts/validators.py`, including branches JSON fixtures can't
  reach because the schema itself already rejects the shape (documented
  inline where this applies).
- **`tests/unit/test_config.py`** - `config/settings.py` loader tests.

### Adding a fixture for a new negative case

A negative fixture must violate something specific and be traceable to
what it violates - never an empty file or an arbitrary typo. Name the file
after the violation (`missing_evidence_refs.json`, `bad_hash_pattern.json`),
and if the violation is only enforced by `jsonschema`'s `if`/`then`/`oneOf`
handling and NOT by the generated Pydantic model on its own (see the module
docstring in `contracts/validators.py` for which contracts have this gap -
currently C7 and C10), say so in a comment... JSON has no comments, so put
it in the fixture's context by naming the containing negative/ directory
clearly and cross-referencing the schema's own `description` field, which
documents this per-contract.

### Commit Messages

Use clear, descriptive commit messages referencing the spec section or
increment where relevant:

```
[Contracts] Add C5 AttributeRecord evidenceTier field per Section 3.3
[Increment 4] Implement L0-L5 sanitisation ladder
[Validators] Fix I6 genesis-entry detection for empty region
```

### Pull Request Process

1. Create a feature branch from `main`
2. Make changes and add tests
3. Ensure `mypy --strict`, `pytest`, and the coverage gate all pass locally
4. If `contracts/` changed, confirm `generated/` was regenerated in the same commit
5. Update `docs/contracts.md` (contract changes) or the relevant `docs/`
   page for the increment being worked (Definition of Done, Section 17.5)
6. Create pull request with clear description
7. Address review comments
8. Merge when approved

## Architecture Overview

See the Project Structure section of `README.md` for the full repository
layout and which PoC increment (Section 17.2) populates each directory.
Directories not yet populated carry a `README.md` stating which increment
does so - check there before assuming a directory is simply missing.

### Key Concepts

- **Data Contracts**: JSON Schema 2020-12 under `contracts/`, generated
  into Pydantic v2 under `generated/`. Identity is deterministic
  (`evref://`, `attr://`, `cluster://`, `acord://`, `canon://` URI
  schemes), never a random UUID, so the same input produces the same
  identifiers on every run.
- **Cross-artefact invariants (I1-I6)**: constraints JSON Schema alone
  can't express because they span more than one document (e.g. "does this
  evidenceRef resolve against the run's actual CorpusManifest"). Enforced
  by `contracts/validators.py`, not by the generated models.
- **The platform proposes, humans ratify**: no artefact reaches release
  without a named human approver - this shapes checkpoint states and
  evidence tracking throughout.

## Dependencies Management

- `pyproject.toml` defines all dependencies, deliberately scoped to what
  the *current* increment needs rather than the eventual full system - see
  the comment at the top of `[project.dependencies]`.
- To add a dependency: add it to `pyproject.toml` in the appropriate
  section, then `pip install -e ".[dev]"` to update the environment.

## Common Issues

### Import Errors
The package is installed editable (`pip install -e ".[dev]"`), which
registers `contracts`, `generated`, and `config` as importable packages
from anywhere - no `PYTHONPATH` manipulation should be necessary. If
imports fail, confirm the editable install succeeded: `pip show
canonical-model-generation`.

### `generated/` out of date
```bash
python scripts/generate_models.py
git status generated/   # should show no changes if contracts/ already matched
```

### mypy failures in `generated/`
Don't edit the generated file. Fix the JSON Schema in `contracts/` and
regenerate. If the failure looks like a codegen tooling limitation rather
than a schema problem, check `scripts/generate_models.py`'s
`datamodel-code-generator` flags first.

## Security

- Never commit secrets (`.env` files, API keys, database credentials)
- `config/platform.yaml`'s `storage.postgres_dsn` is a local-dev placeholder only
- `egress.fail_mode` must remain `closed` - the config schema rejects any
  other value at load time (see `config/settings.py`)

## Support

For questions or issues:
1. Check `README.md` and `docs/`
2. Review `TECHNICAL_SPECIFICATION.txt` for the authoritative spec
3. Contact the Integration Architecture team

## License

Proprietary - Internal and named third parties only
