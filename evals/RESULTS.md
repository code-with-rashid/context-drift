# Eval results

Run on 2026-10-09 (v0.1.0) on Windows 11, Python 3.14, Node 24, pnpm 9.
Each behaviour eval ran in a fresh sub-agent with no context other than the
installed skill, the scenario repo, and the user prompt. Prompts and the full
expectation lists are in [`evals.json`](evals.json); scenarios are rebuilt with
`scenarios/make_webapp.py` and `scenarios/make_pyservice.py`. Outcomes were
graded from the scenario repos themselves (`git diff`, marker files), not from
the agents' own reports.

## Script tests

`python -m unittest discover -s tests`: 25 tests, all passing (claim extraction
from fences, console transcripts, inline code, links and `@imports`; path
heuristics; version ranges; package scripts, package-manager mismatches,
make/just/task targets, file arguments, `python -m` modules; loading rules for
Claude Code, Cursor, Copilot and Codex; symlinked context files; package-relative
paths; template commands; scoped contradictions; CI command extraction; the
risky-command guard; `run` pass/fail/refused/started; both scenarios as answer
keys).

## Real repositories (false-positive check)

`scan` was run on shallow clones of openai/codex, pydantic/pydantic-ai and
vitejs/vite. The first version reported 149 problems on pydantic-ai, nearly all
false: paths written relative to a package directory, jq selectors such as
`.headers`, bare file names, symlinked CLAUDE.md files. After fixing those, it
reports 0 problems on codex and vite and 3 on pydantic-ai, all of which look
like genuine drift (a renamed `pydantic-clai2/` directory used in a documented
pytest command, and two test files that moved to `tests/clai2/`), plus nested
AGENTS.md chains over Codex's 32 KiB default.

## Behaviour (Claude Code sub-agents, default model)

| Eval | Result | Notes |
|---|---|---|
| webapp-fix-all | 9/9 | ran test/typecheck/build/lint; `pnpm test`, `pnpm typecheck` replacements run before writing; legacy path, Copilot `test/`, Node 22 fixed; `@AGENTS.md` added to CLAUDE.md; `git mv` to `style.mdc`; deploy not run (no marker file) and line kept; lint failure reported as a code issue, command kept; package.json and code untouched; also found an unplanted bug: Copilot's `pnpm test -- --coverage` fails under `node --test`, replaced with `--experimental-test-coverage` after running it; reverted the lockfile rewrite from `pnpm install` |
| pyservice-after-migration | 7/7 | Python 3.11+, uv (prose and command); `tests/unit` line removed; `make check`, `scripts/seed.py`, `python -m stockroom --help`; `make migrate` not run (no marker file) and kept; both rules kept; said explicitly that `uv`/`make` aren't installed and which Python equivalents it ran instead |
| webapp-report-only | 3/3 | `git status` clean; all four AGENTS.md problems with evidence; Claude-never-reads-AGENTS.md finding; also flagged the Copilot coverage flag and the Cursor `.md` rule |

## Triggering (skill-router simulation, 10 neighbouring skill descriptions)

Neighbours included the five other catalog skills plus generic `documentation`,
`init`, `claude-md-improver`, `debug` and `changelog` descriptions. 6 prompts
should trigger, 6 should not.

| Router model | Should trigger | Should not trigger |
|---|---|---|
| Sonnet | 6/6 | 6/6 (README to none, CHANGELOG to changelog, flaky CI to flake-or-fault, "explain the cart" to mental-model, lint to none, "write an AGENTS.md" to none) |
| Haiku | 6/6 | 6/6 (same, except README to documentation and "write an AGENTS.md" to init) |

## Behaviour on a smaller model (Haiku)

| Eval | Result | Notes |
|---|---|---|
| webapp-fix-all | 9/9 | same fixes as the default model, including the unplanted coverage-flag bug; deploy not run; lint failure reported, not hidden; lockfile rewrite from `pnpm install` reverted |
| pyservice-after-migration | 7/7 on the files | all six fixes correct, `make migrate` not run, rules kept, uv/make honestly reported as not run. One false statement in the reply: it said Claude Code would not read AGENTS.md without a CLAUDE.md (it does). SKILL.md step 6 now says so explicitly. |
| pyservice-after-migration (re-run on the final SKILL.md) | 7/7 | same file outcome; reply now correctly says Claude Code reads AGENTS.md because there is no CLAUDE.md |
