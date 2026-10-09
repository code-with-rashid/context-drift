# Changelog

## 0.1.0 — 2026-10-09

First release.

- `context-drift` skill: a procedure for checking agent instruction files
  (AGENTS.md, CLAUDE.md, GEMINI.md, Copilot, Cursor, Windsurf, Cline, Junie)
  against the repository, with evidence for every kept or changed line, and
  hard rules against running deploy/publish/migrate commands, editing code to
  match stale docs, or dropping human-written rules.
- `scripts/driftcheck.py` (stdlib Python): `scan` (missing paths, scripts,
  make/just/task targets and `@imports`; package-manager and version
  mismatches; files a tool never loads; differing commands across files; CI
  commands) and `run` (runs documented commands with timeouts, refuses risky
  ones, records results).
- References: which tool reads which file, where the truth lives per
  ecosystem, and what each finding means.
- Unit tests and end-to-end evals with two reproducible scenarios.
