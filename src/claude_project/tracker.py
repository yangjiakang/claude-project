"""API 使用追踪器 —— 记录每次 API 调用"""  # 模块文档字符串：API使用追踪器，用于记录每次API调用

import json  # 导入 JSON 模块，用于序列化和反序列化 JSON 数据
import os  # 导入 OS 模块，用于操作系统相关的文件和目录操作
import time  # 导入 time 模块，用于获取时间戳和进行时间相关操作
from dataclasses import dataclass, asdict  # 从 dataclasses 模块导入 dataclass 装饰器和 asdict 转换函数
from datetime import datetime, timezone  # 从 datetime 模块导入 datetime 类和 timezone 时区类
from pathlib import Path  # 从 pathlib 模块导入 Path 类，用于跨平台路径操作
from typing import Optional  # 从 typing 模块导入 Optional 类型注解，表示可选参数

DATA_DIR = Path.home() / ".claude" / "api-usage"  # 数据根目录：用户主目录下的 .claude/api-usage 文件夹
LOGS_DIR = DATA_DIR / "logs"  # 日志子目录：存放按日期分割的 JSONL 日志文件

SUPPORTED_MODELS = {  # 支持的模型字典，按提供商分类列出所有已知模型名称
    "deepseek": [  # DeepSeek 提供商支持的模型列表
        "deepseek-v4-pro",  # DeepSeek V4 Pro 模型
        "deepseek-v4-flash",  # DeepSeek V4 Flash 模型（轻量快速版）
        "deepseek-v4",  # DeepSeek V4 标准模型
        "deepseek-chat",  # DeepSeek Chat 通用对话模型
        "deepseek-reasoner",  # DeepSeek Reasoner 推理模型
    ],
    "kimi": [  # Kimi（月之暗面）提供商支持的模型列表
        "kimi-2.5",  # Kimi 2.5 模型
        "kimi-2.0",  # Kimi 2.0 模型
        "moonshot-v1-8k",  # Moonshot V1 8K 上下文模型
        "moonshot-v1-32k",  # Moonshot V1 32K 上下文模型
        "moonshot-v1-128k",  # Moonshot V1 128K 上下文模型
    ],
    "claude": [  # Claude（Anthropic）提供商支持的模型列表
        "claude-opus-4-8",  # Claude Opus 4 模型（最强旗舰版）
        "claude-sonnet-4-6",  # Claude Sonnet 4 模型（平衡性能版）
        "claude-haiku-4-5-20251001",  # Claude Haiku 4.5 模型（快速轻量版，2025年10月1日版本）
    ],
}


def detect_model_provider(model_name: str) -> str:  # 函数定义：根据模型名称字符串检测对应的提供商名称
    """根据模型名称识别提供商"""  # 文档字符串：根据模型名称字符串识别并返回提供商名称
    lowered = model_name.lower()  # 将模型名称转换为小写，以实现大小写不敏感的匹配
    for provider, models in SUPPORTED_MODELS.items():  # 遍历支持的模型字典，获取每个提供商及其模型列表
        for m in models:  # 遍历当前提供商下的每个模型名称
            if m in lowered:  # 检查当前模型名称是否出现在小写化的输入模型名称中
                return provider  # 匹配成功，返回对应的提供商名称（如 "deepseek"、"kimi"、"claude"）
    return "unknown"  # 未匹配到任何已知模型，返回 "unknown" 表示未知提供商


@dataclass  # 使用 dataclass 装饰器自动生成 __init__、__repr__、__eq__ 等方法
class UsageRecord:  # 数据类定义：表示单次 API 调用的使用记录
    timestamp: str          # ISO 8601  # 时间戳字段：ISO 8601 格式的字符串，记录调用发生的时间
    session_id: str  # 会话 ID 字段：标识该次 API 调用所属的会话
    model: str  # 模型字段：记录使用的模型名称（如 "deepseek-v4-pro"）
    provider: str  # 提供商字段：记录 API 提供商名称（如 "deepseek"、"kimi"）
    input_tokens: int  # 输入 Token 数字段：记录本次调用消耗的输入 Token 数量
    output_tokens: int  # 输出 Token 数字段：记录本次调用生成的输出 Token 数量
    cost_usd: float  # 费用字段：记录本次 API 调用的费用，以美元计
    endpoint: str           # e.g. "https://api.deepseek.com/anthropic"  # 端点字段：记录 API 请求的目标 URL 地址


class UsageTracker:  # 类定义：API 使用量追踪器，负责持久化记录每次 API 调用
    """API 使用量追踪器"""  # 类文档字符串：API 使用量追踪器，管理使用记录的写入和读取

    def __init__(self, logs_dir: Optional[Path] = None):  # 构造函数：初始化追踪器，可指定自定义日志目录
        self.logs_dir = logs_dir or LOGS_DIR  # 设置日志目录：使用传入的目录或默认的 LOGS_DIR
        self.logs_dir.mkdir(parents=True, exist_ok=True)  # 创建日志目录：递归创建父目录，目录已存在时不报错

    def _daily_file(self, date_str: Optional[str] = None) -> Path:  # 私有方法：根据日期字符串获取对应的日志文件路径
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")  # 获取日期字符串：如未传入则使用当前 UTC 日期
        return self.logs_dir / f"{date_str}.jsonl"  # 返回日志文件路径：格式为 日志目录/YYYY-MM-DD.jsonl

    def record(self, record: UsageRecord) -> None:  # 实例方法：将一条 UsageRecord 追加写入对应的日期日志文件
        """追加一条使用记录"""  # 文档字符串：向当天的日志文件中追加一条使用记录
        daily_file = self._daily_file(record.timestamp[:10])  # 根据记录的时间戳前10位（日期部分）获取日志文件路径
        with open(daily_file, "a") as f:  # 以追加模式打开日志文件
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")  # 将记录转为字典并序列化为 JSON，写入一行并添加换行符

    def read_day(self, date_str: str) -> list[UsageRecord]:  # 实例方法：读取指定日期的所有使用记录
        """读取某一天的所有记录"""  # 文档字符串：读取并返回指定日期的所有使用记录列表
        daily_file = self._daily_file(date_str)  # 根据日期字符串获取对应的日志文件路径
        if not daily_file.exists():  # 检查日志文件是否存在
            return []  # 文件不存在则返回空列表
        records = []  # 初始化空列表，用于存放解析出的 UsageRecord 对象
        with open(daily_file) as f:  # 以只读模式打开日志文件
            for line in f:  # 逐行读取文件内容
                if line.strip():  # 跳过空行（只含空白字符的行）
                    records.append(UsageRecord(**json.loads(line)))  # 将 JSON 行反序列化为字典，解包后创建 UsageRecord 对象并添加到列表
        return records  # 返回该日期的所有使用记录列表

    def read_range(self, start_date: str, end_date: str) -> list[UsageRecord]:  # 实例方法：读取日期范围内的所有使用记录
        """读取日期范围内的所有记录"""  # 文档字符串：读取指定起止日期之间的所有使用记录
        records = []  # 初始化空列表，用于存放范围内所有记录
        for f in sorted(self.logs_dir.glob("*.jsonl")):  # 遍历日志目录中所有 .jsonl 文件，按文件名排序
            date_str = f.stem  # "2026-05-30"  # 获取文件名（不含扩展名）作为日期字符串，例如 "2026-05-30"
            if start_date <= date_str <= end_date:  # 判断日期是否在指定的起止范围内
                records.extend(self.read_day(date_str))  # 读取该日期的所有记录并合并到总列表中
        return records  # 返回日期范围内的所有使用记录列表

    def available_dates(self) -> list[str]:  # 实例方法：获取所有有记录数据的日期列表
        """返回有记录的日期列表"""  # 文档字符串：返回日志目录中存在记录的所有日期列表
        return sorted(  # 对日期列表进行排序后返回
            [f.stem for f in self.logs_dir.glob("*.jsonl")]  # 列表推导式：遍历所有 .jsonl 文件，提取文件名（不含扩展名）作为日期字符串
        )

    def quick_record(  # 实例方法：快速记录一次 API 调用，自动检测提供商和时间戳
        self,  # 实例自身引用
        session_id: str,  # 会话 ID 参数：当前会话的唯一标识符
        model: str,  # 模型参数：使用的模型名称
        input_tokens: int,  # 输入 Token 数参数：本次调用消耗的输入 Token 数量
        output_tokens: int,  # 输出 Token 数参数：本次调用生成的输出 Token 数量
        cost_usd: float = 0.0,  # 费用参数：本次调用的美元费用，默认为 0.0
        endpoint: str = "",  # 端点参数：API 请求的目标 URL，默认为空字符串
    ) -> None:  # 返回值类型：无返回值
        """快速记录（自动检测 provider 和时间）"""  # 文档字符串：便捷方法，自动检测提供商和记录时间戳
        now = datetime.now(timezone.utc).isoformat()  # 获取当前 UTC 时间的 ISO 8601 格式字符串作为时间戳
        provider = detect_model_provider(model)  # 调用检测函数，根据模型名称自动识别提供商
        if not endpoint:  # 判断端点是否为空（未手动指定）
            if provider == "deepseek":  # 如果提供商是 DeepSeek
                endpoint = "https://api.deepseek.com/anthropic"  # 设置 DeepSeek 的默认 API 端点地址
            elif provider == "kimi":  # 如果提供商是 Kimi
                endpoint = "https://api.moonshot.cn/v1"  # 设置 Kimi（月之暗面）的默认 API 端点地址
        self.record(UsageRecord(  # 调用 record 方法，传入新创建的 UsageRecord 对象
            timestamp=now,  # 使用当前 UTC 时间作为时间戳
            session_id=session_id,  # 传入会话 ID
            model=model,  # 传入模型名称
            provider=provider,  # 传入自动检测的提供商名称
            input_tokens=input_tokens,  # 传入输入 Token 数
            output_tokens=output_tokens,  # 传入输出 Token 数
            cost_usd=cost_usd,  # 传入费用
            endpoint=endpoint,  # 传入 API 端点地址
        ))
