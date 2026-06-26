"""告警管理模块

提供以下功能：
1. 阈值告警：基于固定阈值的告警
2. 趋势告警：基于指标变化趋势的告警
3. 异常检测：基于统计方法的异常检测
4. 告警通知：支持多种通知方式
"""

from __future__ import annotations

import json
import logging
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from enum import Enum

LOG = logging.getLogger("alert_manager")


class AlertSeverity(Enum):
    """告警严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(Enum):
    """告警状态"""
    ACTIVE = "active"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class AlertRule:
    """告警规则"""
    name: str
    metric: str
    condition: str  # "gt", "lt", "eq", "ne", "gte", "lte"
    threshold: float
    severity: AlertSeverity
    duration_sec: int = 0  # 持续时间阈值
    cooldown_sec: int = 300  # 告警冷却时间
    enabled: bool = True
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Alert:
    """告警实例"""
    id: str
    rule_name: str
    metric: str
    current_value: float
    threshold: float
    condition: str
    severity: AlertSeverity
    status: AlertStatus
    triggered_at: float
    resolved_at: Optional[float] = None
    acknowledged_at: Optional[float] = None
    message: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "metric": self.metric,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "condition": self.condition,
            "severity": self.severity.value,
            "status": self.status.value,
            "triggered_at": self.triggered_at,
            "resolved_at": self.resolved_at,
            "acknowledged_at": self.acknowledged_at,
            "message": self.message,
            "tags": self.tags,
        }


@dataclass
class TrendAlertRule:
    """趋势告警规则"""
    name: str
    metric: str
    window_sec: int = 300  # 分析窗口
    change_threshold: float = 20.0  # 变化百分比阈值
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True


@dataclass
class AnomalyDetectionConfig:
    """异常检测配置"""
    method: str = "zscore"  # zscore, iqr, percentile
    window_size: int = 100
    zscore_threshold: float = 3.0
    iqr_multiplier: float = 1.5
    percentile_lower: float = 5.0
    percentile_upper: float = 95.0


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._trend_rules: Dict[str, TrendAlertRule] = {}
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._notification_callbacks: List[Callable[[Alert], None]] = []
        self._last_alert_times: Dict[str, float] = {}
        self._metric_history: Dict[str, List[Tuple[float, float]]] = {}  # (timestamp, value)
        self._anomaly_config = AnomalyDetectionConfig()
        
        # 告警统计
        self._total_alerts = 0
        self._total_resolved = 0
    
    def add_rule(self, rule: AlertRule) -> None:
        """添加告警规则"""
        self._rules[rule.name] = rule
        LOG.info(f"Added alert rule: {rule.name}")
    
    def add_trend_rule(self, rule: TrendAlertRule) -> None:
        """添加趋势告警规则"""
        self._trend_rules[rule.name] = rule
        LOG.info(f"Added trend alert rule: {rule.name}")
    
    def remove_rule(self, rule_name: str) -> bool:
        """移除告警规则"""
        if rule_name in self._rules:
            del self._rules[rule_name]
            LOG.info(f"Removed alert rule: {rule_name}")
            return True
        return False
    
    def add_notification_callback(self, callback: Callable[[Alert], None]) -> None:
        """添加通知回调"""
        self._notification_callbacks.append(callback)
    
    def check_threshold(self, metric: str, value: float) -> List[Alert]:
        """检查阈值告警"""
        alerts = []
        current_time = time.time()
        
        for rule_name, rule in self._rules.items():
            if not rule.enabled or rule.metric != metric:
                continue
            
            # 检查冷却时间
            last_alert_time = self._last_alert_times.get(rule_name, 0)
            if current_time - last_alert_time < rule.cooldown_sec:
                continue
            
            # 检查条件
            triggered = False
            if rule.condition == "gt" and value > rule.threshold:
                triggered = True
            elif rule.condition == "lt" and value < rule.threshold:
                triggered = True
            elif rule.condition == "eq" and value == rule.threshold:
                triggered = True
            elif rule.condition == "ne" and value != rule.threshold:
                triggered = True
            elif rule.condition == "gte" and value >= rule.threshold:
                triggered = True
            elif rule.condition == "lte" and value <= rule.threshold:
                triggered = True
            
            if triggered:
                alert = self._create_alert(rule, value)
                alerts.append(alert)
                self._last_alert_times[rule_name] = current_time
        
        return alerts
    
    def check_trend(self, metric: str, value: float) -> List[Alert]:
        """检查趋势告警"""
        alerts = []
        current_time = time.time()
        
        # 更新指标历史
        if metric not in self._metric_history:
            self._metric_history[metric] = []
        
        self._metric_history[metric].append((current_time, value))
        
        # 清理过期数据
        for rule_name, rule in self._trend_rules.items():
            if not rule.enabled or rule.metric != metric:
                continue
            
            window_start = current_time - rule.window_sec
            self._metric_history[metric] = [
                (ts, val) for ts, val in self._metric_history[metric]
                if ts >= window_start
            ]
            
            # 检查趋势
            history = self._metric_history[metric]
            if len(history) < 2:
                continue
            
            # 计算变化百分比
            first_value = history[0][1]
            last_value = history[-1][1]
            
            if first_value != 0:
                change_percent = ((last_value - first_value) / abs(first_value)) * 100
            else:
                change_percent = 0
            
            if abs(change_percent) >= rule.change_threshold:
                alert = Alert(
                    id=f"trend_{rule_name}_{int(current_time)}",
                    rule_name=rule_name,
                    metric=metric,
                    current_value=change_percent,
                    threshold=rule.change_threshold,
                    condition="trend_change",
                    severity=rule.severity,
                    status=AlertStatus.ACTIVE,
                    triggered_at=current_time,
                    message=f"趋势告警: {metric} 变化 {change_percent:.2f}% (阈值: {rule.change_threshold}%)",
                )
                alerts.append(alert)
        
        return alerts
    
    def check_anomaly(self, metric: str, value: float) -> Optional[Alert]:
        """检查异常值"""
        current_time = time.time()
        
        # 更新历史
        if metric not in self._metric_history:
            self._metric_history[metric] = []
        
        self._metric_history[metric].append((current_time, value))
        
        history = [val for _, val in self._metric_history[metric]]
        
        if len(history) < self._anomaly_config.window_size:
            return None
        
        # 只保留窗口内的数据
        history = history[-self._anomaly_config.window_size:]
        
        is_anomaly = False
        
        if self._anomaly_config.method == "zscore":
            mean_val = sum(history) / len(history)
            variance = sum((x - mean_val) ** 2 for x in history) / len(history)
            std_val = variance ** 0.5
            
            if std_val > 0:
                z_score = abs(value - mean_val) / std_val
                is_anomaly = z_score > self._anomaly_config.zscore_threshold
        
        elif self._anomaly_config.method == "iqr":
            sorted_history = sorted(history)
            n = len(sorted_history)
            q1 = sorted_history[n // 4]
            q3 = sorted_history[3 * n // 4]
            iqr = q3 - q1
            lower_bound = q1 - self._anomaly_config.iqr_multiplier * iqr
            upper_bound = q3 + self._anomaly_config.iqr_multiplier * iqr
            is_anomaly = value < lower_bound or value > upper_bound
        
        if is_anomaly:
            return Alert(
                id=f"anomaly_{metric}_{int(current_time)}",
                rule_name="anomaly_detection",
                metric=metric,
                current_value=value,
                threshold=0,
                condition="anomaly",
                severity=AlertSeverity.WARNING,
                status=AlertStatus.ACTIVE,
                triggered_at=current_time,
                message=f"异常检测: {metric} = {value} 被检测为异常值",
            )
        
        return None
    
    def _create_alert(self, rule: AlertRule, current_value: float) -> Alert:
        """创建告警实例"""
        alert_id = f"{rule.name}_{int(time.time())}"
        
        alert = Alert(
            id=alert_id,
            rule_name=rule.name,
            metric=rule.metric,
            current_value=current_value,
            threshold=rule.threshold,
            condition=rule.condition,
            severity=rule.severity,
            status=AlertStatus.ACTIVE,
            triggered_at=time.time(),
            message=f"阈值告警: {rule.metric} {rule.condition} {rule.threshold} (当前值: {current_value})",
            tags=rule.tags,
        )
        
        # 添加到活跃告警
        self._active_alerts[alert_id] = alert
        self._alert_history.append(alert)
        self._total_alerts += 1
        
        # 发送通知
        self._send_notifications(alert)
        
        LOG.warning(f"Alert triggered: {alert.message}")
        
        return alert
    
    def _send_notifications(self, alert: Alert) -> None:
        """发送通知"""
        for callback in self._notification_callbacks:
            try:
                callback(alert)
            except Exception as e:
                LOG.error(f"Failed to send notification: {e}")
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认告警"""
        if alert_id in self._active_alerts:
            alert = self._active_alerts[alert_id]
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = time.time()
            LOG.info(f"Alert acknowledged: {alert_id}")
            return True
        return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """解决告警"""
        if alert_id in self._active_alerts:
            alert = self._active_alerts[alert_id]
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = time.time()
            del self._active_alerts[alert_id]
            self._total_resolved += 1
            LOG.info(f"Alert resolved: {alert_id}")
            return True
        return False
    
    def get_active_alerts(self) -> List[Alert]:
        """获取活跃告警"""
        return list(self._active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """获取告警历史"""
        return self._alert_history[-limit:]
    
    def get_alert_stats(self) -> Dict[str, Any]:
        """获取告警统计"""
        return {
            "total_alerts": self._total_alerts,
            "total_resolved": self._total_resolved,
            "active_alerts": len(self._active_alerts),
            "rules_count": len(self._rules),
            "trend_rules_count": len(self._trend_rules),
        }
    
    def export_alerts_json(self) -> str:
        """导出告警为JSON"""
        alerts_data = {
            "active_alerts": [alert.to_dict() for alert in self._active_alerts.values()],
            "alert_history": [alert.to_dict() for alert in self._alert_history[-100:]],
            "stats": self.get_alert_stats(),
        }
        return json.dumps(alerts_data, indent=2, ensure_ascii=False)


class EmailNotifier:
    """邮件通知器"""
    
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
    
    def send_alert(self, alert: Alert, recipients: List[str]) -> bool:
        """发送告警邮件"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.username
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"[{alert.severity.value.upper()}] AI Edge Monitor 告警: {alert.rule_name}"
            
            body = f"""
告警详情:
- 规则名称: {alert.rule_name}
- 指标: {alert.metric}
- 当前值: {alert.current_value}
- 阈值: {alert.threshold}
- 条件: {alert.condition}
- 严重程度: {alert.severity.value}
- 触发时间: {datetime.fromtimestamp(alert.triggered_at).strftime('%Y-%m-%d %H:%M:%S')}
- 消息: {alert.message}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            
            return True
        except Exception as e:
            LOG.error(f"Failed to send email: {e}")
            return False


class WebhookNotifier:
    """Webhook 通知器"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    def send_alert(self, alert: Alert) -> bool:
        """发送 Webhook 通知"""
        try:
            import urllib.request
            
            data = json.dumps(alert.to_dict()).encode('utf-8')
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req)
            return True
        except Exception as e:
            LOG.error(f"Failed to send webhook: {e}")
            return False


# 便捷函数
def create_alert_manager() -> AlertManager:
    """创建告警管理器实例"""
    return AlertManager()


def create_default_rules() -> List[AlertRule]:
    """创建默认告警规则"""
    return [
        AlertRule(
            name="high_cpu",
            metric="cpu_percent",
            condition="gt",
            threshold=90.0,
            severity=AlertSeverity.WARNING,
            description="CPU使用率过高",
        ),
        AlertRule(
            name="high_memory",
            metric="memory_percent",
            condition="gt",
            threshold=85.0,
            severity=AlertSeverity.WARNING,
            description="内存使用率过高",
        ),
        AlertRule(
            name="high_temperature",
            metric="temperature_c",
            condition="gt",
            threshold=80.0,
            severity=AlertSeverity.ERROR,
            description="温度过高",
        ),
        AlertRule(
            name="low_disk_space",
            metric="disk_usage_percent",
            condition="gt",
            threshold=90.0,
            severity=AlertSeverity.CRITICAL,
            description="磁盘空间不足",
        ),
    ]