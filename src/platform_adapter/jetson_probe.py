"""NVIDIA Jetson power and GPU probe via jtop/tegrastats.

This probe is intentionally separate from `ProcfsProbe` and `PsutilProbe`:
- Jetson GPU / power data is only available through `jtop` (Python API) or
  `tegrastats` (CLI).
- Pulling it in as an optional dependency keeps the rest of the package
  installable on non-Jetson hardware.

Capabilities reported by `detect_caps()`:
- CPU / memory: inherited from a primary probe (this probe focuses on GPU
  and power rails, but can also fill CPU/mem if needed).
- GPU utilization and memory via jtop/tegrastats.
- Board power rail(s) when jtop exposes them.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .probe import PlatformCaps, PlatformProbe, RawMetrics


class JetsonProbe(PlatformProbe):
    """Probe for NVIDIA Jetson devices using jtop or tegrastats."""

    name = "jetson"

    def __init__(self) -> None:
        self._jtop: Optional[Any] = None
        self._jtop_ok = False
        self._tegrastats_ok = False
        self._last_error: Optional[str] = None
        self._try_jtop()
        self._try_tegrastats()

    def _try_jtop(self) -> None:
        try:
            from jtop import jtop

            self._jtop = jtop()
            self._jtop_ok = True
        except Exception as exc:  # pragma: no cover - jtop may not be installed
            self._last_error = f"jtop unavailable: {exc}"
            self._jtop_ok = False

    def _try_tegrastats(self) -> None:
        try:
            result = subprocess.run(
                ["tegrastats", "--stop"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            # tegrastats --stop returns 0 or 1 depending on whether it was
            # already running; either means the binary is present.
            self._tegrastats_ok = result.returncode in (0, 1)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            self._tegrastats_ok = False

    def is_available(self) -> bool:
        return self._jtop_ok or self._tegrastats_ok

    def detect_caps(self) -> PlatformCaps:
        if not self.is_available():
            return PlatformCaps(
                has_cpu=False,
                has_mem=False,
                has_gpu=False,
                has_temp_sensor=False,
                has_power_sensor=False,
                platform_name=self.name,
                notes={"error": self._last_error or "jetson probe unavailable"},
            )
        return PlatformCaps(
            has_cpu=False,  # leave CPU to primary probe
            has_mem=False,  # leave memory to primary probe
            has_gpu=True,
            has_temp_sensor=False,  # temperature handled by primary thermal probe
            has_power_sensor=self._jtop_ok,  # jtop exposes board power
            platform_name=self.name,
            notes={"backend": "jtop" if self._jtop_ok else "tegrastats"},
        )

    def read_metrics(self) -> RawMetrics:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)

        if not self.is_available():
            return RawMetrics(
                ts_ms=ts_ms,
                cpu_percent=0.0,
                mem_used_mb=0.0,
                mem_total_mb=0.0,
                gpu_percent=None,
                gpu_mem_used_mb=None,
                temperature_c=None,
                probe_name=self.name,
                status="not_supported",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message=self._last_error or "jetson probe unavailable",
            )

        gpu_pct: Optional[float] = None
        gpu_mem_mb: Optional[float] = None
        power_w: Optional[float] = None
        partial_reason: Optional[str] = None

        try:
            if self._jtop_ok and self._jtop is not None:
                gpu_pct, gpu_mem_mb, power_w = self._read_jtop()
            elif self._tegrastats_ok:
                gpu_pct, gpu_mem_mb, power_w = self._read_tegrastats()
        except Exception as exc:  # pragma: no cover - depends on real hardware
            partial_reason = f"jetson read failed: {exc}"

        latency_ms = (time.perf_counter() - started) * 1000.0
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=0.0,
            mem_used_mb=0.0,
            mem_total_mb=0.0,
            gpu_percent=gpu_pct,
            gpu_mem_used_mb=gpu_mem_mb,
            temperature_c=None,
            probe_name=self.name,
            status="ok" if partial_reason is None else "partial",
            latency_ms=latency_ms,
            error_message=partial_reason,
        )

    def _read_jtop(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Read GPU utilization, GPU memory (MB), and power (W) from jtop."""
        try:
            from jtop import jtop
        except ImportError as exc:  # pragma: no cover - caught by __init__
            raise RuntimeError("jtop not installed") from exc

        with jtop() as jetson:
            gpu_pct = None
            gpu_mem_mb = None
            power_w = None

            # GPU utilization
            gpu = jetson.gpu
            if gpu:
                gpu_pct = float(gpu.get("GPU", 0)) if gpu.get("GPU") else None
                gpu_mem = gpu.get("RAM", {})
                if isinstance(gpu_mem, dict):
                    used = gpu_mem.get("used")
                    if used is not None:
                        gpu_mem_mb = float(used)

            # Power rails: jtop exposes a flat dict of rail names -> values (mW)
            power = jetson.power
            if power and isinstance(power, dict):
                total_mw: Optional[float] = power.get("tot")
                if total_mw is None and "POM_5V_GPU" in power:
                    total_mw = float(power["POM_5V_GPU"])
                if total_mw is not None:
                    power_w = total_mw / 1000.0

            return gpu_pct, gpu_mem_mb, power_w

    def _read_tegrastats(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Fallback reading from tegrastats single-shot output."""
        result = subprocess.run(
            ["tegrastats", "--interval", "100", "--samples", "1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "tegrastats failed")

        line = result.stdout.strip()
        if not line:
            raise RuntimeError("tegrastats returned no output")

        gpu_pct: Optional[float] = None
        gpu_mem_mb: Optional[float] = None
        power_w: Optional[float] = None

        # Typical tegrastats line:
        # RAM 1234/7772MB (lfb 1234x4MB) SWAP 0/0MB (cached 0MB) CPU [10%@1190, ...]
        # GR3D 20% PLL 0 VDD_IN 1234/1234 VDD_CV 0/0 ...
        for token in line.split():
            if token.startswith("GR3D"):
                try:
                    gpu_pct = float(token.replace("GR3D", "").replace("%", ""))
                except ValueError:
                    pass
            elif token.startswith("RAM"):
                # format: RAM 1234/7772MB
                parts = token.split("/")
                if len(parts) == 2:
                    try:
                        gpu_mem_mb = float(parts[0])
                    except ValueError:
                        pass
            elif token.startswith("VDD_IN"):
                # format: VDD_IN 1234mW or VDD_IN 1234/1234mW
                raw = token.replace("VDD_IN", "").replace("mW", "").split("/")[0]
                try:
                    power_w = float(raw) / 1000.0
                except ValueError:
                    pass

        return gpu_pct, gpu_mem_mb, power_w

    def close(self) -> None:
        if self._jtop is not None:
            try:
                self._jtop.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass
            self._jtop = None
