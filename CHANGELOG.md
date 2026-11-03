# Changelog

## 0.2.0 — 2026-11-03

- Antigravity CLI support (it replaced Gemini CLI for unpaid and Google One
  users in June 2026): `scan` now finds `.agents/AGENTS.md`, `.agents/GEMINI.md`
  and `.agents/rules/*.md`, flags rule files Antigravity silently drops
  (missing or camelCase `trigger:`, subfolders not listed in
  `.agents/rules.json`), `manual` rules the CLI can't load, and files over its
  24,000-byte limit. AGENTS.md and GEMINI.md are reported as read by Antigravity.
- `references/harness-files.md` updated with Antigravity's loading rules and
  `@[label](path)` imports.
- README: Antigravity CLI install path and `gh skill install`.

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
