# context-drift

> A portable [Agent Skill](https://agentskills.io) that checks your agent instruction files (AGENTS.md, CLAUDE.md, GEMINI.md, `.github/copilot-instructions.md`, `.cursor/rules`, ...) against the code they describe. It runs the documented commands, finds paths, scripts and targets that no longer exist, the wrong package manager or language version, contradictions between files, and files a tool silently never loads. Then it fixes the files so every line is true again. Works in Claude Code, Codex CLI, Cursor, Gemini CLI, GitHub Copilot, and any other Agent-Skills-compatible tool.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Part of the [Agent Skills catalog](https://github.com/code-with-rashid/agent-skills).

## The problem

Coding agents follow their instruction files to the letter. When a script is
renamed, a directory moves, or the team switches from npm to pnpm or from
Poetry to uv, nobody updates AGENTS.md, and every agent keeps running the old
command, looking in the old place, and confidently getting it wrong. The
mistakes look like ordinary agent errors, so the stale file is the last place
anyone looks. A stale context file is worse than none.

It gets worse with several tools: CLAUDE.md says one thing, AGENTS.md another,
Copilot's instructions a third. And some files are never read at all: Claude
Code ignores AGENTS.md as soon as a CLAUDE.md exists, Cursor ignores `.md` files
in `.cursor/rules/`, Codex stops reading AGENTS.md files after 32 KiB.

## What this does

- **Checks every claim mechanically.** A bundled, dependency-free script finds
  all the context files and pulls out every command, path, `@import` and
  version they mention, then checks them against the repo: package.json
  scripts, Makefile/justfile/Taskfile targets, lockfiles, `.nvmrc`, `engines`,
  `requires-python`, `go.mod`, and the commands your CI really runs.
- **Runs the documented commands.** "The test command exists" isn't the same as
  "the test command works". Safe commands are run with a timeout; anything that
  deploys, publishes, pushes, deletes, or migrates a database is refused and
  checked by reading instead.
- **Finds files your tools never load,** and the one-line fix for each.
- **Fixes the docs, not the code.** Each wrong line is replaced with a verified
  replacement (or removed). Human-written rules are kept. Files don't grow.
- **Reports with evidence:** file, line, what was wrong, how it was checked.

## Quick demo

```text
$ python driftcheck.py scan --json .drift/scan.json
Context files: 4
  AGENTS.md                         read by: codex, cursor, copilot, claude (if no CLAUDE.md), gemini (if configured)
  CLAUDE.md                         read by: claude, copilot (root only)
  .github/copilot-instructions.md   read by: copilot
  .cursor/rules/style.md            read by: cursor
JS package manager: pnpm (package.json packageManager)

Problems (5):
  [version-mismatch] AGENTS.md:7  Node 18
      claims node 18; .nvmrc says 22; package.json engines.node says >=22
  [pm-mismatch] AGENTS.md:15  npm run test:unit
      uses npm but the repo uses pnpm; npm script `test:unit` not in package.json (similar: test)
  [missing-script] AGENTS.md:17  pnpm run check
      pnpm script `check` not in package.json (similar: typecheck)
  [missing-path] AGENTS.md:22  src/legacy/api.js
      does not exist
  [missing-path] .github/copilot-instructions.md:1  test/
      does not exist (similar in ./: tests)

Loading (3):
  [not-loaded] AGENTS.md  Claude Code reads only CLAUDE.md when both exist; nothing imports @AGENTS.md
  [not-loaded] .cursor/rules/style.md  Cursor only reads .mdc files in .cursor/rules/; this file is ignored

Commands to verify by running (7):
  c4    AGENTS.md:16  pnpm lint
  c9    AGENTS.md:27  pnpm deploy:prod [refuse: deploys or releases]
  ...

$ python driftcheck.py run --scan .drift/scan.json --all --out .drift/runs.json
running c4: pnpm lint
  -> failed exit 1 (0.6s)
     | src\api\client.js: no console.log in src/
  -> refused (0.0s)
     | not run: deploys or releases. Verify it by reading the code instead.
```

The agent then fixes each line, re-runs the replacements, and ends with a
table of findings and evidence.

## Install

The skill is the folder `skills/context-drift/`. It needs Python 3.8+ (standard
library only) and the project's own toolchain to run the commands it checks.

### Claude Code

```
/plugin marketplace add code-with-rashid/agent-skills
/plugin install context-drift@codewithrashid-skills
```

Or in one step on Claude Code v2.1.275+: `/plugin install context-drift --marketplace code-with-rashid/agent-skills`.

### Codex CLI, Cursor, Gemini CLI, GitHub Copilot, and other Agent Skills tools

Copy the skill folder (not the whole repo) into the skills directory your tool reads:

| Tool | Personal (all projects) | Project only |
|---|---|---|
| Codex CLI | `~/.agents/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` or `~/.agents/skills/` | `.cursor/skills/` or `.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` or `~/.agents/skills/` | `.gemini/skills/` or `.agents/skills/` |
| GitHub Copilot | `~/.copilot/skills/` or `~/.agents/skills/` | `.github/skills/` or `.agents/skills/` |
| Claude Code (without the plugin) | `~/.claude/skills/` | `.claude/skills/` |

```bash
git clone https://github.com/code-with-rashid/context-drift /tmp/context-drift
mkdir -p ~/.agents/skills
cp -r /tmp/context-drift/skills/context-drift ~/.agents/skills/
```

```powershell
git clone https://github.com/code-with-rashid/context-drift $env:TEMP\context-drift
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse "$env:TEMP\context-drift\skills\context-drift" "$HOME\.agents\skills\"
```

Gemini CLI can also install straight from the repo:
`gemini skills install https://github.com/code-with-rashid/context-drift.git --path skills/context-drift`.

## Usage

Ask in plain words; the skill's description makes the agent pick it up:

- "Is our AGENTS.md still accurate?" (report only, no edits)
- "We moved from Poetry to uv last month. Make sure the agent instructions are still right."
- "The agent keeps running `npm test` but we use pnpm. Fix our instructions."
- "Cursor isn't picking up our rules. Check the agent rule files."
- "Audit CLAUDE.md and copilot-instructions for anything stale after the refactor."

You can also run the script yourself:

```bash
python skills/context-drift/scripts/driftcheck.py scan            # report
python skills/context-drift/scripts/driftcheck.py scan -v         # also list claims that checked out
python skills/context-drift/scripts/driftcheck.py scan --json .drift/scan.json
python skills/context-drift/scripts/driftcheck.py run --scan .drift/scan.json --all
```

`scan` exits 1 when it finds problems, so it also works as a CI check.

## How it relates to other tools

Claude Code has a built-in `/doctor prompt-audit` (v2.1.283+) that reviews its
own instruction files for outdated or conflicting content. context-drift is
complementary: it covers every tool's files, actually runs the documented
commands, checks claims against lockfiles, version files and CI, and flags
cross-tool loading problems. Linters that only check structure or length of
AGENTS.md don't verify that its contents are still true.

## Limitations

- The script extracts commands from code blocks and inline code, and paths from
  inline code and links. Claims in plain prose ("tests live under the api
  folder") are left to the agent, which the skill tells to spot-check them.
- It verifies commands by running them here. A command that needs services,
  secrets, or a toolchain that isn't installed is reported as unverified, not
  as wrong.
- Monorepos with many nested context files work, but "differing commands"
  findings are only reported between files that govern the same directory.
- Which tool reads which file is documented in
  [references/harness-files.md](skills/context-drift/references/harness-files.md)
  as of October 2026; tools change this, so the reference cites its sources.
- Works best with frontier-tier models; see [evals/RESULTS.md](evals/RESULTS.md).

## Development

```bash
python -m unittest discover -s tests       # script unit tests
python evals/scenarios/make_webapp.py /tmp/webapp      # build an eval scenario
```

Eval prompts and expectations are in [evals/evals.json](evals/evals.json);
results in [evals/RESULTS.md](evals/RESULTS.md).

## Contributing

Issues and pull requests are welcome, especially:

- false positives or misses from real repositories (include the context file
  line and the repo layout),
- new runners, task runners, or toolchain version files,
- changes in which files a tool loads (with a link to the tool's docs).

Please keep the script dependency-free and add a unit test with every change.

## License

[MIT](LICENSE) © Rashid Mahmood
