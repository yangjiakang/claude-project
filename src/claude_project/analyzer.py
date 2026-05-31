"""API 使用分析器 —— 按天/按模型/按提供商聚合统计"""  # 模块文档字符串：API使用分析器，按天、按模型、按提供商进行聚合统计

import json  # 导入 JSON 模块，用于解析 JSON 格式的日志和会话文件
from collections import defaultdict  # 从 collections 模块导入 defaultdict，用于创建带默认值的字典
from dataclasses import dataclass, field  # 从 dataclasses 模块导入 dataclass 装饰器和 field 字段工厂函数
from datetime import datetime, timezone, timedelta  # 从 datetime 模块导入 datetime、timezone 和 timedelta 类
from pathlib import Path  # 从 pathlib 模块导入 Path 类，用于跨平台文件路径操作
from typing import Optional  # 从 typing 模块导入 Optional 类型注解，表示可选参数

from .tracker import UsageTracker, UsageRecord, detect_model_provider  # 从同包的 tracker 模块导入 UsageTracker、UsageRecord 和提供商检测函数

HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"  # Claude Code 的历史记录文件路径：用户主目录下的 .claude/history.jsonl
SESSIONS_DIR = Path.home() / ".claude" / "sessions"  # Claude Code 的会话数据目录路径：用户主目录下的 .claude/sessions


@dataclass  # 使用 dataclass 装饰器自动生成 __init__、__repr__、__eq__ 等方法
class DailyStats:  # 数据类定义：表示单日的 API 使用统计汇总数据
    date: str = ""  # 日期字段：统计对应的日期字符串，格式为 YYYY-MM-DD
    total_sessions: int = 0  # 会话总数：当天涉及的唯一会话数量
    total_requests: int = 0  # 请求总数：当天发起的 API 请求总次数
    total_input_tokens: int = 0  # 输入 Token 总数：当天所有请求的输入 Token 累计值
    total_output_tokens: int = 0  # 输出 Token 总数：当天所有请求的输出 Token 累计值
    total_cost_usd: float = 0.0  # 总费用：当天所有 API 调用的累计美元费用
    by_provider: dict = field(default_factory=lambda: defaultdict(lambda: {  # 按提供商分组的数据字典，使用 defaultdict 自动初始化嵌套结构
        "requests": 0,  # 该提供商的请求次数
        "input_tokens": 0,  # 该提供商的输入 Token 累计值
        "output_tokens": 0,  # 该提供商的输出 Token 累计值
        "cost_usd": 0.0,  # 该提供商的累计美元费用
        "models": defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0}),  # 该提供商下按模型分组的数据，包含输入和输出 Token 计数
    }))


@dataclass  # 使用 dataclass 装饰器自动生成 __init__、__repr__、__eq__ 等方法
class ProviderStats:  # 数据类定义：表示单个提供商的 API 使用统计数据
    provider: str  # 提供商名称字段：标识统计对应的 API 提供商
    requests: int = 0  # 请求次数：该提供商的 API 请求总数
    input_tokens: int = 0  # 输入 Token 数：该提供商的输入 Token 累计值
    output_tokens: int = 0  # 输出 Token 数：该提供商的输出 Token 累计值
    cost_usd: float = 0.0  # 费用：该提供商的累计美元费用
    models: dict = field(default_factory=dict)  # 模型数据字典：该提供商下各模型的 Token 使用详情


class UsageAnalyzer:  # 类定义：从多个数据源综合分析 API 使用情况，生成统计报告
    """从多个数据源分析 API 使用情况"""  # 类文档字符串：从 history.jsonl、sessions 和 token 日志等多个数据源分析 API 使用

    def __init__(self):  # 构造函数：初始化分析器，创建 UsageTracker 实例用于读取 API 使用日志
        self.tracker = UsageTracker()  # 创建 UsageTracker 实例，用于读取和查询 API 使用记录

    # ─── history.jsonl 分析（Claude Code 会话记录）───  # 分隔注释：以下方法负责分析 Claude Code 的历史记录文件

    def analyze_history(self, days: int = 7) -> list[dict]:  # 实例方法：分析 history.jsonl 文件，统计最近 N 天的每日消息数
        """分析 history.jsonl 获取每日会话统计"""  # 文档字符串：解析 history.jsonl 获取最近 N 天的每日消息数量统计
        if not HISTORY_FILE.exists():  # 检查历史记录文件是否存在
            return []  # 文件不存在则返回空列表

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000  # 计算时间截断值：N 天前的 UTC 时间毫秒级时间戳
        daily_counts = defaultdict(int)  # 创建默认值为 0 的字典，用于按日期累计消息数量

        with open(HISTORY_FILE) as f:  # 以只读模式打开历史记录文件
            for line in f:  # 逐行读取文件内容
                if not line.strip():  # 跳过空行（仅含空白字符的行）
                    continue  # 继续处理下一行
                try:  # 尝试解析 JSON 行
                    entry = json.loads(line)  # 将 JSON 行解析为 Python 字典对象
                    ts = entry.get("timestamp", 0)  # 获取条目的时间戳字段，不存在则默认为 0
                    if ts >= cutoff:  # 判断时间戳是否在截断时间之后（即属于最近 N 天）
                        date_str = datetime.fromtimestamp(  # 将毫秒时间戳转换为日期字符串
                            ts / 1000, tz=timezone.utc  # 除以 1000 转换为秒级时间戳，指定 UTC 时区
                        ).strftime("%Y-%m-%d")  # 格式化为 YYYY-MM-DD 格式的日期字符串
                        daily_counts[date_str] += 1  # 该日期的消息计数加一
                except json.JSONDecodeError:  # 捕获 JSON 解析异常（行内容不是有效 JSON）
                    continue  # 跳过该行，继续处理下一行

        return [  # 返回按日期排序的每日消息统计列表
            {"date": d, "message_count": c}  # 每个元素为包含日期和消息计数的字典
            for d, c in sorted(daily_counts.items())  # 对 daily_counts 字典按键（日期）排序后遍历
        ]

    # ─── sessions 分析 ───  # 分隔注释：以下方法负责分析会话数据目录中的 JSON 文件

    def analyze_sessions(self, days: int = 7) -> list[dict]:  # 实例方法：分析会话 JSON 文件，统计最近 N 天的会话时长
        """分析 session 数据获取会话时长"""  # 文档字符串：解析 session JSON 文件获取最近 N 天的会话时长统计
        if not SESSIONS_DIR.exists():  # 检查会话数据目录是否存在
            return []  # 目录不存在则返回空列表

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000  # 计算时间截断值：N 天前的 UTC 时间毫秒级时间戳
        daily_sessions = defaultdict(list)  # 创建默认值为空列表的字典，用于按日期存放会话时长列表

        for session_file in SESSIONS_DIR.glob("*.json"):  # 遍历会话目录中的所有 JSON 文件
            try:  # 尝试读取和解析会话文件
                with open(session_file) as f:  # 以只读模式打开会话 JSON 文件
                    s = json.load(f)  # 将会话文件内容解析为 Python 字典对象
                started = s.get("startedAt", 0)  # 获取会话开始时间的毫秒时间戳，不存在则默认为 0
                if started >= cutoff:  # 判断会话开始时间是否在截断时间之后（属于最近 N 天）
                    updated = s.get("updatedAt", started)  # 获取会话最后更新时间，如不存在则使用开始时间
                    duration_min = (updated - started) / 1000 / 60  # 计算会话持续时长（分钟）：（更新时间-开始时间）/1000/60
                    date_str = datetime.fromtimestamp(  # 将毫秒时间戳转换为日期字符串
                        started / 1000, tz=timezone.utc  # 除以 1000 转换为秒级时间戳，指定 UTC 时区
                    ).strftime("%Y-%m-%d")  # 格式化为 YYYY-MM-DD 格式的日期字符串
                    daily_sessions[date_str].append(duration_min)  # 将该会话时长（分钟）添加到对应日期的列表中
            except (json.JSONDecodeError, KeyError):  # 捕获 JSON 解析异常或缺失关键字段的异常
                continue  # 跳过该文件，继续处理下一个

        return [  # 返回按日期排序的每日会话统计列表
            {  # 每个元素为包含日期、会话数、总时长和平均时长的字典
                "date": d,  # 日期字符串
                "session_count": len(durations),  # 该日期的会话数量
                "total_minutes": round(sum(durations), 1),  # 该日期所有会话的总时长（分钟），四舍五入保留一位小数
                "avg_minutes": round(sum(durations) / len(durations), 1),  # 该日期会话的平均时长（分钟），四舍五入保留一位小数
            }
            for d, durations in sorted(daily_sessions.items())  # 对 daily_sessions 字典按键（日期）排序后遍历
        ]

    # ─── token 日志分析 ───  # 分隔注释：以下方法负责分析 API Token 使用日志

    def analyze_token_usage(self, days: int = 7) -> dict[str, DailyStats]:  # 实例方法：分析 Token 使用日志，返回按日期分组的 DailyStats 字典
        """分析 API 使用日志"""  # 文档字符串：解析 API 使用日志文件，返回最近 N 天的每日 Token 使用统计
        today = datetime.now(timezone.utc)  # 获取当前 UTC 日期时间作为统计截止日期
        start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")  # 计算统计起始日期：当前日期减去 N 天
        end_date = today.strftime("%Y-%m-%d")  # 统计结束日期：当前日期

        records = self.tracker.read_range(start_date, end_date)  # 从追踪器读取日期范围内的所有 API 使用记录
        daily: dict[str, DailyStats] = defaultdict(DailyStats)  # 创建默认值为 DailyStats 对象的字典，按日期分组统计

        for r in records:  # 遍历每一条 API 使用记录
            date = r.timestamp[:10]  # 从记录的时间戳中提取前 10 个字符作为日期字符串（YYYY-MM-DD）
            stats = daily[date]  # 获取该日期对应的 DailyStats 统计对象
            stats.date = date  # 设置统计对象的日期字段
            stats.total_requests += 1  # 请求总数加一
            stats.total_input_tokens += r.input_tokens  # 累加该请求的输入 Token 数
            stats.total_output_tokens += r.output_tokens  # 累加该请求的输出 Token 数
            stats.total_cost_usd += r.cost_usd  # 累加该请求的美元费用

            provider_data = stats.by_provider[r.provider]  # 获取该提供商在 by_provider 嵌套字典中的数据
            provider_data["requests"] += 1  # 该提供商的请求次数加一
            provider_data["input_tokens"] += r.input_tokens  # 累加该提供商的输入 Token 数
            provider_data["output_tokens"] += r.output_tokens  # 累加该提供商的输出 Token 数
            provider_data["cost_usd"] += r.cost_usd  # 累加该提供商的美元费用
            provider_data["models"][r.model]["input_tokens"] += r.input_tokens  # 累加该提供商下该模型的输入 Token 数
            provider_data["models"][r.model]["output_tokens"] += r.output_tokens  # 累加该提供商下该模型的输出 Token 数

        return daily  # 返回按日期分组的 DailyStats 字典

    # ─── 综合报告 ───  # 分隔注释：以下方法负责生成综合性的使用报告

    def daily_report(self, days: int = 7) -> str:  # 实例方法：生成包含会话、消息和 Token 使用的每日综合报告
        """生成每日综合报告"""  # 文档字符串：汇总多个数据源，生成最近 N 天的每日综合使用报告字符串
        daily = self.analyze_token_usage(days)  # 获取按日期分组的 Token 使用统计数据
        hist = {h["date"]: h for h in self.analyze_history(days)}  # 获取历史消息统计，并转换为以日期为键的字典
        sess = {s["date"]: s for s in self.analyze_sessions(days)}  # 获取会话时长统计，并转换为以日期为键的字典

        # 合并所有日期  # 注释：从三个数据源中收集所有出现的日期
        all_dates = sorted(  # 对所有日期去重并排序
            set(list(daily.keys()) + list(hist.keys()) + list(sess.keys()))  # 使用集合对三个数据源的日期键去重
        )
        if not all_dates:  # 如果没有任何日期数据
            return "暂无数据。开始使用后会自动记录。\n\n提示：使用 CLI 工具或 Hook 记录 API 调用。\n"  # 返回提示信息，告知用户暂无数据及如何开始记录

        lines = []  # 初始化空列表，用于收集报告的各行文本
        lines.append("=" * 72)  # 添加分隔线：72 个等号组成顶部边框
        lines.append("  📊 每日 API 使用报告")  # 添加报告标题
        lines.append("=" * 72)  # 添加分隔线：标题下方边框

        grand_total_input = 0  # 初始化总输入 Token 计数器
        grand_total_output = 0  # 初始化总输出 Token 计数器
        grand_total_cost = 0.0  # 初始化总费用累加器

        for date in all_dates:  # 遍历所有统计日期（按升序排列）
            ds = daily.get(date)  # 获取该日期的 Token 统计数据（可能为 None）
            hs = hist.get(date)  # 获取该日期的历史消息统计数据（可能为 None）
            ss = sess.get(date)  # 获取该日期的会话统计数据（可能为 None）

            lines.append(f"\n  📅 {date}")  # 添加日期标题行，使用日历图标
            lines.append("  " + "-" * 68)  # 添加日期下方的分隔线

            # 会话统计  # 注释：输出该日期的会话数量和时长信息
            if ss:  # 如果有会话统计数据
                lines.append(  # 添加会话统计行
                    f"  会话: {ss['session_count']} 次  "  # 会话次数
                    f"总时长: {ss['total_minutes']} 分钟  "  # 会话总时长（分钟）
                    f"平均: {ss['avg_minutes']} 分钟"  # 会话平均时长（分钟）
                )

            if hs:  # 如果有历史消息统计数据
                lines.append(f"  消息: {hs['message_count']} 条")  # 添加消息统计行

            # Token 统计  # 注释：输出该日期的 Token 使用详情（仅当有请求记录时）
            if ds and ds.total_requests > 0:  # 如果该日期有 Token 统计数据且请求数大于 0
                total_in = ds.total_input_tokens  # 获取该日期输入 Token 总数
                total_out = ds.total_output_tokens  # 获取该日期输出 Token 总数
                total_tok = total_in + total_out  # 计算该日期总 Token 数（输入+输出）
                cost = ds.total_cost_usd  # 获取该日期总费用

                grand_total_input += total_in  # 累加到全局输入 Token 总数
                grand_total_output += total_out  # 累加到全局输出 Token 总数
                grand_total_cost += cost  # 累加到全局总费用

                lines.append(f"  Token 使用:")  # 添加 Token 使用子标题
                lines.append(f"    输入:  {total_in:>12,} tokens")  # 添加输入 Token 数行，右对齐宽度12，千分位格式
                lines.append(f"    输出:  {total_out:>12,} tokens")  # 添加输出 Token 数行，右对齐宽度12，千分位格式
                lines.append(f"    合计:  {total_tok:>12,} tokens")  # 添加合计 Token 数行，右对齐宽度12，千分位格式
                if cost > 0:  # 如果费用大于 0
                    lines.append(f"    费用:  ${cost:.4f}")  # 添加费用行，保留 4 位小数

                # 按提供商  # 注释：按提供商分组显示该日期的 Token 使用详情
                for provider, pdata in ds.by_provider.items():  # 遍历每个提供商及其统计数据
                    p_in = pdata["input_tokens"]  # 获取该提供商的输入 Token 数
                    p_out = pdata["output_tokens"]  # 获取该提供商的输出 Token 数
                    p_total = p_in + p_out  # 计算该提供商的总 Token 数
                    lines.append(  # 添加提供商统计行
                        f"\n  🏢 {provider.upper()}: "  # 提供商名称（大写），使用建筑图标
                        f"{pdata['requests']} 请求, "  # 该提供商的请求次数
                        f"{p_total:,} tokens "  # 该提供商的总 Token 数（千分位格式）
                        f"(入 {p_in:,} / 出 {p_out:,})"  # 输入/输出 Token 详情（千分位格式）
                    )

                    # 按模型  # 注释：按模型细分该提供商下的 Token 使用情况
                    for model, mdata in pdata["models"].items():  # 遍历该提供商下的每个模型及其数据
                        m_total = mdata["input_tokens"] + mdata["output_tokens"]  # 计算该模型的总 Token 数
                        lines.append(  # 添加模型统计行
                            f"    └─ {model}: "  # 模型名称，使用树形连接符
                            f"{m_total:,} tokens "  # 该模型的总 Token 数（千分位格式）
                            f"(入 {mdata['input_tokens']:,} / "  # 输入 Token 详情（千分位格式）
                            f"出 {mdata['output_tokens']:,})"  # 输出 Token 详情（千分位格式）
                        )
            else:  # 如果该日期没有 Token 统计数据
                if hs or ss:  # 但如果有历史消息或会话统计数据
                    lines.append("  Token 数据: (暂无 —— 需要配置追踪 Hook)")  # 提示 Token 数据暂缺，需要配置追踪 Hook

        # 总计  # 注释：输出整个统计周期的汇总数据
        lines.append("\n" + "=" * 72)  # 添加分隔线和空行
        lines.append("  📈 统计周期汇总")  # 添加汇总标题
        lines.append("=" * 72)  # 添加汇总标题下方边框
        lines.append(f"  总输入 Token:  {grand_total_input:>12,}")  # 添加总输入 Token 数行
        lines.append(f"  总输出 Token:  {grand_total_output:>12,}")  # 添加总输出 Token 数行
        lines.append(f"  总计 Token:     {(grand_total_input + grand_total_output):>12,}")  # 添加总计 Token 数行
        if grand_total_cost > 0:  # 如果总费用大于 0
            lines.append(f"  总费用:         ${grand_total_cost:.4f}")  # 添加总费用行
        lines.append("")  # 添加空行作为报告结尾

        return "\n".join(lines)  # 将所有行用换行符连接为一个完整字符串并返回

    def deepseek_vs_kimi_report(self, days: int = 7) -> str:  # 实例方法：生成 DeepSeek 与 Kimi 的 Token 使用对比报告
        """DeepSeek vs Kimi 对比报告"""  # 文档字符串：生成 DeepSeek 和 Kimi 两家提供商的 Token 使用对比报告
        daily = self.analyze_token_usage(days)  # 获取最近 N 天的每日 Token 使用统计数据

        deepseek_total_in = 0  # 初始化 DeepSeek 总输入 Token 计数器
        deepseek_total_out = 0  # 初始化 DeepSeek 总输出 Token 计数器
        kimi_total_in = 0  # 初始化 Kimi 总输入 Token 计数器
        kimi_total_out = 0  # 初始化 Kimi 总输出 Token 计数器

        for ds in daily.values():  # 遍历每一天的 DailyStats 统计对象
            for provider, pdata in ds.by_provider.items():  # 遍历该日期下每个提供商的统计数据
                if provider == "deepseek":  # 如果提供商是 DeepSeek
                    deepseek_total_in += pdata["input_tokens"]  # 累加 DeepSeek 输入 Token 数
                    deepseek_total_out += pdata["output_tokens"]  # 累加 DeepSeek 输出 Token 数
                elif provider == "kimi":  # 如果提供商是 Kimi
                    kimi_total_in += pdata["input_tokens"]  # 累加 Kimi 输入 Token 数
                    kimi_total_out += pdata["output_tokens"]  # 累加 Kimi 输出 Token 数

        lines = []  # 初始化空列表，用于收集对比报告的各行文本
        lines.append("=" * 72)  # 添加分隔线：72 个等号组成顶部边框
        lines.append("  ⚔️  DeepSeek vs Kimi 2.5 对比")  # 添加对比报告标题
        lines.append("=" * 72)  # 添加分隔线：标题下方边框
        lines.append("")  # 添加空行

        ds_total = deepseek_total_in + deepseek_total_out  # 计算 DeepSeek 的总 Token 数（输入+输出）
        km_total = kimi_total_in + kimi_total_out  # 计算 Kimi 的总 Token 数（输入+输出）
        grand = ds_total + km_total  # 计算两家提供商的总 Token 数之和

        lines.append(f"  {'':20} {'DeepSeek':>16} {'Kimi 2.5':>16}")  # 添加表头行：空列、DeepSeek 列、Kimi 2.5 列
        lines.append("  " + "-" * 56)  # 添加表头下方分隔线
        lines.append(  # 添加输入 Token 对比行
            f"  {'输入 Token':20} {f'{deepseek_total_in:,}':>16} {f'{kimi_total_in:,}':>16}"  # 左列标签，右列 DeepSeek 和 Kimi 的输入 Token 数
        )
        lines.append(  # 添加输出 Token 对比行
            f"  {'输出 Token':20} {f'{deepseek_total_out:,}':>16} {f'{kimi_total_out:,}':>16}"  # 左列标签，右列 DeepSeek 和 Kimi 的输出 Token 数
        )
        lines.append(  # 添加合计 Token 对比行
            f"  {'合计':20} {f'{ds_total:,}':>16} {f'{km_total:,}':>16}"  # 左列标签，右列 DeepSeek 和 Kimi 的总 Token 数
        )
        if grand > 0:  # 如果总 Token 数大于 0（避免除以零）
            lines.append(  # 添加占比对比行
                f"  {'占比':20} {f'{ds_total/grand*100:.1f}%':>16} {f'{km_total/grand*100:.1f}%':>16}"  # 计算并显示各自的百分比占比
            )
        lines.append("")  # 添加空行作为报告结尾

        return "\n".join(lines)  # 将所有行用换行符连接为一个完整字符串并返回
