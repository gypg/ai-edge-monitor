from __future__ import annotations

import os
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

# 环境变量前缀
_ENV_PREFIX = "AI_EDGE_MONITOR_"

# 环境变量映射：环境变量名 -> 配置键
_ENV_MAPPING = {
    f"{_ENV_PREFIX}DURATION_SEC": "duration_sec",
    f"{_ENV_PREFIX}INTERVAL_MS": "interval_ms",
    f"{_ENV_PREFIX}OUTPUT_DIR": "output_dir",
    f"{_ENV_PREFIX}DEVICE": "device",
    f"{_ENV_PREFIX}FORCE_DUMMY": "force_dummy",
    f"{_ENV_PREFIX}EXPORTERS": "exporters",
    f"{_ENV_PREFIX}CPU_HIGH": "cpu_high",
    f"{_ENV_PREFIX}TEMP_HIGH": "temp_high",
}

# 配置验证规则
_VALIDATION_RULES: Dict[str, Dict[str, Any]] = {
    "duration_sec": {
        "type": int,
        "min": 1,
        "max": 86400,  # 24小时
        "description": "监控时长（秒）",
    },
    "interval_ms": {
        "type": int,
        "min": 100,
        "max": 60000,  # 1分钟
        "description": "采样间隔（毫秒）",
    },
    "output_dir": {
        "type": str,
        "description": "输出目录",
    },
    "device": {
        "type": str,
        "allowed_values": ["auto", "cpu", "gpu", "jetson", "rpi", "nvidia-smi", "procfs", "psutil", "embedded"],
        "description": "目标设备类型",
    },
    "force_dummy": {
        "type": bool,
        "description": "强制使用虚拟数据源",
    },
    "exporters": {
        "type": list,
        "allowed_values": list(_ALLOWED_EXPORTERS),
        "description": "导出器列表",
    },
}


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
    """加载配置，优先级：默认值 < 环境变量 < 配置文件 < CLI参数"""
    raw: Dict[str, Any] = {}
    
    # 1. 从环境变量加载
    env_config = _load_from_env()
    if env_config:
        raw.update(env_config)
    
    # 2. 从配置文件加载（覆盖环境变量）
    if path is not None:
        raw.update(_load_file(Path(path)))
    
    # 3. 从CLI参数加载（最高优先级）
    if overrides:
        raw.update({key: value for key, value in overrides.items() if value is not None})
    
    # 4. 验证配置
    _validate_keys(raw)
    _validate_config(raw)
    
    return MonitorConfig(**raw)


def _load_from_env() -> Dict[str, Any]:
    """从环境变量加载配置"""
    config: Dict[str, Any] = {}
    
    for env_var, config_key in _ENV_MAPPING.items():
        value = os.environ.get(env_var)
        if value is None:
            continue
        
        # 根据配置键类型转换值
        if config_key == "duration_sec":
            config[config_key] = _parse_env_int(env_var, value)
        elif config_key == "interval_ms":
            config[config_key] = _parse_env_int(env_var, value)
        elif config_key == "output_dir":
            config[config_key] = value
        elif config_key == "device":
            config[config_key] = value.lower()
        elif config_key == "force_dummy":
            config[config_key] = _parse_env_bool(env_var, value)
        elif config_key == "exporters":
            # 支持逗号分隔的列表
            config[config_key] = [x.strip() for x in value.split(",") if x.strip()]
        elif config_key == "cpu_high":
            # 阈值单独处理
            if "thresholds" not in config:
                config["thresholds"] = {}
            config["thresholds"]["cpu_high"] = _parse_env_float(env_var, value)
        elif config_key == "temp_high":
            if "thresholds" not in config:
                config["thresholds"] = {}
            config["thresholds"]["temp_high"] = _parse_env_float(env_var, value)
    
    return config


def _parse_env_int(env_var: str, value: str) -> int:
    """解析环境变量为整数"""
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"环境变量 {env_var} 必须是整数，当前值: {value}")


def _parse_env_float(env_var: str, value: str) -> float:
    """解析环境变量为浮点数"""
    try:
        return float(value)
    except ValueError:
        raise ConfigError(f"环境变量 {env_var} 必须是数字，当前值: {value}")


def _parse_env_bool(env_var: str, value: str) -> bool:
    """解析环境变量为布尔值"""
    if value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    raise ConfigError(f"环境变量 {env_var} 必须是布尔值，当前值: {value}")


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


def _validate_config(raw: Mapping[str, Any]) -> None:
    """验证配置的有效性"""
    for key, value in raw.items():
        if key not in _VALIDATION_RULES:
            continue
        
        rule = _VALIDATION_RULES[key]
        expected_type = rule["type"]
        
        # 类型检查
        if expected_type == int:
            if not isinstance(value, int):
                raise ConfigError(f"{key} 必须是整数，当前类型: {type(value).__name__}")
            if "min" in rule and value < rule["min"]:
                raise ConfigError(f"{key} 不能小于 {rule['min']}，当前值: {value}")
            if "max" in rule and value > rule["max"]:
                raise ConfigError(f"{key} 不能大于 {rule['max']}，当前值: {value}")
        
        elif expected_type == float:
            if not isinstance(value, (int, float)):
                raise ConfigError(f"{key} 必须是数字，当前类型: {type(value).__name__}")
        
        elif expected_type == str:
            if not isinstance(value, str):
                raise ConfigError(f"{key} 必须是字符串，当前类型: {type(value).__name__}")
            if "allowed_values" in rule and value not in rule["allowed_values"]:
                raise ConfigError(
                    f"{key} 必须是以下之一: {rule['allowed_values']}，当前值: {value}"
                )
        
        elif expected_type == bool:
            if not isinstance(value, bool):
                raise ConfigError(f"{key} 必须是布尔值，当前类型: {type(value).__name__}")
        
        elif expected_type == list:
            if not isinstance(value, (list, tuple)):
                raise ConfigError(f"{key} 必须是列表，当前类型: {type(value).__name__}")
            if "allowed_values" in rule:
                for item in value:
                    if item not in rule["allowed_values"]:
                        raise ConfigError(
                            f"{key} 中的值 '{item}' 不在允许的范围内: {rule['allowed_values']}"
                        )


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
                raise ConfigError(f"invalid YAML at line {line_no}: expected threshold key: value")
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


def get_config_summary(config: MonitorConfig) -> Dict[str, Any]:
    """获取配置摘要，用于调试和日志"""
    return {
        "duration_sec": config.duration_sec,
        "interval_ms": config.interval_ms,
        "output_dir": config.output_dir,
        "device": config.device,
        "force_dummy": config.force_dummy,
        "exporters": list(config.exporters),
        "thresholds": config.thresholds,
    }


def print_config_summary(config: MonitorConfig) -> None:
    """打印配置摘要"""
    summary = get_config_summary(config)
    print("配置摘要:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
