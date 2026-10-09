#!/usr/bin/env python3
"""Check agent context files (AGENTS.md, CLAUDE.md, GEMINI.md, Copilot and
Cursor rules, ...) against the repository they describe.

  scan   find the context files, pull out every command, path, script, import
         and version they claim, and check each one against the repo.
  run    run documented commands (by id from a scan, or --cmd) with a timeout,
         refusing anything that deploys, publishes, pushes, or deletes.

Standard library only. Python 3.8+.
"""

import argparse
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist",
    "build", "target", "vendor", ".next", ".nuxt", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".gradle", ".idea",
    ".drift", "coverage", ".turbo", ".cache",
}

# name -> tools that read it (for the report). Matched on the path relative to root.
CONTEXT_PATTERNS = [
    ("AGENTS.md", "codex, cursor, copilot, claude (if no CLAUDE.md), gemini (if configured)"),
    ("AGENTS.override.md", "codex"),
    ("CLAUDE.md", "claude, copilot (root only)"),
    ("CLAUDE.local.md", "claude"),
    (".claude/CLAUDE.md", "claude"),
    (".claude/rules/*.md", "claude"),
    ("GEMINI.md", "gemini, copilot (root only)"),
    (".github/copilot-instructions.md", "copilot"),
    (".github/instructions/*", "copilot"),
    (".cursor/rules/*", "cursor"),
    (".cursorrules", "cursor (legacy)"),
    (".windsurfrules", "windsurf (legacy)"),
    (".windsurf/rules/*.md", "windsurf"),
    (".clinerules", "cline"),
    (".clinerules/*.md", "cline"),
    (".junie/guidelines.md", "junie"),
    ("CONVENTIONS.md", "aider (when passed with --read)"),
]
NESTABLE = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md"}

SHELL_LANGS = {"", "bash", "sh", "shell", "console", "zsh", "shell-session",
               "powershell", "pwsh", "ps1", "cmd", "bat", "terminal", "fish"}

KNOWN_TOOLS = {
    "npm", "npx", "pnpm", "yarn", "bun", "bunx", "deno", "node", "tsc", "eslint",
    "prettier", "biome", "vitest", "jest", "playwright", "make", "just", "task",
    "cargo", "rustc", "go", "golangci-lint", "python", "python3", "py", "pip",
    "pip3", "pytest", "uv", "uvx", "poetry", "pipenv", "hatch", "pdm", "tox", "nox",
    "ruff", "black", "mypy", "pyright", "flake8", "isort", "pre-commit", "gradle",
    "./gradlew", "gradlew", "mvn", "./mvnw", "mvnw", "dotnet", "bundle", "rake",
    "rails", "rspec", "ruby", "php", "composer", "phpunit", "mix", "swift",
    "xcodebuild", "flutter", "dart", "docker", "docker-compose", "terraform",
    "kubectl", "helm", "bazel", "buck2", "nx", "turbo", "lerna", "cmake", "ctest",
    "meson", "ninja", "sbt", "lein", "clojure", "stack", "cabal", "zig", "git",
    "gh", "bash", "sh", "pwsh", "mise", "asdf", "nvm", "corepack", "wrangler",
    "supabase", "prisma", "drizzle-kit", "alembic", "django-admin", "flask",
    "uvicorn", "pnpx", "tsx", "ts-node", "cypress", "storybook", "rye", "pixi",
}

JS_PMS = ("npm", "pnpm", "yarn", "bun")
PM_BUILTINS = {
    "npm": {"install", "i", "ci", "add", "exec", "init", "run", "run-script",
            "test", "t", "start", "stop", "restart", "publish", "update", "audit",
            "outdated", "ls", "list", "link", "pack", "version", "uninstall",
            "rm", "prune", "rebuild", "dedupe", "doctor", "cache", "config",
            "view", "info", "why", "explain", "login", "whoami", "create", "x"},
    "pnpm": {"install", "i", "add", "remove", "rm", "update", "up", "exec", "dlx",
             "run", "test", "t", "start", "create", "publish", "store", "why",
             "list", "ls", "outdated", "audit", "prune", "rebuild", "link",
             "unlink", "import", "fetch", "patch", "patch-commit", "deploy",
             "env", "init", "setup", "dedupe", "licenses", "config", "pack",
             "approve-builds", "self-update", "-r", "--filter", "-F", "-C", "--dir",
             "-w", "--workspace-root", "recursive", "m", "multi"},
    "yarn": {"install", "add", "remove", "up", "upgrade", "run", "exec", "dlx",
             "test", "start", "create", "workspace", "workspaces", "info", "why",
             "set", "config", "init", "pack", "npm", "plugin", "cache", "link",
             "unlink", "dedupe", "constraints", "version", "global", "audit", "node",
             "bin", "outdated", "upgrade-interactive"},
    "bun": {"install", "i", "add", "remove", "rm", "update", "run", "x", "test",
            "build", "create", "init", "link", "unlink", "pm", "upgrade", "outdated",
            "publish", "patch", "exec", "repl", "audit", "why", "info"},
}
PURPOSES = [
    ("install", re.compile(r"^\S+ (install|ci|sync|i|bootstrap|setup)\b")),
    ("test", re.compile(r"\b(test|tests|pytest|vitest|jest|rspec|phpunit|ctest|spec|check:test)\b")),
    ("lint", re.compile(r"\b(lint|eslint|ruff check|flake8|golangci-lint|clippy|biome lint)\b")),
    ("typecheck", re.compile(r"\b(typecheck|type-check|tsc|mypy|pyright|check-types|types)\b")),
    ("format", re.compile(r"\b(format|fmt|prettier|black|ruff format|biome format)\b")),
    ("build", re.compile(r"\b(build|compile)\b")),
    ("dev", re.compile(r"\b(dev|start|serve|watch)\b")),
]

PATH_EXTS = ("md", "mdx", "txt", "json", "jsonc", "yaml", "yml", "toml", "ini", "cfg",
             "lock", "py", "pyi", "js", "mjs", "cjs", "jsx", "ts", "mts", "cts", "tsx",
             "go", "rs", "java", "kt", "kts", "rb", "php", "cs", "fs", "swift", "c",
             "h", "cc", "cpp", "hpp", "sh", "bash", "ps1", "bat", "sql", "proto",
             "graphql", "gql", "css", "scss", "html", "vue", "svelte", "astro",
             "env", "example", "xml", "gradle", "csproj", "sln", "tf", "dockerfile",
             "mk", "lua", "ex", "exs", "dart", "zig", "prisma", "mdc")
PATH_RE = re.compile(r"^(?:\./)?[A-Za-z0-9_.@\-\[\]]+(?:/[A-Za-z0-9_.@\-\[\]*]+)*/?$")
KNOWN_DOTFILES = {
    ".nvmrc", ".node-version", ".python-version", ".ruby-version", ".tool-versions",
    ".gitignore", ".gitattributes", ".editorconfig", ".env", ".env.example", ".npmrc",
    ".yarnrc.yml", ".prettierrc", ".eslintrc", ".eslintignore", ".prettierignore",
    ".dockerignore", ".pre-commit-config.yaml", ".golangci.yml", ".golangci.yaml",
    ".cursorrules", ".windsurfrules", ".clinerules", ".mise.toml", ".swiftlint.yml",
    ".rubocop.yml", ".flake8", ".pylintrc", ".coveragerc", ".babelrc", ".browserslistrc",
}
GENERATED_HINTS = ("dist/", "build/", "out/", "target/", "coverage/", ".next/",
                   "node_modules/", ".venv/", "__pycache__/", "bin/", "obj/",
                   ".env", ".drift/", "tmp/", "logs/", ".turbo/")

VERSION_SOURCES_RE = re.compile(
    r"\b(Node(?:\.js|JS)?|Python|Go|Golang|Ruby|Java|JDK|Rust|pnpm|Yarn|Bun|Deno)"
    r"\s*(?:version\s*|v|>=\s*|\^|~)?\s*(\d+(?:\.\d+){0,2})(\+)?", re.I)

RISKY = [
    (r"\brm\s+-[a-zA-Z]*[rf]", "deletes files"),
    (r"\bRemove-Item\b.*-Recurse", "deletes files"),
    (r"\bgit\s+(push|reset|clean|checkout|switch|stash|rebase|commit|merge|tag)\b", "changes git state"),
    (r"\b(npm|pnpm|yarn|bun)\s+(publish|deprecate|unpublish|login)\b", "publishes"),
    (r"\b(twine|gem|cargo|poetry|uv|hatch|flit)\s+(upload|push|publish)\b", "publishes"),
    (r"\bdocker\s+(push|login)\b", "publishes"),
    (r"\bterraform\s+(apply|destroy|import)\b", "changes infrastructure"),
    (r"\b(kubectl|helm)\s+(apply|delete|install|upgrade|rollout)\b", "changes infrastructure"),
    (r"\b(deploy|release|publish)\b", "deploys or releases"),
    (r"\b(migrate|migration|db:(push|reset|drop|seed)|prisma\s+db|drizzle-kit\s+push|alembic\s+upgrade)\b", "changes a database"),
    (r"\bsudo\b", "needs elevated rights"),
    (r"(curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(ba|z)?sh\b|\|\s*iex\b", "runs a downloaded script"),
    (r"\bdrop\s+(table|database)\b", "changes a database"),
    (r"\b(gh)\s+(release|pr\s+merge|repo\s+(delete|edit))\b", "changes a remote repository"),
    (r"--force\b|\s-f\s+(push)", "forces an overwrite"),
]
TEMPLATE = re.compile(r"<[^>\s]+>|\bpath/to/|\{\{|\bYOUR_|\bxxx\b", re.I)
LONG_RUNNING = re.compile(r"(^|[\s:])(dev|start|serve|watch|storybook)(\s|$)|--watch\b|\bwatch\b")


# ---------------------------------------------------------------- discovery

def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)


def discover(root):
    found = []
    seen = set()
    for path in walk(root):
        r = rel(path, root)
        base = os.path.basename(r)
        tools = None
        for pattern, who in CONTEXT_PATTERNS:
            if fnmatch.fnmatch(r, pattern) or (pattern in NESTABLE and base == pattern):
                tools = who
                break
            if pattern.endswith("/*") and r.startswith(pattern[:-1]) and "/" in r[len(pattern) - 1:]:
                tools = who  # nested dirs under .cursor/rules/ and .github/instructions/
                break
        if tools and "/" in r and base in ("CLAUDE.md", "GEMINI.md") and not r.startswith(".claude/"):
            tools = tools.replace(", copilot (root only)", "")
        if tools and r not in seen:
            seen.add(r)
            entry = {"path": r, "read_by": tools}
            target = alias_target(path, root)
            if target:
                entry["alias_of"] = target
            found.append(entry)
    found.sort(key=lambda f: (f["path"].count("/"), f["path"]))
    return found


def alias_target(path, root):
    """A context file that is a symlink to another file, or a git symlink checked
    out as a tiny text file holding the target path (core.symlinks=false)."""
    if os.path.islink(path):
        return rel(os.path.realpath(path), root)
    try:
        if os.path.getsize(path) > 200:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    t = text.strip()
    if t and "\n" not in t and " " not in t and not t.startswith(("#", "@")):
        cand = os.path.normpath(os.path.join(os.path.dirname(path), t))
        if os.path.isfile(cand):
            return rel(cand, root)
    return None


# ---------------------------------------------------------------- repo facts

def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def load_json(path):
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


class Repo:
    def __init__(self, root):
        self.root = root
        self._pkg = {}
        self.lock_pm = self._lock_pm()
        self.py_tool = self._py_tool()

    def exists(self, relpath):
        return os.path.exists(os.path.join(self.root, relpath))

    def package_json(self, subdir=""):
        if subdir not in self._pkg:
            self._pkg[subdir] = load_json(os.path.join(self.root, subdir, "package.json"))
        return self._pkg[subdir]

    def _lock_pm(self):
        pkg = self.package_json() or {}
        declared = str(pkg.get("packageManager", "")).split("@")[0] or None
        locks = [("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"),
                 ("bun.lock", "bun"), ("package-lock.json", "npm"), ("npm-shrinkwrap.json", "npm")]
        found = [pm for f, pm in locks if self.exists(f)]
        if declared:
            return {"pm": declared, "evidence": "package.json packageManager"}
        if len(set(found)) == 1:
            lock = [f for f, pm in locks if pm == found[0] and self.exists(f)][0]
            return {"pm": found[0], "evidence": lock}
        return None

    def _py_tool(self):
        for f, tool in (("uv.lock", "uv"), ("poetry.lock", "poetry"), ("Pipfile.lock", "pipenv"),
                        ("pdm.lock", "pdm"), ("pixi.lock", "pixi")):
            if self.exists(f):
                return {"tool": tool, "evidence": f}
        return None

    def make_targets(self, subdir=""):
        for name in ("Makefile", "makefile", "GNUmakefile"):
            text = read_text(os.path.join(self.root, subdir, name))
            if text is not None:
                targets = set(re.findall(r"^([A-Za-z0-9_.\-/%]+)\s*:(?!=)", text, re.M))
                for line in re.findall(r"^\.PHONY\s*:(.*)$", text, re.M):
                    targets.update(line.split())
                return name, targets
        return None, set()

    def just_recipes(self, subdir=""):
        for name in ("justfile", "Justfile", ".justfile"):
            text = read_text(os.path.join(self.root, subdir, name))
            if text is not None:
                return name, set(re.findall(r"^@?([A-Za-z0-9_\-]+)(?:\s+[^:=\n]*)?:(?!=)", text, re.M))
        return None, set()

    def task_names(self):
        for name in ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml"):
            text = read_text(os.path.join(self.root, name))
            if text is not None:
                m = re.search(r"^tasks:\s*\n((?:[ \t]+.*\n?|\s*\n)*)", text, re.M)
                body = m.group(1) if m else ""
                return name, set(re.findall(r"^[ \t]{2}([A-Za-z0-9_\-:]+):", body, re.M))
        return None, set()

    def versions(self):
        """Declared toolchain versions: {tool: [(value, source)]}."""
        out = {}

        def add(tool, value, source):
            if value:
                out.setdefault(tool, []).append((value.strip(), source))

        for f in (".nvmrc", ".node-version"):
            t = read_text(os.path.join(self.root, f))
            if t:
                add("node", t.strip().lstrip("v").split()[0], f)
        pkg = self.package_json() or {}
        engines = pkg.get("engines") or {}
        if isinstance(engines, dict):
            add("node", str(engines.get("node", "")), "package.json engines.node")
        pm = str(pkg.get("packageManager", ""))
        if "@" in pm:
            name, ver = pm.split("@", 1)
            add(name, ver.split("+")[0], "package.json packageManager")
        t = read_text(os.path.join(self.root, ".python-version"))
        if t:
            add("python", t.strip().split()[0], ".python-version")
        t = read_text(os.path.join(self.root, "pyproject.toml"))
        if t:
            m = re.search(r'requires-python\s*=\s*["\']([^"\']+)', t)
            if m:
                add("python", m.group(1), "pyproject.toml requires-python")
        t = read_text(os.path.join(self.root, "go.mod"))
        if t:
            m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", t, re.M)
            if m:
                add("go", m.group(1), "go.mod")
        for f in ("rust-toolchain.toml", "rust-toolchain"):
            t = read_text(os.path.join(self.root, f))
            if t:
                m = re.search(r"(\d+\.\d+(?:\.\d+)?)", t)
                if m:
                    add("rust", m.group(1), f)
        t = read_text(os.path.join(self.root, ".ruby-version"))
        if t:
            add("ruby", t.strip().split()[0].replace("ruby-", ""), ".ruby-version")
        t = read_text(os.path.join(self.root, ".tool-versions"))
        if t:
            for line in t.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = {"nodejs": "node"}.get(parts[0], parts[0])
                    add(name, parts[1], ".tool-versions")
        return out

    def ci_commands(self):
        out = []
        wf = os.path.join(self.root, ".github", "workflows")
        if os.path.isdir(wf):
            for name in sorted(os.listdir(wf)):
                if not name.endswith((".yml", ".yaml")):
                    continue
                text = read_text(os.path.join(wf, name)) or ""
                lines = text.splitlines()
                i = 0
                while i < len(lines):
                    m = re.match(r"^(\s*)-?\s*run:\s*(.*)$", lines[i])
                    if m:
                        indent = len(m.group(1))
                        value = m.group(2).strip()
                        if value in ("|", ">", "|-", ">-", "|+"):
                            i += 1
                            while i < len(lines) and (not lines[i].strip() or
                                                      len(lines[i]) - len(lines[i].lstrip()) > indent):
                                cmd = lines[i].strip()
                                if cmd and not cmd.startswith("#"):
                                    out.append({"file": ".github/workflows/" + name, "line": i + 1, "cmd": cmd})
                                i += 1
                            continue
                        if value:
                            out.append({"file": ".github/workflows/" + name, "line": i + 1, "cmd": value.strip("'\"")})
                    i += 1
        return out


# ---------------------------------------------------------------- claims

def strip_frontmatter(lines):
    if lines and lines[0].strip() == "---":
        for i in range(1, min(len(lines), 60)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def extract(path, root):
    """Yield claims from one context file: (kind, line, text)."""
    text = read_text(os.path.join(root, path)) or ""
    lines = text.splitlines()
    start = strip_frontmatter(lines)
    in_fence = False
    fence_lang = ""
    fence_mark = ""
    console = False
    claims = []
    for i in range(start, len(lines)):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"^(\s*)(`{3,}|~{3,})\s*([\w+\-.]*)", line)
        if m and (not in_fence or (stripped.startswith(fence_mark) and stripped.strip("`~") == "")):
            if not in_fence:
                in_fence, fence_mark = True, m.group(2)
                fence_lang = m.group(3).lower()
                console = fence_lang in ("console", "shell-session", "terminal")
            else:
                in_fence = False
            continue
        if in_fence:
            if fence_lang not in SHELL_LANGS:
                continue
            cmd = stripped
            prompt = re.match(r"^(\$|>|PS [^>]*>|%)\s+(.*)$", cmd)
            if prompt:
                cmd = prompt.group(2)
            elif console:
                continue  # output line in a console transcript
            if not cmd or cmd.startswith(("#", "//", "REM ")):
                continue
            cmd = re.sub(r"\s+#\s.*$", "", cmd)
            if looks_like_command(cmd, strict=(fence_lang == "")):
                claims.append(("command", i + 1, cmd))
            continue
        # outside fences: @imports, inline code, links, versions
        if os.path.basename(path) in ("CLAUDE.md", "CLAUDE.local.md", "GEMINI.md") or path.startswith(".claude/"):
            no_code = re.sub(r"`[^`]*`", "", line)
            for imp in re.findall(r"(?:^|\s)@((?:\\ |[^\s`])+)", no_code):
                imp = imp.rstrip(".,;:)").replace("\\ ", " ")
                if "/" in imp or "." in imp or imp in ("README", "AGENTS"):
                    if "@" not in imp and not re.match(r"^[\w.+-]+\.(com|org|io|dev|net)$", imp):
                        claims.append(("import", i + 1, imp))
        for span in re.findall(r"`([^`\n]+)`", line):
            span = span.strip()
            if looks_like_command(span, strict=True):
                claims.append(("command", i + 1, span))
            elif looks_like_path(span):
                claims.append(("path", i + 1, span))
        for target in re.findall(r"\]\(([^)\s#]+)(?:#[^)]*)?\)", line):
            if "://" not in target and not target.startswith(("mailto:", "#")) and looks_like_path(target, link=True):
                claims.append(("path", i + 1, target))
        for m in VERSION_SOURCES_RE.finditer(re.sub(r"`[^`]*`", "", line)):
            claims.append(("version", i + 1, m.group(0).strip()))
    return claims


def first_word(cmd):
    try:
        words = shlex.split(cmd, posix=True)
    except ValueError:
        words = cmd.split()
    while words and re.match(r"^[A-Z_][A-Z0-9_]*=", words[0]):
        words = words[1:]  # FOO=bar cmd
    return words


def looks_like_command(text, strict):
    words = first_word(text)
    if not words:
        return False
    w = words[0]
    if w in KNOWN_TOOLS or w.lower() in KNOWN_TOOLS:
        return len(words) > 1 or not strict or w in ("make", "just", "pytest", "tox", "nox", "cargo", "go")
    if re.match(r"^\.{1,2}/[\w./\-]+$", w):
        return True  # ./scripts/foo.sh
    if not strict and w == "cd":
        return True
    return False


def looks_like_path(text, link=False):
    t = text.strip()
    if not t or " " in t or "://" in t or t.startswith(("~", "$", "-", "<", "@", "{")):
        return False
    if re.search(r"[(){}<>=,;'\"|]", t) or t.startswith("/"):
        return False
    if not PATH_RE.match(t):
        return False
    if t.endswith("/"):
        return "/" in t[:-1] or link or t.count("/") == 1 and len(t) > 2
    last = t.rsplit("/", 1)[-1]
    if "/" not in t and t.startswith("."):
        return t in KNOWN_DOTFILES or t.startswith((".env.", ".eslintrc", ".prettierrc"))
    if "." in last:
        ext = last.rsplit(".", 1)[-1].lower()
        if ext in PATH_EXTS or last.lower() in ("dockerfile", "makefile", "justfile"):
            return True
        if last.startswith(".") and last.count(".") == 1:
            return True  # .nvmrc, .env.example handled above
        return False
    if last in ("Dockerfile", "Makefile", "justfile", "Procfile", "LICENSE", "Gemfile", "Rakefile"):
        return True
    return "/" in t and link


# ---------------------------------------------------------------- checks

def split_segments(cmd):
    """Split a shell line into simple commands, tracking `cd` prefixes."""
    parts = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd)
    cwd = ""
    out = []
    for part in parts:
        words = first_word(part)
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            cwd = os.path.normpath(os.path.join(cwd, words[1])).replace(os.sep, "/")
            if cwd == ".":
                cwd = ""
            out.append(("cd", cwd, words))
            continue
        out.append(("cmd", cwd, words))
    return out


def purpose_of(cmd):
    words = [w for w in first_word(cmd) if not w.startswith("-") and "/" not in w and "<" not in w]
    low = " ".join(words[:4]).lower()
    for name, rx in PURPOSES:
        if rx.search(low):
            return name
    return None


def check_command(repo, cmd):
    """Return a list of (status, detail) for one command claim."""
    results = []
    for kind, cwd, words in split_segments(cmd):
        if kind == "cd":
            if not os.path.isdir(os.path.join(repo.root, cwd)):
                results.append(("missing-path", "`cd %s`: directory does not exist" % cwd))
            continue
        tool = words[0]
        args = words[1:]
        # package-manager script references
        if tool in JS_PMS:
            sub = cwd
            rest = list(args)
            while rest and rest[0] in ("--prefix", "-C", "--dir", "--cwd") and len(rest) > 1:
                sub = os.path.normpath(os.path.join(sub, rest[1])).replace(os.sep, "/")
                rest = rest[2:]
            filtered = any(a in ("--filter", "-F", "-w", "--workspace", "workspace", "-r", "--recursive", "--workspaces", "-ws")
                           or a.startswith(("--filter=", "--workspace=")) for a in rest)
            if repo.lock_pm and repo.lock_pm["pm"] != tool and not (tool == "npm" and rest[:1] in (["install"], ["i"]) and "-g" in rest):
                results.append(("pm-mismatch", "uses %s but the repo uses %s (%s)" % (tool, repo.lock_pm["pm"], repo.lock_pm["evidence"])))
            if filtered or not rest:
                continue
            script = None
            if rest[0] in ("run", "run-script") and len(rest) > 1:
                script = rest[1]
            elif rest[0] in ("test", "t", "start", "stop", "restart") and tool == "npm":
                script = {"t": "test"}.get(rest[0], rest[0])
            elif rest[0] not in PM_BUILTINS.get(tool, ()) and not rest[0].startswith("-"):
                script = rest[0]
            elif tool in ("pnpm", "yarn", "bun") and rest[0] in ("test", "t", "start", "build"):
                script = {"t": "test"}.get(rest[0], rest[0])
                if tool == "bun" and rest[0] in ("test", "build"):
                    script = None  # bun has its own test runner and bundler
            if script:
                pkg = repo.package_json(sub)
                if pkg is None:
                    results.append(("missing-path", "no package.json in %s" % (sub or "the repo root")))
                else:
                    scripts = pkg.get("scripts") or {}
                    if script not in scripts:
                        if script == "start" and repo.exists(os.path.join(sub, "server.js")):
                            continue  # npm start falls back to node server.js
                        near = [s for s in scripts if script in s or s in script]
                        hint = (" (scripts that exist: %s)" % ", ".join(sorted(scripts)[:12])) if scripts else ""
                        if near:
                            hint = " (similar: %s)" % ", ".join(sorted(near)[:5])
                        results.append(("missing-script", "%s script `%s` not in %s%s" % (tool, script, os.path.join(sub, "package.json").replace(os.sep, "/"), hint)))
                    else:
                        results.append(("script-ok", "%s -> `%s`" % (script, scripts[script])))
            continue
        if tool == "make":
            sub = cwd
            rest = list(args)
            if rest[:1] == ["-C"] and len(rest) > 1:
                sub = os.path.join(sub, rest[1])
                rest = rest[2:]
            name, targets = repo.make_targets(sub)
            if name is None:
                results.append(("missing-path", "no Makefile in %s" % (sub or "the repo root")))
            else:
                for t in [a for a in rest if not a.startswith("-") and "=" not in a]:
                    if t not in targets and not any(fnmatch.fnmatch(t, p.replace("%", "*")) for p in targets if "%" in p):
                        results.append(("missing-target", "make target `%s` not in %s" % (t, name)))
            continue
        if tool == "just":
            name, recipes = repo.just_recipes(cwd)
            if name is None:
                results.append(("missing-path", "no justfile"))
            else:
                for t in [a for a in args if not a.startswith("-")][:1]:
                    if t not in recipes:
                        results.append(("missing-target", "just recipe `%s` not in %s" % (t, name)))
            continue
        if tool == "task":
            name, tasks = repo.task_names()
            if name is None:
                results.append(("missing-path", "no Taskfile"))
            else:
                for t in [a for a in args if not a.startswith("-")][:1]:
                    if t not in tasks:
                        results.append(("missing-target", "task `%s` not in %s" % (t, name)))
            continue
        if tool in ("poetry", "pipenv", "pdm", "uv") and repo.py_tool and repo.py_tool["tool"] != tool \
                and args[:1] in (["run"], ["install"], ["sync"], ["add"]):
            results.append(("pm-mismatch", "uses %s but the repo is managed with %s (%s)" % (tool, repo.py_tool["tool"], repo.py_tool["evidence"])))
        # file arguments that must exist
        candidates = []
        if re.match(r"^\.{1,2}/", tool):
            candidates.append(tool)
        for j, a in enumerate(args):
            prev = args[j - 1] if j else ""
            if prev in ("-r", "--requirement", "-c", "--constraint", "-f", "--file", "--config", "-p", "--project", "--manifest-path") or \
                    (tool in ("python", "python3", "py", "node", "bash", "sh", "pwsh", "ruby", "deno", "tsx", "ts-node", "bun") and j == 0 and not a.startswith("-")):
                if looks_like_path(a) or re.match(r"^[\w./\-]+\.\w+$", a):
                    candidates.append(a)
            elif tool in ("go",) and a.startswith("./") and a.endswith("/..."):
                candidates.append(a[:-4] or ".")
            elif tool in ("pytest", "ruff", "mypy", "black", "eslint", "prettier", "tsc", "vitest", "jest", "rspec", "phpunit") \
                    and not a.startswith("-") and ("/" in a or re.search(r"\.\w+$", a)) and "*" not in a and "::" not in a:
                candidates.append(a)
            elif prev in ("-s", "--start-directory", "-t", "--top-level-directory") and "unittest" in args:
                candidates.append(a)
            elif "::" in a and tool == "pytest":
                candidates.append(a.split("::")[0])
        if tool in ("python", "python3", "py") and args[:1] == ["-m"] and len(args) > 1 and args[1] not in ("pytest", "pip", "venv", "http.server", "unittest", "mypy", "ruff", "black", "build", "twine", "flake8", "isort", "pyright", "coverage", "uvicorn", "django", "flask", "tox", "nox", "pre_commit", "ensurepip", "json.tool", "pdb", "timeit", "cProfile", "doctest", "compileall", "py_compile", "zipapp", "pydoc", "site", "hatch", "poetry", "uv"):
            mod = args[1].replace(".", "/")
            if not any(repo.exists(os.path.join(cwd, base, p)) for base in ("", "src")
                       for p in (mod + ".py", os.path.join(mod, "__init__.py"), os.path.join(mod, "__main__.py"))):
                results.append(("missing-path", "`python -m %s`: no module %s.py or package %s/ in the repo (may be an installed package)" % (args[1], mod, mod)))
        for c in candidates:
            p = os.path.normpath(os.path.join(cwd, c))
            if not repo.exists(p) and not any(c.startswith(g) or ("/" + g) in c for g in GENERATED_HINTS):
                results.append(("missing-path", "`%s` does not exist%s" % (c.replace(os.sep, "/"), similar_hint(repo.root, p))))
        if shutil.which(tool) is None and not re.match(r"^\.{1,2}/", tool) and tool not in ("cd",):
            results.append(("tool-not-installed", "`%s` is not on PATH here (not necessarily stale)" % tool))
    return results


def version_claim(repo, versions, text):
    m = VERSION_SOURCES_RE.match(text)
    if not m:
        return None
    name = m.group(1).lower()
    name = {"node.js": "node", "nodejs": "node", "golang": "go", "jdk": "java"}.get(name, name)
    claimed = m.group(2)
    declared = versions.get(name)
    if not declared:
        return ("version-unchecked", "no %s version declared in the repo to compare with" % name)
    problems = []
    for value, source in declared:
        if not version_compatible(name, claimed, value, bool(m.group(3))):
            problems.append("%s says %s" % (source, value))
    if problems:
        return ("version-mismatch", "claims %s %s; %s" % (name, claimed, "; ".join(problems)))
    return ("version-ok", "matches " + ", ".join("%s (%s)" % (v, s) for v, s in declared))


def _nums(v):
    return [int(x) for x in re.findall(r"\d+", v)[:3]]


def version_compatible(tool, claimed, declared, plus):
    c = _nums(claimed)
    if not c:
        return True
    depth = 2 if tool in ("python", "go") and len(c) > 1 else 1
    bounds = re.findall(r"(>=|<=|==|~=|>|<|\^|~)?\s*v?(\d+(?:\.\d+)*)", declared)
    if not bounds:
        return True
    for op, ver in bounds:
        d = _nums(ver)[:depth]
        claim = c[:depth]
        if op in (">=", ">", "^", "~", "~="):
            if claim < d:
                return False  # the doc names a version below the minimum
        elif op in ("<", "<="):
            if claim > d or (op == "<" and claim == d and len(_nums(ver)) <= depth):
                return False
        elif plus:
            if claim > d:
                return False  # "Node 24+" but the repo pins 22
        elif claim != d:
            return False
    return True


def loading_findings(repo, files):
    """Context files a tool will silently not load, or will truncate."""
    out = []
    paths = {f["path"] for f in files}
    aliases = {f["path"]: f.get("alias_of") for f in files}
    for f in files:
        if f.get("alias_of"):
            out.append({"file": f["path"], "line": 0, "status": "alias-info",
                        "detail": "symlink to %s; on checkouts without symlink support (Windows default) it is a short text file holding that path" % f["alias_of"]})
    root_claude = [p for p in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md") if p in paths]
    if any(aliases.get(p) == "AGENTS.md" for p in root_claude):
        root_claude = []
    if "AGENTS.md" in paths and root_claude:
        imports = any(re.search(r"(?:^|\s)@\.?/?AGENTS\.md\b", re.sub(r"`[^`]*`", "", read_text(os.path.join(repo.root, p)) or ""))
                      for p in root_claude)
        if not imports:
            out.append({"file": "AGENTS.md", "line": 0, "status": "not-loaded",
                        "detail": "Claude Code reads only CLAUDE.md when both exist; nothing imports @AGENTS.md, so Claude never sees AGENTS.md"})
    if "AGENTS.md" in paths and "GEMINI.md" not in paths:
        settings = read_text(os.path.join(repo.root, ".gemini", "settings.json")) or ""
        if "AGENTS.md" not in settings:
            out.append({"file": "AGENTS.md", "line": 0, "status": "not-loaded-info",
                        "detail": "Gemini CLI reads GEMINI.md by default; it reads AGENTS.md only if .gemini/settings.json lists it in context.fileName"})
    for p in paths:
        if p.startswith(".cursor/rules/") and not p.endswith(".mdc"):
            out.append({"file": p, "line": 0, "status": "not-loaded",
                        "detail": "Cursor only reads .mdc files in .cursor/rules/; this file is ignored"})
        if p.startswith(".github/instructions/") and not p.endswith(".instructions.md"):
            out.append({"file": p, "line": 0, "status": "not-loaded",
                        "detail": "Copilot only reads files ending .instructions.md in .github/instructions/"})
        if p.startswith(".github/instructions/") and p.endswith(".instructions.md"):
            head = (read_text(os.path.join(repo.root, p)) or "")[:600]
            if not re.search(r"^applyTo:", head, re.M):
                out.append({"file": p, "line": 0, "status": "not-loaded-info",
                            "detail": "no applyTo: frontmatter, so Copilot does not apply it automatically"})
        if os.path.basename(p) in ("CLAUDE.md", "GEMINI.md") and "/" in p and not p.startswith(".claude/"):
            pass  # nested: fine for Claude/Gemini; Copilot reads root only
        if os.path.basename(p) == "CLAUDE.md" or p.startswith(".claude/rules/"):
            n = len((read_text(os.path.join(repo.root, p)) or "").splitlines())
            if n > 200:
                out.append({"file": p, "line": 0, "status": "too-long",
                            "detail": "%d lines; Claude Code docs recommend under 200 per file" % n})
    agents = [p for p in paths if os.path.basename(p) in ("AGENTS.md", "AGENTS.override.md")]
    for p in agents:
        chain = [q for q in agents if os.path.dirname(q) == "" or p.startswith(os.path.dirname(q) + "/")]
        size = sum(os.path.getsize(os.path.join(repo.root, q)) for q in set(chain))
        if size > 32 * 1024:
            out.append({"file": p, "line": 0, "status": "truncated",
                        "detail": "AGENTS.md chain is %d KiB; Codex stops adding files at 32 KiB by default" % (size // 1024)})
    return out


def scope_of(path):
    """Directory a context file governs. Tool-specific folders govern the root."""
    if path.startswith((".github/", ".cursor/", ".claude/", ".windsurf/", ".clinerules/", ".junie/")):
        return ""
    return os.path.dirname(path)


def contradictions(command_claims):
    """Same purpose, different commands, in different files that govern the same directory."""
    out = []
    scopes = sorted({scope_of(c["file"]) for c in command_claims})
    for scope in scopes:
        out.extend(_contradictions([c for c in command_claims if scope_of(c["file"]) == scope], scope))
    return out


def _contradictions(command_claims, scope):
    by_purpose = {}
    for c in command_claims:
        p = purpose_of(c["claim"])
        if p and p not in ("install", "dev"):
            by_purpose.setdefault(p, {}).setdefault(normalise(c["claim"]), set()).add(c["file"])
    out = []
    for purpose, cmds in sorted(by_purpose.items()):
        files = set().union(*cmds.values())
        if len(cmds) > 1 and len(files) > 1:
            groups = ["`%s` (%s)" % (cmd, ", ".join(sorted(fs))) for cmd, fs in sorted(cmds.items())]
            if all(len(fs) == 1 for fs in cmds.values()) and len({next(iter(fs)) for fs in cmds.values()}) == 1:
                continue
            out.append({"purpose": purpose, "scope": scope or ".", "variants": groups})
    pms = {}
    for c in command_claims:
        w = first_word(c["claim"])
        if w and w[0] in JS_PMS:
            pms.setdefault(w[0], set()).add(c["file"])
    if len(pms) > 1:
        out.append({"purpose": "package manager", "scope": scope or ".",
                    "variants": ["%s (%s)" % (pm, ", ".join(sorted(fs))) for pm, fs in sorted(pms.items())]})
    return out


def normalise(cmd):
    return re.sub(r"\s+", " ", cmd.strip())


# ---------------------------------------------------------------- scan

def scan(root):
    repo = Repo(root)
    files = discover(root)
    versions = repo.versions()
    findings = []
    command_claims = []
    n = 0
    for f in files:
        if f.get("alias_of"):
            continue  # same content as its target; checked there
        for kind, line, text in extract(f["path"], root):
            n += 1
            entry = {"id": "c%d" % n, "file": f["path"], "line": line, "kind": kind, "claim": text}
            if kind == "command":
                res = check_command(repo, text)
                here = os.path.dirname(f["path"])
                if here and any(r[0] in PROBLEM for r in res):
                    alt = check_command(repo, "cd %s && %s" % (here, text))
                    if sum(r[0] in PROBLEM for r in alt) < sum(r[0] in PROBLEM for r in res):
                        res = [r for r in alt]
                        entry["run_from"] = here
                bad = [r for r in res if r[0] not in ("script-ok", "tool-not-installed")]
                entry["status"] = bad[0][0] if bad else "unverified"
                entry["detail"] = "; ".join(d for _, d in (bad or res)) or "not run yet"
                entry["purpose"] = purpose_of(text)
                entry["risky"] = risky_reason(text)
                entry["long_running"] = bool(LONG_RUNNING.search(text))
                entry["template"] = bool(TEMPLATE.search(text))
                command_claims.append(entry)
            elif kind in ("path", "import"):
                base = os.path.dirname(f["path"])
                target = text.lstrip("./") if text.startswith("./") else text
                cands = [os.path.normpath(os.path.join(base, text)), os.path.normpath(text)]
                if kind == "import" and text.startswith("~"):
                    entry["status"], entry["detail"] = "personal-import", "imports a file from the home directory; not checked"
                elif any(repo.exists(c) or (("*" in c) and glob_any(root, c)) for c in cands):
                    entry["status"], entry["detail"] = "ok", "exists"
                elif suffix_match(root, target):
                    entry["status"] = "ok"
                    entry["detail"] = "found as %s" % ", ".join(suffix_match(root, target)[:2])
                elif any(target.startswith(g) or ("/" + g) in target for g in GENERATED_HINTS) or                         (target.startswith(".") and "/" in target and not repo.exists(target.split("/")[0])):
                    entry["status"], entry["detail"] = "generated", "missing, but looks like a build output or a local/runtime config path"
                elif "/" not in target and kind == "path":
                    entry["status"] = "unresolved-name"
                    entry["detail"] = "no file with this name anywhere in the repo (may be a file the agent is told to create)" + (similar_hint(root, cands[0]) or similar_hint(root, cands[1]))
                else:
                    found = find_by_name(root, os.path.basename(target.rstrip("/")))
                    entry["status"] = "missing-import" if kind == "import" else "missing-path"
                    entry["detail"] = "does not exist" + (" (same name found at: %s)" % ", ".join(found[:3]) if found
                                                          else similar_hint(root, cands[0]) or similar_hint(root, cands[1]))
            elif kind == "version":
                res = version_claim(repo, versions, text)
                if res is None:
                    continue
                entry["status"], entry["detail"] = res
            findings.append(entry)
    return {
        "root": os.path.abspath(root),
        "context_files": files,
        "package_manager": repo.lock_pm,
        "python_tool": repo.py_tool,
        "declared_versions": {k: v for k, v in versions.items()},
        "ci_commands": repo.ci_commands(),
        "claims": findings,
        "loading": loading_findings(repo, files),
        "contradictions": contradictions(command_claims),
    }


_name_index = {}


def find_by_name(root, name):
    if not name:
        return []
    if root not in _name_index:
        idx = {}
        for p in walk(root):
            idx.setdefault(os.path.basename(p), []).append(rel(p, root))
            d = os.path.dirname(p)
            idx.setdefault(os.path.basename(d), []).append(rel(d, root) + "/")
        _name_index[root] = idx
    return sorted(set(_name_index[root].get(name, [])))


_all_paths = {}


def suffix_match(root, claim):
    """Paths in the repo that end with the claimed path (docs often drop a prefix)."""
    claim = claim.strip("/").lstrip("./")
    if not claim:
        return []
    if root not in _all_paths:
        paths = []
        for p in walk(root):
            r = rel(p, root)
            paths.append(r)
            d = os.path.dirname(r)
            while d:
                paths.append(d)
                d = os.path.dirname(d)
        _all_paths[root] = sorted(set(paths))
    return [p for p in _all_paths[root] if p == claim or p.endswith("/" + claim)]


def similar_hint(root, relpath):
    """Suggest close names next to a missing path: the usual rename case."""
    import difflib
    relpath = relpath.rstrip("/\\")
    parent, name = os.path.split(relpath)
    d = os.path.join(root, parent)
    while parent and not os.path.isdir(d):
        parent, name = os.path.split(parent)
        d = os.path.join(root, parent)
    try:
        entries = [e for e in os.listdir(d) if e not in SKIP_DIRS]
    except OSError:
        return ""
    close = difflib.get_close_matches(name, entries, n=3, cutoff=0.5)
    if not close:
        return ""
    return " (similar in %s: %s)" % ((parent or ".").replace(os.sep, "/") + "/", ", ".join(close))


def glob_any(root, pattern):
    import glob
    return bool(glob.glob(os.path.join(root, pattern), recursive=True))


def risky_reason(cmd):
    for rx, why in RISKY:
        if re.search(rx, cmd, re.I):
            return why
    return None


PROBLEM = ("missing-path", "missing-script", "missing-target", "missing-import", "pm-mismatch",
           "version-mismatch")


def print_scan(result, verbose):
    files = result["context_files"]
    print("Context files: %d" % len(files))
    for f in files:
        print("  %-45s read by: %s" % (f["path"], f["read_by"]))
    pm = result["package_manager"]
    if pm:
        print("JS package manager: %s (%s)" % (pm["pm"], pm["evidence"]))
    if result["python_tool"]:
        print("Python tool: %s (%s)" % (result["python_tool"]["tool"], result["python_tool"]["evidence"]))
    claims = result["claims"]
    problems = [c for c in claims if c["status"] in PROBLEM]
    print("\nProblems (%d):" % len(problems))
    for c in problems:
        print("  [%s] %s:%d  %s\n      %s" % (c["status"], c["file"], c["line"], c["claim"], c["detail"]))
    if result["loading"]:
        print("\nLoading (%d):" % len(result["loading"]))
        aliases = [l for l in result["loading"] if l["status"] == "alias-info"]
        if aliases:
            print("  [alias-info] %d context file(s) are symlinks to another context file (e.g. %s -> %s); "
                  "checked once, through the target" % (len(aliases), aliases[0]["file"],
                                                         aliases[0]["detail"].split(";")[0].replace("symlink to ", "")))
        for l in result["loading"]:
            if l["status"] != "alias-info":
                print("  [%s] %s  %s" % (l["status"], l["file"], l["detail"]))
    if result["contradictions"]:
        print("\nDiffering commands across files (%d):" % len(result["contradictions"]))
        for c in result["contradictions"]:
            print("  %s (in %s): %s" % (c["purpose"], c["scope"], " vs ".join(c["variants"])))
    cmds = [c for c in claims if c["kind"] == "command" and c["status"] not in PROBLEM]
    print("\nCommands to verify by running (%d):" % len(cmds))
    for c in cmds:
        tag = " [refuse: %s]" % c["risky"] if c["risky"] else (
            " [template: fill in, then run with --cmd]" if c.get("template") else
            (" [long-running]" if c["long_running"] else ""))
        print("  %-5s %s:%d  %s%s" % (c["id"], c["file"], c["line"], c["claim"], tag))
    if result["ci_commands"]:
        print("\nCI runs (%d):" % len(result["ci_commands"]))
        for c in result["ci_commands"][:40]:
            print("  %s:%d  %s" % (c["file"], c["line"], c["cmd"]))
    if verbose:
        rest = [c for c in claims if c["status"] not in PROBLEM and c["kind"] != "command"]
        print("\nOther claims (%d):" % len(rest))
        for c in rest:
            print("  [%s] %s:%d  %s  (%s)" % (c["status"], c["file"], c["line"], c["claim"], c["detail"]))
    counts = {}
    for c in claims:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    print("\nSummary: %d claims; %s" % (len(claims), ", ".join("%s %d" % kv for kv in sorted(counts.items()))))


# ---------------------------------------------------------------- run

def find_bash():
    if os.name != "nt":
        return "/bin/sh"
    for cand in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    git = shutil.which("git")
    if git:
        guess = os.path.join(os.path.dirname(os.path.dirname(git)), "bin", "bash.exe")
        if os.path.exists(guess):
            return guess
    return None


def run_one(cmd, root, timeout, long_running, shell_choice):
    start = time.time()
    if shell_choice == "auto":
        sh = find_bash()
        argv = [sh, "-c", cmd] if sh and sh.endswith(".exe") else None
        use_shell = argv is None
    elif shell_choice == "native":
        argv, use_shell = None, True
    else:
        argv, use_shell = [shell_choice, "-c", cmd], False
    try:
        proc = subprocess.Popen(argv if argv else cmd, shell=use_shell, cwd=root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
    except OSError as exc:
        return {"status": "error", "exit": None, "seconds": 0, "tail": str(exc)}
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = "passed" if proc.returncode == 0 else "failed"
        code = proc.returncode
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        out, _ = proc.communicate()
        status = "started" if long_running else "timeout"
        code = None
    text = out.decode("utf-8", errors="replace") if out else ""
    tail = "\n".join(text.strip().splitlines()[-25:])
    return {"status": status, "exit": code, "seconds": round(time.time() - start, 1), "tail": tail}


def kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            proc.kill()
    except Exception:
        pass


def cmd_run(args):
    todo = []
    if args.scan:
        with open(args.scan, encoding="utf-8") as fh:
            data = json.load(fh)
        claims = {c["id"]: c for c in data["claims"] if c["kind"] == "command"}
        ids = args.ids or []
        if args.all:
            ids = [i for i, c in claims.items() if c["status"] not in PROBLEM and not c.get("template")]
        for i in ids:
            if i not in claims:
                print("unknown id %s (not a command claim in %s)" % (i, args.scan), file=sys.stderr)
                return 2
            c = claims[i]
            todo.append({"id": i, "file": c["file"], "line": c["line"], "cmd": c["claim"], "cwd": c.get("run_from")})
    for k, c in enumerate(args.cmd or []):
        todo.append({"id": "cmd%d" % (k + 1), "file": None, "line": None, "cmd": c, "cwd": None})
    if not todo:
        print("nothing to run: pass --scan with --ids/--all, or --cmd", file=sys.stderr)
        return 2
    results = []
    seen = {}
    for t in todo:
        cmd = t["cmd"]
        why = risky_reason(cmd)
        if why and not args.allow_risky:
            r = {"status": "refused", "exit": None, "seconds": 0, "tail": "not run: %s. Verify it by reading the code instead." % why}
        elif (t["cwd"], normalise(cmd)) in seen:
            r = dict(seen[(t["cwd"], normalise(cmd))])
            r["tail"] = "same command as %s" % r.get("same_as", "")
        else:
            lr = bool(LONG_RUNNING.search(cmd))
            timeout = args.long_timeout if lr else args.timeout
            where = os.path.join(args.root, t["cwd"]) if t["cwd"] else args.root
            print("running %s: %s%s" % (t["id"], cmd, " (in %s)" % t["cwd"] if t["cwd"] else ""), flush=True)
            r = run_one(cmd, where, timeout, lr, args.shell)
            r["same_as"] = t["id"]
            seen[(t["cwd"], normalise(cmd))] = r
        r = dict(r)
        r.pop("same_as", None)
        t.update(r)
        results.append(t)
        print("  -> %s%s (%.1fs)" % (r["status"], "" if r["exit"] is None else " exit %s" % r["exit"], r["seconds"]))
        if r["status"] in ("failed", "timeout", "error", "refused") and r["tail"]:
            for line in r["tail"].splitlines()[-8:]:
                print("     | " + line)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        prev = []
        if os.path.exists(args.out):
            try:
                with open(args.out, encoding="utf-8") as fh:
                    prev = json.load(fh).get("runs", [])
            except ValueError:
                prev = []
        done = {r["id"] for r in results}
        merged = [p for p in prev if p["id"] not in done] + results
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"root": os.path.abspath(args.root), "runs": merged}, fh, indent=2)
    bad = [r for r in results if r["status"] in ("failed", "timeout", "error")]
    return 1 if bad else 0


def cmd_scan(args):
    result = scan(args.root)
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
    print_scan(result, args.verbose)
    problems = [c for c in result["claims"] if c["status"] in PROBLEM]
    return 1 if (problems or any(l["status"] in ("not-loaded", "truncated") for l in result["loading"])) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("scan", help="find context files and check their claims")
    s.add_argument("--root", default=".")
    s.add_argument("--json", help="also write the full result as JSON to this path")
    s.add_argument("-v", "--verbose", action="store_true", help="also list claims that checked out")
    r = sub.add_parser("run", help="run documented commands safely and record the outcome")
    r.add_argument("--root", default=".")
    r.add_argument("--scan", help="scan JSON written by `scan --json`")
    r.add_argument("--ids", nargs="*", help="command claim ids from the scan (c3 c7 ...)")
    r.add_argument("--all", action="store_true", help="run every command claim that passed the static checks")
    r.add_argument("--cmd", action="append", help="a command to run (repeatable)")
    r.add_argument("--timeout", type=int, default=600, help="seconds before a normal command counts as hung")
    r.add_argument("--long-timeout", type=int, default=25, help="seconds to let dev/watch/serve commands run; still up = started")
    r.add_argument("--shell", default="auto", help="auto (POSIX sh, Git Bash on Windows), native, or a shell path")
    r.add_argument("--allow-risky", action="store_true", help="also run commands that deploy, publish, push or delete")
    r.add_argument("--out", help="merge results into this JSON file")
    args = p.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "run":
        return cmd_run(args)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
