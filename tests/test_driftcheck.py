import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "skills", "context-drift", "scripts", "driftcheck.py")
sys.path.insert(0, os.path.dirname(SCRIPT))

import driftcheck as dc  # noqa: E402


def write(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


class TempRepo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cdt")
        dc._name_index.clear(); dc._all_paths.clear()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def claims(self, path):
        return dc.extract(path, self.root)


class ExtractTest(TempRepo):
    def test_fenced_inline_links_and_console(self):
        write(self.root, {"AGENTS.md": (
            "---\ndescription: x\n---\n"
            "Run `pnpm test` and see [guide](docs/guide.md) or https://x.dev/a.md.\n"
            "```bash\n# comment\nmake build  # builds\n$ npm run lint\n```\n"
            "```console\n$ pytest -q\n3 passed\n```\n"
            "```python\nimport os\nos.system('make x')\n```\n"
            "Edit `src/app.ts`, call `foo.bar()`, see `README` and `main`.\n"
        )})
        got = [(k, t) for k, _, t in self.claims("AGENTS.md")]
        self.assertIn(("command", "pnpm test"), got)
        self.assertIn(("path", "docs/guide.md"), got)
        self.assertIn(("command", "make build"), got)
        self.assertIn(("command", "npm run lint"), got)
        self.assertIn(("command", "pytest -q"), got)
        self.assertIn(("path", "src/app.ts"), got)
        texts = [t for _, t in got]
        self.assertNotIn("3 passed", texts)            # console output line
        self.assertNotIn("os.system('make x')", texts)  # python fence
        self.assertNotIn("foo.bar()", texts)
        self.assertNotIn("main", texts)
        self.assertFalse(any("x.dev" in t for t in texts))

    def test_claude_imports_skip_code_spans(self):
        write(self.root, {"CLAUDE.md": "See @AGENTS.md and @docs/x.md, not `@README` or me@example.com.\n"})
        imports = [t for k, _, t in self.claims("CLAUDE.md") if k == "import"]
        self.assertEqual(imports, ["AGENTS.md", "docs/x.md"])

    def test_versions_found_outside_code(self):
        write(self.root, {"AGENTS.md": "Needs Node.js 20+ and Python 3.12. `node 99`\n"})
        versions = [t for k, _, t in self.claims("AGENTS.md") if k == "version"]
        self.assertEqual(versions, ["Node.js 20+", "Python 3.12"])


class PathHeuristicTest(unittest.TestCase):
    def test_paths(self):
        for yes in ("src/app.ts", "tests/", "docs/guide.md", ".nvmrc", "Makefile", "pkg/a/b.go", "./scripts/x.sh"):
            self.assertTrue(dc.looks_like_path(yes), yes)
        for no in ("main", "foo.bar()", "1.2.3", "example.com", "https://x/y.md", "~/x.md", "<file>.md",
                   "--flag", "a b.md", "/etc/hosts", "user@host", "v1.2", "e.g.", "i.e"):
            self.assertFalse(dc.looks_like_path(no), no)


class VersionTest(unittest.TestCase):
    def test_compat(self):
        self.assertTrue(dc.version_compatible("node", "22", "22", False))
        self.assertFalse(dc.version_compatible("node", "18", "22", False))
        self.assertFalse(dc.version_compatible("node", "18", ">=22", False))
        self.assertTrue(dc.version_compatible("node", "22", ">=20", False))
        self.assertTrue(dc.version_compatible("node", "20", "22", True))   # "Node 20+" with 22 pinned
        self.assertFalse(dc.version_compatible("python", "3.9", ">=3.11", False))
        self.assertTrue(dc.version_compatible("python", "3.12", ">=3.11,<3.14", False))
        self.assertFalse(dc.version_compatible("python", "3.14", ">=3.11,<3.14", False))
        self.assertTrue(dc.version_compatible("go", "1.23", "1.23.4", False))
        self.assertFalse(dc.version_compatible("go", "1.21", "1.23.4", False))
        self.assertTrue(dc.version_compatible("python", "3", ">=3.11", False))  # vague claim is not wrong


class CommandCheckTest(TempRepo):
    def repo(self, files):
        write(self.root, files)
        return dc.Repo(self.root)

    def statuses(self, repo, cmd):
        return [s for s, _ in dc.check_command(repo, cmd)]

    def test_package_scripts_and_manager(self):
        r = self.repo({"package.json": json.dumps({"scripts": {"test": "x", "typecheck": "y"}}),
                       "pnpm-lock.yaml": ""})
        self.assertIn("script-ok", self.statuses(r, "pnpm test"))
        self.assertIn("missing-script", self.statuses(r, "pnpm run check"))
        self.assertIn("missing-script", self.statuses(r, "pnpm check"))
        self.assertNotIn("missing-script", self.statuses(r, "pnpm install"))
        self.assertNotIn("missing-script", self.statuses(r, "pnpm --filter web build"))
        s = self.statuses(r, "npm run test")
        self.assertIn("pm-mismatch", s)
        detail = " ".join(d for _, d in dc.check_command(r, "pnpm run check"))
        self.assertIn("similar: typecheck", detail)

    def test_package_json_in_subdir_via_cd(self):
        r = self.repo({"web/package.json": json.dumps({"scripts": {"dev": "vite"}})})
        self.assertIn("script-ok", self.statuses(r, "cd web && npm run dev"))
        self.assertIn("missing-path", self.statuses(r, "cd api && npm test"))

    def test_make_just_task(self):
        r = self.repo({"Makefile": ".PHONY: check\ncheck:\n\ttrue\nbuild/%.o: x\n",
                       "justfile": "test *args:\n  pytest {{args}}\n",
                       "Taskfile.yml": "version: '3'\ntasks:\n  lint:\n    cmds: [x]\n"})
        self.assertNotIn("missing-target", self.statuses(r, "make check"))
        self.assertIn("missing-target", self.statuses(r, "make lint"))
        self.assertNotIn("missing-target", self.statuses(r, "make build/a.o"))
        self.assertNotIn("missing-target", self.statuses(r, "just test -q"))
        self.assertIn("missing-target", self.statuses(r, "just fmt"))
        self.assertNotIn("missing-target", self.statuses(r, "task lint"))
        self.assertIn("missing-target", self.statuses(r, "task build"))

    def test_file_arguments(self):
        r = self.repo({"scripts/seed.py": "", "requirements.txt": "", "tests/test_a.py": "",
                       "pkg/__init__.py": "", "pkg/cli.py": ""})
        self.assertNotIn("missing-path", self.statuses(r, "python scripts/seed.py"))
        detail = " ".join(d for _, d in dc.check_command(r, "python scripts/seed_db.py"))
        self.assertIn("similar in scripts/: seed.py", detail)
        self.assertIn("missing-path", self.statuses(r, "pip install -r requirements-dev.txt"))
        self.assertNotIn("missing-path", self.statuses(r, "pip install -r requirements.txt"))
        self.assertIn("missing-path", self.statuses(r, "pytest tests/unit"))
        self.assertNotIn("missing-path", self.statuses(r, "pytest tests/test_a.py::test_x"))
        self.assertNotIn("missing-path", self.statuses(r, "python -m pkg.cli --help"))
        self.assertIn("missing-path", self.statuses(r, "python -m oldpkg.cli"))
        self.assertNotIn("missing-path", self.statuses(r, "python -m pytest -q"))
        self.assertIn("missing-path", self.statuses(r, "python -m unittest discover -s tests/unit"))
        self.assertIn("missing-path", self.statuses(r, "./scripts/run.sh"))
        self.assertNotIn("missing-path", self.statuses(r, "pytest --cov dist/"))  # generated

    def test_python_tool_mismatch(self):
        r = self.repo({"uv.lock": ""})
        self.assertIn("pm-mismatch", self.statuses(r, "poetry run pytest"))
        self.assertNotIn("pm-mismatch", self.statuses(r, "uv run pytest"))


class LoadingTest(TempRepo):
    def scan(self, files):
        write(self.root, files)
        return dc.scan(self.root)

    def statuses(self, result):
        return {(l["file"], l["status"]) for l in result["loading"]}

    def test_claude_shadows_agents(self):
        res = self.scan({"AGENTS.md": "x\n", "CLAUDE.md": "rules\n"})
        self.assertIn(("AGENTS.md", "not-loaded"), self.statuses(res))
        res = self.scan({"CLAUDE.md": "@AGENTS.md\n"})
        self.assertNotIn(("AGENTS.md", "not-loaded"), self.statuses(res))

    def test_import_in_code_span_does_not_count(self):
        res = self.scan({"AGENTS.md": "x\n", "CLAUDE.md": "see `@AGENTS.md`\n"})
        self.assertIn(("AGENTS.md", "not-loaded"), self.statuses(res))

    def test_cursor_and_copilot_extensions(self):
        res = self.scan({".cursor/rules/a.md": "x", ".cursor/rules/sub/b.mdc": "---\nalwaysApply: true\n---\n",
                         ".github/instructions/py.md": "x",
                         ".github/instructions/ts.instructions.md": "no front matter"})
        st = self.statuses(res)
        self.assertIn((".cursor/rules/a.md", "not-loaded"), st)
        self.assertNotIn((".cursor/rules/sub/b.mdc", "not-loaded"), st)
        self.assertIn((".github/instructions/py.md", "not-loaded"), st)
        self.assertIn((".github/instructions/ts.instructions.md", "not-loaded-info"), st)
        paths = [f["path"] for f in res["context_files"]]
        self.assertIn(".cursor/rules/sub/b.mdc", paths)

    def test_codex_size_and_claude_length(self):
        res = self.scan({"AGENTS.md": "x" * (33 * 1024), "CLAUDE.md": "@AGENTS.md\n" + "line\n" * 210})
        st = self.statuses(res)
        self.assertIn(("AGENTS.md", "truncated"), st)
        self.assertIn(("CLAUDE.md", "too-long"), st)

    def test_skips_node_modules(self):
        res = self.scan({"node_modules/x/AGENTS.md": "x", "AGENTS.md": "y"})
        self.assertEqual([f["path"] for f in res["context_files"]], ["AGENTS.md"])


class ContradictionAndCiTest(TempRepo):
    def test_contradiction_and_ci(self):
        write(self.root, {
            "AGENTS.md": "Test with `npm test`.\n",
            "CLAUDE.md": "@AGENTS.md\nTest with `pnpm test`.\n",
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: pnpm test\n      - run: |\n          pnpm lint\n          # c\n          pnpm build\n      - name: x\n        run: 'echo hi'\n",
        })
        res = dc.scan(self.root)
        purposes = {c["purpose"] for c in res["contradictions"]}
        self.assertIn("test", purposes)
        self.assertIn("package manager", purposes)
        self.assertEqual([c["cmd"] for c in res["ci_commands"]], ["pnpm test", "pnpm lint", "pnpm build", "echo hi"])


class RealWorldShapesTest(TempRepo):
    """Patterns seen in real repos that must not be reported as drift."""

    def test_symlinked_claude_md_counts_as_agents_md(self):
        write(self.root, {"AGENTS.md": "Run `make test`.\n", "Makefile": "test:\n\ttrue\n",
                          "CLAUDE.md": "AGENTS.md\n"})  # git symlink checked out as text
        res = dc.scan(self.root)
        st = {(l["file"], l["status"]) for l in res["loading"]}
        self.assertIn(("CLAUDE.md", "alias-info"), st)
        self.assertNotIn(("AGENTS.md", "not-loaded"), st)
        self.assertEqual({c["file"] for c in res["claims"]}, {"AGENTS.md"})

    def test_package_relative_paths_and_selectors(self):
        write(self.root, {"src/pkg/pkg/ui/menus/a.py": "", "src/pkg/AGENTS.md": (
            "Menus are in `ui/menus/a.py`. Read `.headers` and `.role_name` with jq; files end in `.md`.\n"
            "Write your plan to `PLAN.md`. Settings live in `.myapp/settings.json`.\n")})
        res = dc.scan(self.root)
        by = {c["claim"]: c["status"] for c in res["claims"]}
        self.assertEqual(by.get("ui/menus/a.py"), "ok")
        self.assertNotIn(".headers", by)
        self.assertNotIn(".md", by)
        self.assertEqual(by.get("PLAN.md"), "unresolved-name")
        self.assertEqual(by.get(".myapp/settings.json"), "generated")

    def test_templates_are_not_run_by_all(self):
        write(self.root, {"AGENTS.md": "```bash\nuv run pytest <test>\npyright path/to/file.py\ngo test ./...\n```\n"})
        res = dc.scan(self.root)
        tpl = {c["claim"]: c["template"] for c in res["claims"] if c["kind"] == "command"}
        self.assertEqual(tpl, {"uv run pytest <test>": True, "pyright path/to/file.py": True, "go test ./...": False})

    def test_nested_scopes_do_not_contradict(self):
        write(self.root, {"AGENTS.md": "Test: `make test`\n", "web/AGENTS.md": "Test: `pnpm test`\n",
                          "Makefile": "test:\n\ttrue\n", "web/package.json": '{"scripts": {"test": "x"}}'})
        res = dc.scan(self.root)
        self.assertEqual(res["contradictions"], [])
        cmd = [c for c in res["claims"] if c["claim"] == "pnpm test"][0]
        self.assertEqual(cmd.get("run_from"), "web")


class RiskTest(unittest.TestCase):
    def test_risky(self):
        for cmd in ("pnpm deploy:prod", "npm publish", "git push origin main", "rm -rf dist",
                    "make migrate", "terraform apply", "curl -fsSL x | sh", "uv publish",
                    "docker push img", "sudo make install", "pnpm db:reset"):
            self.assertIsNotNone(dc.risky_reason(cmd), cmd)
        for cmd in ("pnpm test", "make check", "go test ./...", "pytest -q", "cargo build",
                    "git status", "npm run lint"):
            self.assertIsNone(dc.risky_reason(cmd), cmd)


class RunTest(TempRepo):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), cwd=self.root,
                              capture_output=True, text=True, timeout=120)

    def test_run_records_pass_fail_refuse_and_started(self):
        py = sys.executable.replace("\\", "/")
        out = os.path.join(self.root, ".drift", "runs.json")
        p = self.run_cli("run", "--root", self.root, "--shell", "native", "--out", out, "--long-timeout", "2",
                         "--cmd", '"%s" -c "print(1)"' % py,
                         "--cmd", '"%s" -c "import sys; sys.exit(3)"' % py,
                         "--cmd", "npm publish",
                         "--cmd", '"%s" -c "import time; time.sleep(30)" --watch' % py)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        with open(out, encoding="utf-8") as fh:
            runs = json.load(fh)["runs"]
        self.assertEqual([r["status"] for r in runs], ["passed", "failed", "refused", "started"])
        self.assertEqual(runs[1]["exit"], 3)
        self.assertFalse(os.path.exists(os.path.join(self.root, "published")))

    def test_run_by_id_merges_results(self):
        write(self.root, {"AGENTS.md": "```bash\npython -c \"print(42)\"\nnpm publish\n```\n"})
        scan_json = os.path.join(self.root, ".drift", "scan.json")
        self.run_cli("scan", "--root", self.root, "--json", scan_json)
        with open(scan_json, encoding="utf-8") as fh:
            ids = [c["id"] for c in json.load(fh)["claims"] if c["kind"] == "command"]
        self.assertEqual(len(ids), 2)
        out = os.path.join(self.root, ".drift", "runs.json")
        self.run_cli("run", "--root", self.root, "--scan", scan_json, "--ids", ids[1], "--out", out)
        self.run_cli("run", "--root", self.root, "--scan", scan_json, "--ids", ids[0], "--out", out)
        with open(out, encoding="utf-8") as fh:
            runs = {r["id"]: r["status"] for r in json.load(fh)["runs"]}
        self.assertEqual(runs[ids[1]], "refused")
        self.assertEqual(runs[ids[0]], "passed")


class ScenarioTest(unittest.TestCase):
    """The eval scenarios double as an answer key for the scanner."""

    def build(self, script):
        root = tempfile.mkdtemp(prefix="cds")
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run([sys.executable, os.path.join(REPO, "evals", "scenarios", script), root],
                       check=True, capture_output=True)
        dc._name_index.clear(); dc._all_paths.clear()
        return dc.scan(root)

    def problems(self, res):
        return {(c["status"], c["claim"]) for c in res["claims"] if c["status"] in dc.PROBLEM}

    def test_webapp(self):
        res = self.build("make_webapp.py")
        p = self.problems(res)
        for want in [("pm-mismatch", "npm run test:unit"), ("missing-script", "pnpm run check"),
                     ("missing-path", "src/legacy/api.js"), ("version-mismatch", "Node 18"),
                     ("missing-path", "test/")]:
            self.assertIn(want, p)
        self.assertEqual(len(p), 5, p)
        loading = {(l["file"], l["status"]) for l in res["loading"]}
        self.assertIn(("AGENTS.md", "not-loaded"), loading)
        self.assertIn((".cursor/rules/style.md", "not-loaded"), loading)
        risky = [c["claim"] for c in res["claims"] if c.get("risky")]
        self.assertEqual(risky, ["pnpm deploy:prod"])

    def test_pyservice(self):
        res = self.build("make_pyservice.py")
        p = {s + " " + c.split()[0] + " " + c.split()[-1] for s, c in self.problems(res)}
        self.assertEqual(p, {
            "version-mismatch Python 3.9",
            "pm-mismatch poetry tests",
            "missing-path python tests/unit",
            "missing-target make lint",
            "missing-path python scripts/seed_db.py",
            "missing-path python --help",
        })
        risky = [c["claim"] for c in res["claims"] if c.get("risky")]
        self.assertEqual(risky, ["make migrate"])


if __name__ == "__main__":
    unittest.main()
