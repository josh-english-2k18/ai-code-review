# Repository Guidelines

## Project Structure & Module Organization

- `ai_review/` contains the core package and CLI.
- `ai_review/analyzers/` contains the Python, JavaScript, and TypeScript analyzers and the dependency graph.
- `ai_review/summarize/` builds packets, change summaries, and structural guides.
- `ai_review/prompt/` contains the review and synthesis templates, prompt composition, and packet chunking.
- `ai_review/security/` contains secret redaction utilities.
- `tests/` contains the pytest suite.
- `docs/` contains the [technical design](docs/TECHNICAL_DESIGN.md) and documentation assets.
- `auth/login.py` is a standalone login placeholder.
- `logo.png`, `pyproject.toml`, and `requirements*.txt` contain project assets and packaging metadata.

## Build, Test, and Development Commands

- `python -m pip install -e .` installs the CLI and its runtime dependencies in editable mode.
- `python -m pip install -e '.[dev]'` also installs the test dependencies.
- `ai_review prompt` generates a review brief for uncommitted changes.
- `ai_review prompt --base main --head HEAD` generates a brief for committed changes relative to the merge base.
- `ai_review analyze --full` rebuilds `REPO_GUIDE.md`.
- `python -m pytest` runs the test suite using `pytest.ini`.

## Coding Style & Naming Conventions

- Python code uses 4-space indentation and conventional PEP 8 naming (e.g., `snake_case` functions, `CapWords` classes) as seen in `ai_review/`.
- No formatter or linter is configured in this repo; match the surrounding style and keep modules small and focused.
- Prefer descriptive file names in `tests/` that mirror functionality (e.g., `test_git_ops.py`).

## Testing Guidelines

- Pytest discovers tests under `tests/` as configured in `pytest.ini`.
- Name test files `test_*.py`.
- Run all tests with `pytest` before major changes; add new tests for new analyzers or packet logic.

## Commit & Pull Request Guidelines

- Commit messages in history are short, sentence-style summaries without a strict convention. Keep them concise and specific (e.g., “Add JS heuristic parser”).
- Include the purpose of the change and the commands run with their results in each PR.
- Link relevant issues or references when available.
- Include screenshots or sample output when CLI output or templates change.

## Security & Configuration Notes

- The CLI filters common sensitive paths and applies best-effort redaction when rendering source excerpts and summaries. Account for redaction when adding data sources.
- The analysis cache lives at `.ai_review/cache/analysis.json`. Keep cache files, generated guides, and review packets out of commits.
