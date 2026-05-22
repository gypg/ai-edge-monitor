# Jetson / Raspberry Pi Real Hardware Validation Template

> This is a fill-in template for future real-device validation. It does not claim that any hardware run has already been completed.

## 1. Device Information

| Field | Value |
|---|---|
| Device model |  |
| CPU / GPU / accelerator |  |
| RAM |  |
| OS image / version |  |
| Kernel version |  |
| Python version |  |
| ai-edge-monitor commit |  |
| Power source available (`sysfs`, `tegrastats`, external meter) |  |
| Notes |  |

## 2. Environment Setup

```bash
python -m pip install -e ".[all]"
ai-edge-monitor run --duration 60 --out reports/real_device
```

For hosts without supported sensors, force the synthetic path for comparison only:

```bash
ai-edge-monitor run --duration 60 --out reports/dummy_reference --force-dummy
```

## 3. Expected Results

- CPU readings should move with workload changes and stay within `0..100` percent.
- Memory used should be non-zero and below total device memory.
- Power should be non-null when a supported power source exists; otherwise the summary should clearly identify dummy or unavailable quality.
- Temperature should be plausible for the board class and should rise during sustained workload.
- `report.png`, `summary.json`, `metrics.jsonl`, and `metrics.csv` should all be generated.

## 4. Result Checklist

| Check | PASS/FAIL | Evidence path / notes |
|---|---|---|
| Command completed with exit code 0 |  |  |
| `metrics.jsonl` generated and non-empty |  |  |
| `metrics.csv` generated and non-empty |  |  |
| `summary.json` generated and parseable |  |  |
| `report.png` generated and viewable |  |  |
| CPU readings are plausible |  |  |
| Memory readings are plausible |  |  |
| Power readings are plausible or fallback is explained |  |  |
| Temperature readings are plausible or unavailable is explained |  |  |

## 5. Recorded Summary

| Metric | Real device value | Dummy reference value | Notes |
|---|---:|---:|---|
| `sample_count_metrics` |  |  |  |
| `sample_count_power` |  |  |  |
| `cpu_avg` |  |  |  |
| `cpu_max` |  |  |  |
| `mem_used_avg_mb` |  |  |  |
| `power_avg_watt` |  |  |  |
| `power_max_watt` |  |  |  |
| `temp_max_c` |  |  |  |
| `energy_joule` |  |  |  |
| `power_quality_worst` |  |  |  |

## 6. Exception Log

| Time | Symptom | Suspected cause | Action taken | Result |
|---|---|---|---|---|
|  |  |  |  |  |

## 7. Dummy Scenario Comparison Guide

Generate a controlled synthetic inference report:

```bash
ai-edge-monitor scenario --scenario inference --duration 60 --out docs/test_report/scenarios
```

Compare the real-device report against `docs/test_report/scenarios/report_inference.png`:

- Real CPU and temperature curves may be noisier than dummy curves.
- Real power may be unavailable, lower, or higher depending on board sensors and rails exposed.
- Dummy scenarios are useful for validating report shape, not for claiming hardware performance.
