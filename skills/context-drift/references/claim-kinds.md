# Finding kinds and how to fix them

| Status (from `scan`/`run`) | Meaning | Fix |
|---|---|---|
| `missing-script` | `npm run X`, `pnpm X`, ... names a script that isn't in package.json | Find the successor (similar names are listed), run it, replace. If there is none, delete the line. |
| `missing-target` | `make X` / `just X` / `task X` names a target that doesn't exist | Same as above, from the Makefile/justfile/Taskfile. |
| `missing-path` | a path, a script file, a `cd` directory, or a `python -m` module doesn't exist | Look for the moved file (hints list the same name elsewhere or close names nearby). Replace or delete. A `python -m` hit can be a false alarm for an installed third-party module; check before editing. |
| `missing-import` | a CLAUDE.md/GEMINI.md `@import` target doesn't exist | Point it at the moved file or remove the import. |
| `pm-mismatch` | a command uses a package manager the repo doesn't use | Rewrite with the repo's manager (`npm run test` to `pnpm test`, `poetry run X` to `uv run X`) and run it. Also fix prose that names the old tool. |
| `version-mismatch` | "Node 18" while `.nvmrc` says 22, "Python 3.9" while `requires-python >=3.11` | Use the declared version. Prefer pointing at the file ("the Node version in `.nvmrc`") over copying a number that will drift again. |
| `generated` | a missing path that looks like a build output (`dist/`, `coverage/`) | Usually fine. Check the command that creates it exists. |
| `not-loaded` | a tool never reads this file | See harness-files.md. |
| `not-loaded-info` | a tool reads it only if configured | Mention it; change config only if the repo uses that tool. |
| `too-long` / `truncated` | over Claude Code's 200-line advice / over Codex's 32 KiB | Move detail out; don't silently delete rules. Ask if unsure what to cut. |
| `unverified` (scan) | a command passed the static checks but hasn't been run | Run it. |
| `passed` / `failed` / `timeout` / `started` / `refused` (run) | the outcome of running it | `failed`: read the tail. Decide whether the command is wrong (stale flag, wrong directory, runs zero tests) or the code is broken. Only the first is drift. A failing test suite with a correct command is not a doc problem; report it separately. |

## Differing commands across files

`scan` lists commands with the same purpose (test, lint, typecheck, format,
build) that differ between files. Not all of these are wrong: `pnpm test` and
`pnpm test -- --coverage` can both be true. A difference is drift when one
version fails or uses the wrong tool. Make the wrong one match the right one.
When both work and serve different purposes, leave them.

## Claims the script can't see

Read the prose for these and spot-check each one:

- locations: "tests live in", "handlers are in", "config is loaded from"
- tools and libraries: "we use Redux", "styled with Tailwind", "Poetry for dependencies"; check the manifest
- workflow: branch names (`main` vs `master`; `git branch -r`), PR templates, required checks
- environment: env var names (grep for them in code and `.env.example`), ports, service names in `docker-compose.yml`/`compose.yaml`

Unverifiable rules (style preferences, "ask before X", "never Y") are kept as
they are. They are the most valuable lines in the file.
