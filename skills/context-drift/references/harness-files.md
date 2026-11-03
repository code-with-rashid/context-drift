# Which tool reads which file

Checked against each tool's documentation in November 2026. Tools change this
often; when a finding depends on it, say which rule you relied on.

| File | Read by | Notes |
|---|---|---|
| `AGENTS.md` (root and nested) | Codex, Cursor, GitHub Copilot, Antigravity, Claude Code (see below), Gemini CLI (if configured) | Codex: one file per directory, root down to the working directory, closer files later; stops adding files at 32 KiB (`project_doc_max_bytes`). Copilot and Cursor: nearest nested file takes precedence. Antigravity: workspace folder and its parents up to the repo root, never subfolders below where it was started. |
| `.agents/AGENTS.md`, `.agents/GEMINI.md`, `.agents/rules/*.md` | Antigravity (CLI and app) | Rules add up; none overrides another. `rules/` files need frontmatter `trigger:` (see below). Legacy `.agent/` also read. |
| `AGENTS.override.md` | Codex | Replaces `AGENTS.md` in the same directory. |
| `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` | Claude Code | Loaded from the working directory and every parent; subdirectory files load when Claude touches files there. Docs recommend under 200 lines per file. |
| `.claude/rules/*.md` | Claude Code | Optional `paths:` frontmatter scopes a rule to matching files. |
| `GEMINI.md` | Gemini CLI, Antigravity | Gemini CLI: global `~/.gemini/GEMINI.md`, workspace and parents, plus just-in-time files. Antigravity: same places as `AGENTS.md`. |
| `.github/copilot-instructions.md` | GitHub Copilot | Repository-wide. |
| `.github/instructions/**/*.instructions.md` | GitHub Copilot | Must end `.instructions.md`; `applyTo:` glob in frontmatter. |
| root `CLAUDE.md` / `GEMINI.md` | GitHub Copilot | Read as agent instructions, root only. |
| `.cursor/rules/**/*.mdc` | Cursor | Only `.mdc` is read. Frontmatter: `description`, `globs`, `alwaysApply`. |
| `.cursorrules`, `.windsurfrules` | legacy | Current docs don't describe them; don't rely on them being read. |

## Loading problems and their smallest fixes

**Claude Code ignores AGENTS.md when a CLAUDE.md exists.** Claude Code reads
AGENTS.md only when there is no CLAUDE.md or CLAUDE.local.md in the working
directory or above (unless the user changed the "Project instructions"
setting). Fix: add a line `@AGENTS.md` to CLAUDE.md, outside backticks and code
blocks (imports inside code are ignored). Then remove anything in CLAUDE.md that
now duplicates or contradicts AGENTS.md.

**Gemini CLI doesn't read AGENTS.md by default.** It reads `GEMINI.md`. Fix, if
the team uses Gemini CLI: create `.gemini/settings.json` with
`{"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}}`, or a `GEMINI.md`
containing `@AGENTS.md` on its own line. Only do this when the repo shows signs
of Gemini use (a `.gemini/` directory, a GEMINI.md, docs that mention it) or the
user asks; otherwise mention it in the report. Antigravity CLI, which replaced
Gemini CLI for unpaid and Google One users in June 2026, reads AGENTS.md
without any setting.

**Antigravity discards rule files without a valid trigger.** Each
`.agents/rules/*.md` file needs YAML frontmatter with `trigger:` set to
`always_on`, `model_decision`, `glob` or `manual`, in snake_case (`alwaysOn` is
dropped). Fix: add the frontmatter; use `always_on` unless the rule is clearly
scoped. `manual` rules load only when @-mentioned, which the CLI can't do.
Files in subfolders of `rules/` are ignored unless listed in
`.agents/rules.json`; move them up a level or list them.

**Antigravity truncates big files.** Each rule file, `AGENTS.md` and
`GEMINI.md` is cut at 24,000 bytes, and all always-on rules share a 20,000-token
budget (the largest get demoted to a one-line pointer). Split large files.

**Cursor ignores `.md` in `.cursor/rules/`.** Rename to `.mdc` (`git mv`) and
make sure the frontmatter has `alwaysApply: true`, or `globs`, or a
`description`, otherwise the rule is never attached.

**Copilot ignores `.github/instructions/foo.md`.** Rename to
`foo.instructions.md` and add `applyTo: "**"` (or a narrower glob) frontmatter.

**Codex truncates large AGENTS.md chains.** Above 32 KiB combined, later
(closer) files are dropped. Move detail into nested AGENTS.md files next to the
code they describe, or into docs the file links to.

## Import syntax

- Claude Code: `@path/to/file` anywhere outside code spans and fences; relative
  to the importing file; up to four hops; escape spaces with `\ `.
- Gemini CLI: `@path/to/file.md` on its own line; relative or absolute.
- Antigravity: `@[label](path)` inlines the file; a bare `@path` is only a
  file reference and does not inline anything.
- Codex, Cursor, Copilot: no import syntax; link to files instead and the agent
  reads them on demand.

## Sources

- https://code.claude.com/docs/en/memory
- https://learn.chatgpt.com/docs/agent-configuration/agents-md (Codex)
- https://geminicli.com/docs/cli/gemini-md/
- https://antigravity.google/docs/rules/ and https://antigravity.google/docs/customization-discovery/
- https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions
- https://cursor.com/docs/context/rules
