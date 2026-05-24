# Phase B Competitive Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ai-edge-monitor more professional by adding YAML configuration, an orchestration layer, NVIDIA GPU probing, stable CI baseline behavior, and updated portfolio documentation.

**Architecture:** Keep CLI thin: argparse parses flags, `config_manager` merges defaults/file/CLI overrides, and `app_orchestrator.Orchestrator` owns the monitoring lifecycle. `platform_adapter.NvidiaSmiProbe` follows the existing `PlatformProbe` contract and is optional; default probe selection falls back cleanly when `nvidia-smi` is absent.

**Tech Stack:** Python 3.8+, stdlib argparse/subprocess/dataclasses/json, optional PyYAML-free minimal YAML parser for flat portfolio config, unittest script-style tests, existing pre-commit/black/isort/mypy.

---

## File Structure

- Create `src/config_manager/__init__.py`: public API exports.
- Create `src/config_manager/config.py`: `MonitorConfig`, `ConfigError`, YAML parsing, file loading, CLI override merge.
- Create `tests/config_manager/test_config.py`: unit tests for defaults, YAML, overrides, and invalid config.
- Create `src/app_orchestrator/__init__.py`: public API exports.
- Create `src/app_orchestrator/orchestrator.py`: `Orchestrator` and `MonitoringResult` that run collector/analyzer/export/report.
- Create `tests/app_orchestrator/test_orchestrator.py`: unit/integration-style tests for dummy run and invalid output path.
- Modify `src/cli/__main__.py`: remove run lifecycle logic; call config manager and orchestrator.
- Create `src/platform_adapter/nvidia_smi_probe.py`: parse and probe NVIDIA metrics via `nvidia-smi`.
- Create `tests/platform_adapter/test_nvidia_smi_probe.py`: parser/probe unit tests using injected command runner.
- Modify `src/platform_adapter/__init__.py`: add `nvidia-smi` to factory preference.
- Modify `pyproject.toml`: include `config_manager*`, `app_orchestrator*`; add known first-party imports.
- Modify `.github/workflows/test.yml`: set CI baseline environment flag and split baseline/integration commands for readability.
- Modify `README.md`: document config-file run and NVIDIA support.
- Create `docs/changelog/add-config-orchestrator-nvidia.md`: summarize Phase B changes.

## Task 1: config_manager

- [ ] Write `tests/config_manager/test_config.py` with tests for default config, YAML file loading, CLI overrides, unknown keys, invalid positive ints, invalid exporters, and invalid thresholds.
- [ ] Run `py tests/config_manager/test_config.py`; expect `ModuleNotFoundError: No module named 'config_manager'`.
- [ ] Implement `src/config_manager/config.py` and `src/config_manager/__init__.py` with:
  - `MonitorConfig(duration_sec=30, interval_ms=1000, output_dir='reports/demo', device='auto', force_dummy=False, exporters=('jsonl','csv','summary','png'), thresholds={'cpu_high':85.0,'temp_high':80.0})`
  - `ConfigError`
  - `load_config(path=None, overrides=None)`
  - simple YAML parser supporting the required scalar/list/nested-threshold structure.
- [ ] Add `config_manager*` to `pyproject.toml` package discovery and isort first-party list.
- [ ] Run `py tests/config_manager/test_config.py`; expect OK.

## Task 2: app_orchestrator and thin CLI

- [ ] Write `tests/app_orchestrator/test_orchestrator.py` for dummy run generating `metrics.jsonl`, `metrics.csv`, `summary.json`, `report.png`, and for invalid output path raising a clear error.
- [ ] Run `py tests/app_orchestrator/test_orchestrator.py`; expect `ModuleNotFoundError: No module named 'app_orchestrator'`.
- [ ] Implement `src/app_orchestrator/orchestrator.py` with `Orchestrator(config).run()` using existing `Collector`, `AggregatorAnalyzer`, `JsonlExporter`, `CsvExporter`, `SummaryExporter`, and `plot_report`.
- [ ] Implement `src/app_orchestrator/__init__.py`.
- [ ] Refactor `src/cli/__main__.py` so `run` builds config via `load_config()` and calls `Orchestrator`; keep `report` and `scenario` behavior.
- [ ] Add `app_orchestrator*` to `pyproject.toml` package discovery and isort first-party list.
- [ ] Run `py tests/app_orchestrator/test_orchestrator.py && py tests/cli/test_cli_report.py && py integration/test_cli_run.py`; expect OK.

## Task 3: NVIDIA nvidia-smi probe

- [ ] Write `tests/platform_adapter/test_nvidia_smi_probe.py` for CSV parser, unavailable command fallback, successful read, and parse error read status.
- [ ] Run `py tests/platform_adapter/test_nvidia_smi_probe.py`; expect `ModuleNotFoundError` or import error for `NvidiaSmiProbe`.
- [ ] Implement `src/platform_adapter/nvidia_smi_probe.py` with injected runner, `parse_nvidia_smi_csv()`, `is_available()`, `detect_caps()`, and `read_metrics()`.
- [ ] Modify `src/platform_adapter/__init__.py` to prefer `nvidia-smi` before `procfs`/`psutil` when requested and export `NvidiaSmiProbe`.
- [ ] Run `py tests/platform_adapter/test_nvidia_smi_probe.py && py tests/platform_adapter/test_baseline.py`; expect OK.

## Task 4: CI baseline stability and docs

- [ ] Modify `.github/workflows/test.yml` to set `AI_EDGE_CI=1` in the test job and preserve existing status check names.
- [ ] Review baseline tests for env-aware thresholds; if needed, add a small shared helper or local env multiplier without weakening local thresholds.
- [ ] Update README Quick Demo with `monitor.yaml` example and `ai-edge-monitor run --config monitor.yaml`.
- [ ] Update README features and module status to mention `nvidia-smi` GPU support and config/orchestrator status.
- [ ] Add `docs/changelog/add-config-orchestrator-nvidia.md`.
- [ ] Run `py -m pre_commit run --all-files`; expect PASS.

## Task 5: Final verification

- [ ] Run all unit/baseline script tests:
  `py tests/power_monitor/test_baseline.py && py tests/platform_adapter/test_baseline.py && py tests/platform_adapter/test_nvidia_smi_probe.py && py tests/aggregator_analyzer/test_baseline.py && py tests/collector/test_baseline.py && py tests/scheduler/test_baseline.py && py tests/runtime_guardian/test_baseline.py && py tests/test_power_acceptance.py && py tests/storage_exporter/test_exporters.py && py tests/config_manager/test_config.py && py tests/app_orchestrator/test_orchestrator.py && py tests/cli/test_cli_report.py`
- [ ] Run all integration tests:
  `py integration/test_power_to_analyzer.py && py integration/test_adapter_to_collector.py && py integration/test_collector_to_analyzer.py && py integration/test_scheduler_to_report.py && py integration/test_e2e_collect_to_report.py && py integration/test_full_system.py && py integration/test_cli_run.py`
- [ ] Run CLI config smoke test:
  create a temporary YAML config and run `ai-edge-monitor run --config <file> --duration 3 --force-dummy`.
- [ ] Run `py -m pre_commit run --all-files`.
- [ ] Summarize changed files and test outputs.

## Self-review

- Spec coverage: config_manager, app_orchestrator, nvidia-smi, CI/test stability, README, final verification are each covered by tasks.
- Placeholder scan: no placeholders or deferred implementation notes.
- Type consistency: config object is `MonitorConfig`, orchestrator result is `MonitoringResult`, CLI calls `load_config()` and `Orchestrator.run()` consistently.
