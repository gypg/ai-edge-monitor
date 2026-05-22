# add-cli-and-exporter

## Summary

Added the first portfolio-ready Phase A workflow: `ai-edge-monitor` can now run one monitoring session, export structured telemetry, and render a PNG report from one command.

## Changes

- Added `cli` package with `run`, `report`, and `scenario` subcommands.
- Registered `ai-edge-monitor` as a console script in `pyproject.toml`.
- Added `storage_exporter` with JSONL, CSV, and summary JSON exporters.
- Added CLI and exporter tests, including a dummy-source integration test for the one-command demo.
- Updated README Quick Demo, module status table, and project tree.

## User-facing commands

```bash
ai-edge-monitor run --duration 30 --out reports/demo
ai-edge-monitor report --input reports/demo/summary.json --out reports/demo/report.png
ai-edge-monitor scenario --duration 60 --out docs/test_report/scenarios
```

## Outputs

`ai-edge-monitor run` writes:

- `metrics.jsonl`
- `metrics.csv`
- `summary.json`
- `report.png`
- `report.png.json`
