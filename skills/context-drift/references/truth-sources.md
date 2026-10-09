# Where the truth lives

When a context file and the repo disagree, these decide. CI configuration
outranks everything else for "which command is right": it runs on every change,
so it is the one place stale commands get caught.

| Question | Authority, in order |
|---|---|
| Which commands are real | CI workflows (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `.circleci/config.yml`, `Jenkinsfile`), then the task runner (package.json `scripts`, `Makefile`, `justfile`, `Taskfile.yml`, `pyproject.toml` `[tool.poe]`/`[tool.hatch.envs]`, `tox.ini`, `noxfile.py`, `build.gradle`, `pom.xml`) |
| JS package manager | `package.json` `packageManager`, then the lockfile: `pnpm-lock.yaml` pnpm, `yarn.lock` yarn, `bun.lock`/`bun.lockb` bun, `package-lock.json` npm |
| Python tooling | `uv.lock` uv, `poetry.lock` Poetry, `Pipfile.lock` Pipenv, `pdm.lock` PDM, `pixi.lock` pixi; `[build-system]` in pyproject.toml |
| Language versions | Node: `.nvmrc`, `.node-version`, `engines.node`, `.tool-versions`, `mise.toml`. Python: `.python-version`, `requires-python`. Go: `go.mod` `go` line (and `toolchain`). Rust: `rust-toolchain.toml`, `rust-version` in Cargo.toml. Ruby: `.ruby-version`, Gemfile `ruby`. Java: `.java-version`, Gradle toolchain, Maven `maven.compiler.release` |
| Test runner and test locations | runner config (`vitest.config.*`, `jest.config.*`, `[tool.pytest.ini_options]` `testpaths`, `pytest.ini`, `go test ./...` layout, `phpunit.xml`), then where test files actually are |
| Lint/format tools | config files that exist (`eslint.config.*`, `biome.json`, `.prettierrc*`, `ruff.toml`/`[tool.ruff]`, `.golangci.yml`, `rustfmt.toml`), `.pre-commit-config.yaml` hooks |
| Directory layout | the tree itself (`git ls-files`), not the README |
| Monorepo packages | `pnpm-workspace.yaml`, `workspaces` in package.json, `go.work`, Cargo `[workspace]`, `settings.gradle`, `nx.json`/`turbo.json` |

## Renames to look for

Most drift is a rename someone didn't carry into the docs. When a claim is
missing, look for its successor before deleting it:

- scripts: `test:unit` to `test`, `check` to `typecheck`, `lint:fix` to `lint --fix`, `start` to `dev`
- tools: npm/yarn to pnpm or bun; Poetry/Pipenv/pip-tools to uv; Jest to Vitest; ESLint+Prettier to Biome; flake8/isort/black to Ruff; `docker-compose` to `docker compose`; Mocha to `node --test`
- paths: `src/legacy/*` to new module names, `test/` to `tests/`, `lib/` to `src/`, `app/` to `src/app/`
- packages: the project renamed (`pyproject.toml` `name`, `package.json` `name`, import package directory)

The scan's `(similar: ...)` hints come from these patterns: a close name in the
same directory, or the same file name elsewhere in the tree. Confirm the hint
before using it; a similar name is evidence, not proof.
