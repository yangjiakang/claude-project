"""API 使用追踪器 —— 记录每次 API 调用"""

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path.home() / ".claude" / "api-usage"
LOGS_DIR = DATA_DIR / "logs"

SUPPORTED_MODELS = {
    "deepseek": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "kimi": [
        "kimi-2.5",
        "kimi-2.0",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
    ],
    "claude": [
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    ],
}


def detect_model_provider(model_name: str) -> str:
    """根据模型名称识别提供商"""
    lowered = model_name.lower()
    for provider, models in SUPPORTED_MODELS.items():
        for m in models:
            if m in lowered:
                return provider
    return "unknown"


@dataclass
class UsageRecord:
    timestamp: str          # ISO 8601
    session_id: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    endpoint: str           # e.g. "https://api.deepseek.com/anthropic"


class UsageTracker:
    """API 使用量追踪器"""

    def __init__(self, logs_dir: Optional[Path] = None):
        self.logs_dir = logs_dir or LOGS_DIR
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _daily_file(self, date_str: Optional[str] = None) -> Path:
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.logs_dir / f"{date_str}.jsonl"

    def record(self, record: UsageRecord) -> None:
        """追加一条使用记录"""
        daily_file = self._daily_file(record.timestamp[:10])
        with open(daily_file, "a") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def read_day(self, date_str: str) -> list[UsageRecord]:
        """读取某一天的所有记录"""
        daily_file = self._daily_file(date_str)
        if not daily_file.exists():
            return []
        records = []
        with open(daily_file) as f:
            for line in f:
                if line.strip():
                    records.append(UsageRecord(**json.loads(line)))
        return records

    def read_range(self, start_date: str, end_date: str) -> list[UsageRecord]:
        """读取日期范围内的所有记录"""
        records = []
        for f in sorted(self.logs_dir.glob("*.jsonl")):
            date_str = f.stem  # "2026-05-30"
            if start_date <= date_str <= end_date:
                records.extend(self.read_day(date_str))
        return records

    def available_dates(self) -> list[str]:
        """返回有记录的日期列表"""
        return sorted(
            [f.stem for f in self.logs_dir.glob("*.jsonl")]
        )

    def quick_record(
        self,
        session_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        endpoint: str = "",
    ) -> None:
        """快速记录（自动检测 provider 和时间）"""
        now = datetime.now(timezone.utc).isoformat()
        provider = detect_model_provider(model)
        if not endpoint:
            if provider == "deepseek":
                endpoint = "https://api.deepseek.com/anthropic"
            elif provider == "kimi":
                endpoint = "https://api.moonshot.cn/v1"
        self.record(UsageRecord(
            timestamp=now,
            session_id=session_id,
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            endpoint=endpoint,
        ))
