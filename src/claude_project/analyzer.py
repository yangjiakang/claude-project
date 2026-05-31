"""API 使用分析器 —— 按天/按模型/按提供商聚合统计"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .tracker import UsageTracker, UsageRecord, detect_model_provider

HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
SESSIONS_DIR = Path.home() / ".claude" / "sessions"


@dataclass
class DailyStats:
    date: str = ""
    total_sessions: int = 0
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    by_provider: dict = field(default_factory=lambda: defaultdict(lambda: {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "models": defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0}),
    }))


@dataclass
class ProviderStats:
    provider: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    models: dict = field(default_factory=dict)


class UsageAnalyzer:
    """从多个数据源分析 API 使用情况"""

    def __init__(self):
        self.tracker = UsageTracker()

    # ─── history.jsonl 分析（Claude Code 会话记录）───

    def analyze_history(self, days: int = 7) -> list[dict]:
        """分析 history.jsonl 获取每日会话统计"""
        if not HISTORY_FILE.exists():
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        daily_counts = defaultdict(int)

        with open(HISTORY_FILE) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", 0)
                    if ts >= cutoff:
                        date_str = datetime.fromtimestamp(
                            ts / 1000, tz=timezone.utc
                        ).strftime("%Y-%m-%d")
                        daily_counts[date_str] += 1
                except json.JSONDecodeError:
                    continue

        return [
            {"date": d, "message_count": c}
            for d, c in sorted(daily_counts.items())
        ]

    # ─── sessions 分析 ───

    def analyze_sessions(self, days: int = 7) -> list[dict]:
        """分析 session 数据获取会话时长"""
        if not SESSIONS_DIR.exists():
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000
        daily_sessions = defaultdict(list)

        for session_file in SESSIONS_DIR.glob("*.json"):
            try:
                with open(session_file) as f:
                    s = json.load(f)
                started = s.get("startedAt", 0)
                if started >= cutoff:
                    updated = s.get("updatedAt", started)
                    duration_min = (updated - started) / 1000 / 60
                    date_str = datetime.fromtimestamp(
                        started / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    daily_sessions[date_str].append(duration_min)
            except (json.JSONDecodeError, KeyError):
                continue

        return [
            {
                "date": d,
                "session_count": len(durations),
                "total_minutes": round(sum(durations), 1),
                "avg_minutes": round(sum(durations) / len(durations), 1),
            }
            for d, durations in sorted(daily_sessions.items())
        ]

    # ─── token 日志分析 ───

    def analyze_token_usage(self, days: int = 7) -> dict[str, DailyStats]:
        """分析 API 使用日志"""
        today = datetime.now(timezone.utc)
        start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        records = self.tracker.read_range(start_date, end_date)
        daily: dict[str, DailyStats] = defaultdict(DailyStats)

        for r in records:
            date = r.timestamp[:10]
            stats = daily[date]
            stats.date = date
            stats.total_requests += 1
            stats.total_input_tokens += r.input_tokens
            stats.total_output_tokens += r.output_tokens
            stats.total_cost_usd += r.cost_usd

            provider_data = stats.by_provider[r.provider]
            provider_data["requests"] += 1
            provider_data["input_tokens"] += r.input_tokens
            provider_data["output_tokens"] += r.output_tokens
            provider_data["cost_usd"] += r.cost_usd
            provider_data["models"][r.model]["input_tokens"] += r.input_tokens
            provider_data["models"][r.model]["output_tokens"] += r.output_tokens

        return daily

    # ─── 综合报告 ───

    def daily_report(self, days: int = 7) -> str:
        """生成每日综合报告"""
        daily = self.analyze_token_usage(days)
        hist = {h["date"]: h for h in self.analyze_history(days)}
        sess = {s["date"]: s for s in self.analyze_sessions(days)}

        # 合并所有日期
        all_dates = sorted(
            set(list(daily.keys()) + list(hist.keys()) + list(sess.keys()))
        )
        if not all_dates:
            return "暂无数据。开始使用后会自动记录。\n\n提示：使用 CLI 工具或 Hook 记录 API 调用。\n"

        lines = []
        lines.append("=" * 72)
        lines.append("  📊 每日 API 使用报告")
        lines.append("=" * 72)

        grand_total_input = 0
        grand_total_output = 0
        grand_total_cost = 0.0

        for date in all_dates:
            ds = daily.get(date)
            hs = hist.get(date)
            ss = sess.get(date)

            lines.append(f"\n  📅 {date}")
            lines.append("  " + "-" * 68)

            # 会话统计
            if ss:
                lines.append(
                    f"  会话: {ss['session_count']} 次  "
                    f"总时长: {ss['total_minutes']} 分钟  "
                    f"平均: {ss['avg_minutes']} 分钟"
                )

            if hs:
                lines.append(f"  消息: {hs['message_count']} 条")

            # Token 统计
            if ds and ds.total_requests > 0:
                total_in = ds.total_input_tokens
                total_out = ds.total_output_tokens
                total_tok = total_in + total_out
                cost = ds.total_cost_usd

                grand_total_input += total_in
                grand_total_output += total_out
                grand_total_cost += cost

                lines.append(f"  Token 使用:")
                lines.append(f"    输入:  {total_in:>12,} tokens")
                lines.append(f"    输出:  {total_out:>12,} tokens")
                lines.append(f"    合计:  {total_tok:>12,} tokens")
                if cost > 0:
                    lines.append(f"    费用:  ${cost:.4f}")

                # 按提供商
                for provider, pdata in ds.by_provider.items():
                    p_in = pdata["input_tokens"]
                    p_out = pdata["output_tokens"]
                    p_total = p_in + p_out
                    lines.append(
                        f"\n  🏢 {provider.upper()}: "
                        f"{pdata['requests']} 请求, "
                        f"{p_total:,} tokens "
                        f"(入 {p_in:,} / 出 {p_out:,})"
                    )

                    # 按模型
                    for model, mdata in pdata["models"].items():
                        m_total = mdata["input_tokens"] + mdata["output_tokens"]
                        lines.append(
                            f"    └─ {model}: "
                            f"{m_total:,} tokens "
                            f"(入 {mdata['input_tokens']:,} / "
                            f"出 {mdata['output_tokens']:,})"
                        )
            else:
                if hs or ss:
                    lines.append("  Token 数据: (暂无 —— 需要配置追踪 Hook)")

        # 总计
        lines.append("\n" + "=" * 72)
        lines.append("  📈 统计周期汇总")
        lines.append("=" * 72)
        lines.append(f"  总输入 Token:  {grand_total_input:>12,}")
        lines.append(f"  总输出 Token:  {grand_total_output:>12,}")
        lines.append(f"  总计 Token:     {(grand_total_input + grand_total_output):>12,}")
        if grand_total_cost > 0:
            lines.append(f"  总费用:         ${grand_total_cost:.4f}")
        lines.append("")

        return "\n".join(lines)

    def deepseek_vs_kimi_report(self, days: int = 7) -> str:
        """DeepSeek vs Kimi 对比报告"""
        daily = self.analyze_token_usage(days)

        deepseek_total_in = 0
        deepseek_total_out = 0
        kimi_total_in = 0
        kimi_total_out = 0

        for ds in daily.values():
            for provider, pdata in ds.by_provider.items():
                if provider == "deepseek":
                    deepseek_total_in += pdata["input_tokens"]
                    deepseek_total_out += pdata["output_tokens"]
                elif provider == "kimi":
                    kimi_total_in += pdata["input_tokens"]
                    kimi_total_out += pdata["output_tokens"]

        lines = []
        lines.append("=" * 72)
        lines.append("  ⚔️  DeepSeek vs Kimi 2.5 对比")
        lines.append("=" * 72)
        lines.append("")

        ds_total = deepseek_total_in + deepseek_total_out
        km_total = kimi_total_in + kimi_total_out
        grand = ds_total + km_total

        lines.append(f"  {'':20} {'DeepSeek':>16} {'Kimi 2.5':>16}")
        lines.append("  " + "-" * 56)
        lines.append(
            f"  {'输入 Token':20} {f'{deepseek_total_in:,}':>16} {f'{kimi_total_in:,}':>16}"
        )
        lines.append(
            f"  {'输出 Token':20} {f'{deepseek_total_out:,}':>16} {f'{kimi_total_out:,}':>16}"
        )
        lines.append(
            f"  {'合计':20} {f'{ds_total:,}':>16} {f'{km_total:,}':>16}"
        )
        if grand > 0:
            lines.append(
                f"  {'占比':20} {f'{ds_total/grand*100:.1f}%':>16} {f'{km_total/grand*100:.1f}%':>16}"
            )
        lines.append("")

        return "\n".join(lines)
