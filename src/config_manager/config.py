from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

PathLike = Union[str, Path]
_ALLOWED_KEYS = {
    "duration_sec",
    "interval_ms",
    "output_dir",
    "device",
    "force_dummy",
    "exporters",
    "thresholds",
}
_ALLOWED_EXPORTERS = {"jsonl", "csv", "summary", "png"}
_DEFAULT_THRESHOLDS = {"cpu_high": 85.0, "temp_high": 80.0}


class ConfigError(ValueError):
    pass


@dataclass
class MonitorConfig:
    duration_sec: int = 30
    interval_ms: int = 1000
    output_dir: str = "reports/demo"
    device: str = "auto"
    force_dummy: bool = False
    exporters: Tuple[str, ...] = ("jsonl", "csv", "summary", "png")
    thresholds: Dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_THRESHOLDS))

    def __post_init__(self) -> None:
        self.duration_sec = _positive_int("duration_sec", self.duration_sec)
        self.interval_ms = _positive_int("interval_ms", self.interval_ms)
        self.output_dir = str(self.output_dir)
        self.device = str(self.device)
        self.force_dummy = bool(self.force_dummy)
        self.exporters = tuple(str(item) for item in self.exporters)
        for exporter in self.exporters:
            if exporter not in _ALLOWED_EXPORTERS:
                raise ConfigError(f"unsupported exporter: {exporter}")
        thresholds = dict(_DEFAULT_THRESHOLDS)
        thresholds.update(self.thresholds or {})
        normalized: Dict[str, float] = {}
        for name, value in thresholds.items():
            try:
                normalized[name] = float(value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"threshold {name} must be a number") from exc
        self.thresholds = normalized


def load_config(
    path: Optional[PathLike] = None, overrides: Optional[Mapping[str, Any]] = None
) -> MonitorConfig:
    raw: Dict[str, Any] = {}
    if path is not None:
        raw.update(_load_file(Path(path)))
    if overrides:
        raw.update({key: value for key, value in overrides.items() if value is not None})
    _validate_keys(raw)
    return MonitorConfig(**raw)


def _load_file(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ConfigError("config file must be YAML (.yaml or .yml)")
    loaded = _parse_yaml(path.read_text(encoding="utf-8"))
    _validate_keys(loaded)
    return loaded


def _validate_keys(raw: Mapping[str, Any]) -> None:
    for key in raw:
        if key not in _ALLOWED_KEYS:
            raise ConfigError(f"unknown config key: {key}")


def _positive_int(name: str, value: Any) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if converted <= 0:
        raise ConfigError(f"{name} must be > 0")
    return converted


def _parse_yaml(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for line_no, original in enumerate(text.splitlines(), start=1):
        stripped = original.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(original) - len(original.lstrip(" "))
        if indent == 0:
            if ":" not in stripped:
                raise ConfigError(f"invalid YAML at line {line_no}: expected key: value")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise ConfigError(f"invalid YAML at line {line_no}: empty key")
            if value == "":
                data[key] = [] if key == "exporters" else {}
                current_key = key
            else:
                data[key] = _parse_scalar(value)
                current_key = None
            continue
        if current_key is None:
            raise ConfigError(f"invalid YAML at line {line_no}: unexpected indentation")
        if current_key == "exporters":
            if not stripped.startswith("- "):
                raise ConfigError(f"invalid YAML at line {line_no}: expected list item")
            item = stripped[2:].strip()
            data[current_key].append(str(_parse_scalar(item)))
        elif current_key == "thresholds":
            if ":" not in stripped:
                raise ConfigError(
                    f"invalid YAML at line {line_no}: expected threshold key: value"
                )
            key, value = stripped.split(":", 1)
            data[current_key][key.strip()] = _parse_scalar(value.strip())
        else:
            raise ConfigError(
                f"invalid YAML at line {line_no}: nested values not supported for {current_key}"
            )
    return data


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value