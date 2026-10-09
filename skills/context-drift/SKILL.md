---
name: context-drift
description: >-
  Check a repo's agent instruction files (AGENTS.md, CLAUDE.md, GEMINI.md,
  .github/copilot-instructions.md, .cursor/rules, and similar) against the
  actual code: run the commands they document, find paths, scripts and
  make targets that no longer exist, the wrong package manager or language
  version, files that contradict each other, and files a tool silently never
  loads. Then fix the files so every line is true. Use when asked to audit,
  verify, update, clean up, or fix AGENTS.md / CLAUDE.md / agent rules, when
  an agent keeps running a wrong or renamed command, after a refactor, rename,
  or tooling migration (npm to pnpm, Poetry to uv, Jest to Vitest), or when
  asked "is our AGENTS.md still accurate?". Not for writing a first context
  file from scratch.
license: MIT
compatibility: Requires Python 3.8+. Runs the project's own documented commands, so their toolchains must be installed to verify them.
metadata:
  version: "0.1.0"
  author: Rashid Mahmood
---

# Context drift

Agents follow their instruction files to the letter. A renamed script, a moved
directory, or a migration from npm to pnpm turns a helpful AGENTS.md into one
that sends every agent down the wrong path, and nobody notices because the
mistakes look like ordinary agent errors. Your job is to make every claim in
these files true again, with evidence, and change nothing else.

## Hard rules

- **Every line you keep or write must be backed by evidence from this session**:
  a command you ran and saw pass, a file you saw exist, a manifest or CI file you
  read. Don't write a replacement command you haven't run (or, if it is unsafe
  to run, read in the manifest that defines it).
- **Never run commands that deploy, publish, push, delete, migrate a database,
  or need credentials**, even when the context file documents them. The helper
  refuses them; don't run them yourself instead. Check that they are defined
  (script, target, file) and say "not run: <reason>".
- **Fix the docs, not the code.** If a documented command is missing because
  the code changed, update the doc to the new truth. Don't re-add scripts,
  rename files, or edit code to match a stale doc. If the doc looks right and
  the code looks accidentally broken (CI still calls the missing script), report
  it and ask instead of choosing.
- **Keep the rules people wrote.** Guardrails and conventions ("never commit to
  main", "no I/O in stock.py") can't be proven by running anything. Keep them
  unless they name something that no longer exists; then update the name.
- **Don't grow the files.** Replace wrong lines, delete lines about things that
  are gone. Don't add new sections, generic advice, or a summary of the code.
  The only additions allowed are ones that fix a finding (for example a
  one-line `@AGENTS.md` import so Claude Code reads AGENTS.md).
- **Don't say "verified" about anything you didn't check.** A command that
  could not run here (tool not installed, needs network or services) is
  `unverified`, with the reason.

## The helper

`scripts/driftcheck.py` (stdlib Python) does the mechanical part. Run it from
the repo root with the path adjusted to where this skill is installed, and keep
its output in `.drift/` (don't commit it):

```bash
python <skill>/scripts/driftcheck.py scan --json .drift/scan.json [-v]
python <skill>/scripts/driftcheck.py run --scan .drift/scan.json --ids c4 c7 --out .drift/runs.json
python <skill>/scripts/driftcheck.py run --scan .drift/scan.json --all --out .drift/runs.json
python <skill>/scripts/driftcheck.py run --cmd "<replacement command>" --out .drift/runs.json
```

`scan` finds every context file and lists, with `file:line`: missing paths,
scripts, make/just/task targets and `@imports`; package-manager mismatches
against the lockfile; version claims that disagree with `.nvmrc`, `engines`,
`requires-python`, `go.mod` and friends; files a tool won't load; commands that
differ between files; and the commands CI actually runs. Each documented
command gets an id (`c4`) so `run` can execute it. `run` uses a timeout,
refuses risky commands, counts a dev server that is still up after
`--long-timeout` seconds as `started`, and records exit code and output tail.
On Windows it runs commands under Git Bash when available.

## Procedure

**1. Scan.** Run `scan`. Read the list of context files and which tools read
each one; that tells you whose behaviour each file controls.

**2. Find the truth sources.** For each kind of claim, the repo has an
authority: `package.json` scripts and `packageManager`, the lockfile,
`pyproject.toml`, `Makefile`/`justfile`, toolchain version files, and above all
the CI workflow, which shows the commands that really run on every change.
[references/truth-sources.md](references/truth-sources.md) lists them per
ecosystem.

**3. Run the documented commands.** Run every command the scan lists as
unverified (`run --all`, or by id). Install dependencies first only if the
project's own install command is cheap and the others need it. A command that
exists can still be wrong: it may fail, run zero tests, or test the wrong
directory, so read the output, not just the exit code. Long-running commands
(`dev`, `watch`) only need to start.

**4. Check what the script can't.** Read the prose. Spot-check each concrete
statement about the code ("tests live in `test/`", "we use Redux", "API
handlers are in `src/routes`") with a search or a directory listing. Check
claims about tooling against manifests (a file that says "managed with Poetry"
in a repo with `uv.lock` is wrong even if no command says `poetry`). See
[references/claim-kinds.md](references/claim-kinds.md) for what each finding
means and how to fix it.

**5. Decide each finding.** For every problem, find the replacement and prove
it: run the new command (for example `pnpm typecheck` instead of
`pnpm run check`) or confirm the new path exists. When files disagree, the one
that matches the truth sources wins. If you can't find a replacement, delete
the claim rather than guess, and say so in the report.

**6. Fix loading problems.** If a tool never reads a file (Claude Code ignores
AGENTS.md when CLAUDE.md exists; Cursor ignores `.md` in `.cursor/rules/`;
Copilot only reads `*.instructions.md` in `.github/instructions/`), apply the
smallest fix from [references/harness-files.md](references/harness-files.md),
usually a one-line import or a rename. Don't merge or restructure files unless
the user asks. Report only the loading problems the scan or that reference
states; for example, with no CLAUDE.md at all, Claude Code reads AGENTS.md
directly, so that is not a problem and needs no new file.

**7. Edit, then re-check.** Make the edits. Re-run `scan` and `run` on every
command you changed or added. Done when the scan shows no problems you haven't
either fixed or explained, and every command in the files has a run result or a
stated reason it wasn't run.

## Report

End with this, even when nothing needed fixing:

```markdown
## Context drift: <repo>
Files checked: AGENTS.md (codex, cursor, copilot), CLAUDE.md (claude), ...

| File:line | Claim | Finding | Evidence | Fix |
|---|---|---|---|---|
| AGENTS.md:15 | `npm run test:unit` | script renamed, wrong package manager | no `test:unit` in package.json; pnpm-lock.yaml; `pnpm test` passed (2 tests) | `pnpm test` |
| AGENTS.md:27 | `pnpm deploy:prod` | not run (deploys) | script exists in package.json | kept |

Verified by running: <commands and results>
Not run: <commands and why>
Left for you: <anything that needs a human decision>
```
