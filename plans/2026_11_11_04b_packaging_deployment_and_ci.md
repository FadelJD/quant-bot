# 04b · Packaging, deployment and CI

Created 2026-11-11 · Wave 4 · Parallel with 04a, 04c · Needs wave 3 · Spec sections 5, 13, 17

## Goal

Anyone can install it, the owner can run it unattended three different ways, and CI proves the
tree is healthy on Windows and Ubuntu.

## Owns

`pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.github/`, `Dockerfile`,
`docker-compose.yml`, `deploy/` (new), `scripts/smoke.py`.

## Current state

`pyproject.toml` with extras and dev group, a CI workflow with a matrix, a pre-commit config. No
Dockerfile, no compose file, no supervision files (D15).

## Work items

1. **Wheel.** `uv build` produces a wheel containing `_templates/` and the report template.
   Verify with `pipx install dist/*.whl` in a clean environment, then `kestrel init` and the
   quickstart in an empty folder. Add `py.typed`.
2. **Dependency hygiene.** Lower bounds that were actually resolved, upper bounds only on majors
   known to break. `[ml]` and `[research]` extras. Run the core without extras in CI as its own job.
   Add `pip-audit` (or `uv pip audit` if available) as a non-blocking CI step.
3. **CI workflow.**
   - Matrix: `ubuntu-latest`, `windows-latest` × Python 3.11, 3.12.
   - Steps: `uv sync`, secrets scan, `ruff check`, `ruff format --check`, `mypy --strict`,
     `lint-imports`, smoke gate, `pytest -m "unit or integration" --cov` with the coverage gate
     (enabled when wave 5 lands), wheel build and install check.
   - Benchmark job on Ubuntu only, 60 s target.
   - Cache `uv`. Concurrency group cancels superseded runs. Least-privilege `permissions`.
   - Triggers: pushes to `main`, `develop`, `feat/**`, and PRs to `main` and `develop`.
4. **Pre-commit.** Mirrors CI lint steps; `detect-secrets` with the committed baseline; large-file
   and private-key hooks. Document the one-line install for PowerShell and bash.
5. **Docker.** Multi-stage `Dockerfile` on `python:3.12-slim`, non-root user, `uv` for install,
   only the wheel and its dependencies in the final image, `HEALTHCHECK` reading the heartbeat
   file age (I6). `docker-compose.yml` with `restart: always`, volumes for `state/`, `data/`,
   `logs/`, `reports/`, and `env_file: .env`. Build the image in CI; do not run the loop.
6. **Supervision files under `deploy/`.**
   - `deploy/systemd/kestrel.service`: `Restart=always`, `RestartSec=10`, `EnvironmentFile`,
     hardened (`NoNewPrivileges`, `ProtectSystem=strict`, writable paths listed).
   - `deploy/windows/install-nssm.ps1` and a Task Scheduler XML with restart on failure.
   - Each with a three-line header saying how to install and remove it. 04c's runbook links them.
7. **Log and state housekeeping.** A `kestrel maintenance` entry is not needed; document
   retention (logs 30 days by the handler, state backups by `kestrel state export` from cron or
   Task Scheduler) and ship the two example schedule snippets.
8. **Release mechanics (used by plan 06).** A `release.yml` workflow triggered by a tag on
   `main`: build, attach the wheel and sdist to a GitHub release. No PyPI publish in v1 (owner
   decision recorded).
9. **Repository hygiene.** `CODEOWNERS` not needed; add a PR template with the checklist from
   plan 00 section 4, and `SECURITY.md` stating paper-only and how to report an issue.
10. **Smoke gate, final form.** All steps `required`, under 90 s, same command on both OSes.

## Done when

- CI is green on all four matrix cells with every step except pytest's coverage gate enforced.
- `pipx install` of the built wheel reaches a passing quickstart in an empty folder.
- `docker build` succeeds in CI; the image runs `kestrel doctor` and `kestrel run --rehearse 1d`.
- The systemd unit passes `systemd-analyze verify` (when available); the PowerShell script passes
  `PSScriptAnalyzer` or a syntax parse.
- D15 closed.

## Out of scope

Deploying anywhere. PyPI. Cloud infrastructure code. Tests beyond wiring the CI step.
