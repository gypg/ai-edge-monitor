# Phase C Observability Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add observability ecosystem support, containerized demo execution, lightweight inference workload, and real-device validation templates so the project has AI Infra / MLOps / Edge AI portfolio depth.

**Architecture:** Keep additions optional and stdlib-first: Prometheus text generation consumes existing summary dictionaries, Docker runs the existing CLI, and inference demo is a pure-Python workload so no new runtime dependency is required. Documentation and validation templates sit beside existing reports and changelogs.

**Tech Stack:** Python 3.8+, standard library `http.server`, Docker/Docker Compose manifests, unittest/script-style tests, existing CLI/config/orchestrator/exporter modules.

---

## Files

- Create `src/prometheus_exporter/__init__.py` and `src/prometheus_exporter/exporter.py` for Prometheus text and optional HTTP server.
- Create `tests/prometheus_exporter/test_exporter.py` for output format, values, and empty summaries.
- Modify `pyproject.toml` package discovery and isort first-party list for `prometheus_exporter`.
- Create `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `integration/test_docker_smoke.py`.
- Create `examples/inference_demo.py` for a pure-Python matrix-style inference workload.
- Create `docs/test_report/validation_template_jetson_rpi.md`.
- Modify `README.md` for Prometheus, Docker, inference demo, validation template, module table, and tree.
- Create `docs/changelog/add-phase-c-observability.md`.

## Task 1: Prometheus exporter

- [ ] Write `tests/prometheus_exporter/test_exporter.py` importing `PrometheusExporter`; test HELP/TYPE lines and metrics: `ai_edge_cpu_percent`, `ai_edge_memory_used_bytes`, `ai_edge_power_watts`, `ai_edge_temperature_celsius`.
- [ ] Run `py tests/prometheus_exporter/test_exporter.py`; expected failure: missing `prometheus_exporter` module.
- [ ] Implement `PrometheusExporter.render(summary)` and `PrometheusExporter.render_latest()` in `src/prometheus_exporter/exporter.py`, plus `start_http_server(port)` using stdlib HTTP server.
- [ ] Export API in `src/prometheus_exporter/__init__.py`.
- [ ] Update `pyproject.toml` to include `prometheus_exporter*` and known first-party name.
- [ ] Run `py tests/prometheus_exporter/test_exporter.py`; expected OK.

## Task 2: Docker support

- [ ] Create `integration/test_docker_smoke.py` first; it should detect Docker availability, build `ai-edge-monitor:smoke`, run a 5-second dummy session, and skip with exit 0 when Docker is unavailable.
- [ ] Run `py integration/test_docker_smoke.py`; expected failure before Dockerfile exists if Docker is available, or SKIP if unavailable.
- [ ] Create `Dockerfile` using `python:3.10-slim`, installing `pip install -e .[all]`, default command `ai-edge-monitor --help`.
- [ ] Create `.dockerignore` excluding caches, git/worktrees, reports, node_modules, and generated artifacts.
- [ ] Create `docker-compose.yml` with service `ai-edge-monitor`, mounting `./monitor.yaml:/app/monitor.yaml:ro` and `./reports:/app/reports`, command `ai-edge-monitor run --config /app/monitor.yaml --force-dummy`.
- [ ] Run `py integration/test_docker_smoke.py`; expected OK or SKIP if Docker unavailable.

## Task 3: Inference workload demo

- [ ] Write a testable script `examples/inference_demo.py` with `run_workload(duration_sec, size, progress_interval_sec)` and CLI args `--duration-sec`, `--size`, `--progress-interval-sec`.
- [ ] Run `py examples/inference_demo.py --duration-sec 2 --size 16 --progress-interval-sec 1`; expected progress output and exit 0.
- [ ] Generate or verify dummy inference scenario command remains documented via `ai-edge-monitor scenario --scenario inference`.

## Task 4: Real-device validation template

- [ ] Create `docs/test_report/validation_template_jetson_rpi.md` with device info fields, one-command run, expected result interpretation, result tables, exception log, and dummy comparison guidance.
- [ ] Ensure it is documentation-only and does not claim actual hardware validation.

## Task 5: README and changelog

- [ ] Update README feature bullets for Prometheus metrics, Docker support, and inference workload.
- [ ] Update README Quick Demo or later sections with Docker build/run and workload-monitoring examples.
- [ ] Update module status table with `prometheus_exporter`.
- [ ] Update project structure tree for new files and directories.
- [ ] Add `docs/changelog/add-phase-c-observability.md`.

## Task 6: Final verification and PR

- [ ] Run all unit/baseline tests including `py tests/prometheus_exporter/test_exporter.py`.
- [ ] Run all integration tests including `py integration/test_docker_smoke.py`.
- [ ] Run `py examples/inference_demo.py --duration-sec 2 --size 16 --progress-interval-sec 1`.
- [ ] Run `py -m pre_commit run --all-files`.
- [ ] Commit Phase C changes, push `worktree-phase-c-observability`, and create PR.

## Self-review

- Spec coverage: Prometheus, Docker, inference workload, validation template, README/changelog, tests, final PR are covered.
- Placeholder scan: no deferred implementation placeholders.
- Type consistency: `PrometheusExporter` exposes `render`, `render_latest`, and `start_http_server`; tests and docs use the same names.
