# add-config-orchestrator-nvidia

## Summary

Phase B adds configuration-driven execution, a dedicated orchestration layer, and optional NVIDIA GPU telemetry through `nvidia-smi`.

## Changes

- Added `config_manager` with YAML defaults/file/CLI override merging and validation.
- Added `app_orchestrator` so CLI run only parses arguments and delegates lifecycle execution.
- Added `NvidiaSmiProbe` for GPU utilization, memory, and temperature when `nvidia-smi` is available.
- Updated CI to mark test jobs with `AI_EDGE_CI=1` for baseline-aware execution.
- Updated README Quick Demo with YAML config usage and NVIDIA support notes.

## User-facing commands

```bash
ai-edge-monitor run --config monitor.yaml
ai-edge-monitor run --config monitor.yaml --duration 10 --force-dummy
```
