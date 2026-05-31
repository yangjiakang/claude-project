"""CLI 入口 —— 命令行分析工具 & 网页资源爬取器"""
# 本模块是整个项目的命令行入口，基于 argparse 实现子命令架构

import argparse  # Python 标准库的命令行参数解析器
import sys  # 系统相关操作，用于退出程序和输出到 stderr
from pathlib import Path  # 面向对象的文件路径处理
from datetime import datetime, timezone  # 日期时间处理（导入但供扩展使用）

from .tracker import UsageTracker, detect_model_provider  # 导入 API 使用追踪器和模型识别函数
from .analyzer import UsageAnalyzer  # 导入使用量分析器
from .scraper import ImageScraper, ScrapeConfig  # 导入图片爬取器和配置类
from .video_scraper import VideoScraper, VideoScrapeConfig  # 导入视频爬取器和配置类


def cmd_report(args):
    """生成每日报告 —— 显示指定天数内的 API 使用统计"""
    analyzer = UsageAnalyzer()  # 实例化使用量分析器
    print(analyzer.daily_report(days=args.days))  # 调用日报生成方法并输出


def cmd_compare(args):
    """DeepSeek vs Kimi 对比 —— 横向对比两个模型的 Token 用量"""
    analyzer = UsageAnalyzer()  # 实例化使用量分析器
    print(analyzer.deepseek_vs_kimi_report(days=args.days))  # 调用对比报告方法并输出


def cmd_record(args):
    """手动记录一条 API 调用 —— 将单次调用信息写入追踪日志"""
    tracker = UsageTracker()  # 实例化使用量追踪器
    tracker.quick_record(  # 调用快捷记录方法
        session_id=args.session or "manual",  # 会话 ID，默认 "manual"
        model=args.model,  # 模型名称
        input_tokens=args.input_tokens,  # 输入 Token 数
        output_tokens=args.output_tokens,  # 输出 Token 数
        cost_usd=args.cost or 0.0,  # 费用（USD），默认 0
        endpoint=args.endpoint or "",  # API 端点 URL
    )
    provider = detect_model_provider(args.model)  # 自动检测模型提供商
    print(  # 输出成功确认消息
        f"✅ 已记录: {args.model} ({provider}) "  # 模型名和提供商
        f"入 {args.input_tokens:,} / 出 {args.output_tokens:,} tokens"  # Token 用量统计
    )


def cmd_status(args):
    """查看追踪状态 —— 显示数据目录、记录数、Token 总量等概览信息"""
    tracker = UsageTracker()  # 实例化使用量追踪器
    analyzer = UsageAnalyzer()  # 实例化使用量分析器

    dates = tracker.available_dates()  # 获取有追踪记录的所有日期
    sessions = analyzer.analyze_sessions(days=30)  # 分析近 30 天的会话数据
    history = analyzer.analyze_history(days=30)  # 分析近 30 天的历史记录

    print("📊 API 使用追踪状态")  # 状态信息标题
    print("=" * 50)  # 分隔线
    print(f"  数据目录: {tracker.logs_dir}")  # 显示日志存储目录路径
    print(f"  有记录的天数: {len(dates)}")  # 显示有数据的天数
    if dates:  # 如果有数据
        print(f"  范围: {dates[0]} ~ {dates[-1]}")  # 显示数据日期范围

    # 统计日志中的记录数和 Token 总量
    total_records = 0  # 累计记录条数
    total_tokens = 0  # 累计 Token 数量
    for d in dates:  # 遍历每个有记录的日期
        records = tracker.read_day(d)  # 读取当天的所有记录
        total_records += len(records)  # 累加记录数
        for r in records:  # 遍历当天的每条记录
            total_tokens += r.input_tokens + r.output_tokens  # 累加输入和输出 Token

    print(f"  API 调用记录: {total_records} 条")  # 显示总记录数
    print(f"  总 Token: {total_tokens:,}")  # 显示 Token 总量（千分位格式）
    print(f"  Claude Code 会话: {len(sessions)} 个")  # 显示检测到的会话数
    if history:  # 如果有历史记录
        total_msgs = sum(h["message_count"] for h in history)  # 计算消息总数
        print(f"  消息数: {total_msgs} 条")  # 显示消息总数
    print()  # 末尾空行


def cmd_scrape(args):
    """从网页抓取图片 —— 解析页面中的 img/picture/meta 等标签并下载"""
    # 解析扩展名过滤参数
    exts = set()  # 用集合存储允许的扩展名，确保唯一性
    if args.extensions:  # 如果用户指定了扩展名过滤
        for ext in args.extensions.split(","):  # 逗号分隔多个扩展名
            ext = ext.strip().lstrip(".")  # 去空格和开头的点号
            if ext:  # 非空才添加
                exts.add(f".{ext}")  # 统一加上点号前缀

    config = ScrapeConfig(  # 构建图片爬取配置对象
        url=args.url,  # 目标网页 URL
        output_dir=Path(args.output).resolve(),  # 输出目录（转为绝对路径）
        max_images=args.max,  # 最大下载数量
        extensions=exts,  # 扩展名过滤集合
        recursive=args.recursive,  # 是否递归爬取
        max_depth=args.depth,  # 递归最大深度
        timeout=args.timeout,  # 请求超时时间
    )

    scraper = ImageScraper(config)  # 实例化图片爬取器
    result = scraper.scrape()  # 执行爬取并获取结果统计

    # 输出爬取结果摘要
    print(f"\n{'=' * 50}")  # 分隔线
    print(f"  抓取完成: {args.url}")  # 显示目标 URL
    print(f"{'=' * 50}")  # 分隔线
    print(f"  下载成功: {result['downloaded']} 张")  # 成功下载数
    print(f"  跳过:     {result['skipped']} 张")  # 跳过数
    if result["errors"]:  # 如果有失败
        print(f"  失败:     {result['errors']} 张")  # 失败数
    if result.get("pages_visited", 1) > 1:  # 如果访问了多个页面（递归模式）
        print(f"  访问页面: {result['pages_visited']} 个")  # 访问页面数
    print(f"  保存目录: {config.output_dir}")  # 保存目录路径
    print()  # 末尾空行


def cmd_video_scrape(args):
    """从网页抓取视频 —— 解析页面中的 video/source/iframe/JS 配置等并下载"""
    # 解析扩展名过滤参数
    exts = set()  # 用集合存储允许的扩展名，确保唯一性
    if args.extensions:  # 如果用户指定了扩展名过滤
        for ext in args.extensions.split(","):  # 逗号分隔多个扩展名
            ext = ext.strip().lstrip(".")  # 去空格和开头的点号
            if ext:  # 非空才添加
                exts.add(f".{ext}")  # 统一加上点号前缀

    config = VideoScrapeConfig(  # 构建视频爬取配置对象
        url=args.url,  # 目标网页 URL
        output_dir=Path(args.output).resolve(),  # 输出目录（转为绝对路径）
        max_videos=args.max,  # 最大下载数量
        min_size_kb=args.min_size,  # 最小文件大小过滤
        extensions=exts,  # 扩展名过滤集合
        recursive=args.recursive,  # 是否递归爬取
        max_depth=args.depth,  # 递归最大深度
        timeout=args.timeout,  # 请求超时时间
        concurrent=args.concurrent,  # 并发下载线程数
        skip_head=args.skip_head,  # 是否跳过 HEAD 预检
        convert_to=args.convert_to or "",  # 下载后转换的目标格式
        convert_preset=args.convert_preset or "medium",  # 编码速度预设
        convert_remove_original=args.convert_remove,  # 转换后是否删除原文件
    )

    scraper = VideoScraper(config)  # 实例化视频爬取器
    result = scraper.scrape()  # 执行爬取并获取结果统计

    # 输出爬取结果摘要
    print(f"\n{'=' * 50}")  # 分隔线
    print(f"  抓取完成: {args.url}")  # 显示目标 URL
    print(f"{'=' * 50}")  # 分隔线
    print(f"  下载成功: {result['downloaded']} 个")  # 成功下载数
    print(f"  跳过:     {result['skipped']} 个")  # 跳过数
    if result["errors"]:  # 如果有失败
        print(f"  失败:     {result['errors']} 个")  # 失败数
    if result.get("pages_visited", 1) > 1:  # 如果访问了多个页面（递归模式）
        print(f"  访问页面: {result['pages_visited']} 个")  # 访问页面数
    if result.get("converted"):  # 如果有格式转换
        print(f"  格式转换: {result['converted']} 个")  # 转换成功数
    print(f"  保存目录: {config.output_dir}")  # 保存目录路径
    print()  # 末尾空行


def main():
    """CLI 主入口 —— 注册所有子命令并解析参数"""
    parser = argparse.ArgumentParser(  # 创建命令行参数解析器
        description="API 使用分析工具 & 网页资源爬取器",  # 工具描述
        prog="api-usage",  # 命令行程序名
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")  # 创建子命令容器

    # ——— report 子命令 ———
    p_report = subparsers.add_parser("report", help="生成每日报告")  # 注册 report 子命令
    p_report.add_argument("--days", type=int, default=7, help="统计天数 (默认 7)")  # 统计天数参数
    p_report.set_defaults(func=cmd_report)  # 绑定处理函数

    # ——— compare 子命令 ———
    p_compare = subparsers.add_parser("compare", help="DeepSeek vs Kimi 对比")  # 注册 compare 子命令
    p_compare.add_argument("--days", type=int, default=7, help="统计天数 (默认 7)")  # 统计天数参数
    p_compare.set_defaults(func=cmd_compare)  # 绑定处理函数

    # ——— record 子命令 ———
    p_record = subparsers.add_parser("record", help="手动记录 API 调用")  # 注册 record 子命令
    p_record.add_argument("--model", "-m", required=True, help="模型名称")  # 模型名称（必填）
    p_record.add_argument("--input-tokens", "-i", type=int, required=True)  # 输入 Token 数（必填）
    p_record.add_argument("--output-tokens", "-o", type=int, required=True)  # 输出 Token 数（必填）
    p_record.add_argument("--cost", "-c", type=float, help="费用 (USD)")  # 费用（可选）
    p_record.add_argument("--endpoint", "-e", help="API 端点")  # API 端点（可选）
    p_record.add_argument("--session", "-s", help="会话 ID")  # 会话 ID（可选）
    p_record.set_defaults(func=cmd_record)  # 绑定处理函数

    # ——— status 子命令 ———
    p_status = subparsers.add_parser("status", help="查看追踪状态")  # 注册 status 子命令
    p_status.set_defaults(func=cmd_status)  # 绑定处理函数（无额外参数）

    # ——— scrape 子命令（图片爬取） ———
    p_scrape = subparsers.add_parser("scrape", help="从网页抓取图片")  # 注册 scrape 子命令
    p_scrape.add_argument("url", help="目标网页 URL")  # 位置参数：URL
    p_scrape.add_argument("--output", "-o", default="./images", help="图片保存目录 (默认 ./images)")  # 输出目录
    p_scrape.add_argument("--max", "-n", type=int, default=0, help="最大下载数量 (0=不限制)")  # 最大数量
    p_scrape.add_argument(  # 扩展名过滤
        "--extensions", "-e", default="",  # 默认为空（不过滤）
        help="文件扩展名过滤，逗号分隔 (如 jpg,png)"  # 帮助文本
    )
    p_scrape.add_argument(  # 递归开关
        "--recursive", "-r", action="store_true",  # 布尔标志
        help="递归抓取同域链接页面"  # 帮助文本
    )
    p_scrape.add_argument(  # 递归深度
        "--depth", "-d", type=int, default=2,  # 默认深度为 2
        help="递归深度 (默认 2，仅在 -r 时生效)"  # 帮助文本
    )
    p_scrape.add_argument("--timeout", "-t", type=int, default=30, help="请求超时秒数 (默认 30)")  # 超时时间
    p_scrape.set_defaults(func=cmd_scrape)  # 绑定处理函数

    # ——— video 子命令（视频爬取） ———
    p_video = subparsers.add_parser("video", help="从网页抓取视频")  # 注册 video 子命令
    p_video.add_argument("url", help="目标网页 URL")  # 位置参数：URL
    p_video.add_argument("--output", "-o", default="./videos", help="视频保存目录 (默认 ./videos)")  # 输出目录
    p_video.add_argument("--max", "-n", type=int, default=0, help="最大下载数量 (0=不限制)")  # 最大数量
    p_video.add_argument("--min-size", "-s", type=int, default=0, help="最小文件大小 (KB)，过滤太小的文件")  # 最小文件大小
    p_video.add_argument(  # 扩展名过滤
        "--extensions", "-e", default="",  # 默认为空（不过滤）
        help="文件扩展名过滤，逗号分隔 (如 mp4,webm)"  # 帮助文本
    )
    p_video.add_argument(  # 递归开关
        "--recursive", "-r", action="store_true",  # 布尔标志
        help="递归抓取同域链接页面"  # 帮助文本
    )
    p_video.add_argument(  # 递归深度
        "--depth", "-d", type=int, default=2,  # 默认深度为 2
        help="递归深度 (默认 2，仅在 -r 时生效)"  # 帮助文本
    )
    p_video.add_argument("--timeout", "-t", type=int, default=60, help="请求超时秒数 (默认 60)")  # 超时时间（视频下载更长）
    p_video.add_argument(  # 并发下载线程数
        "--concurrent", "-j", type=int, default=1,  # 默认 1 为串行
        help="并发下载线程数 (默认 1 串行，设为 3~5 可大幅加速多视频下载)"  # 帮助文本
    )
    p_video.add_argument(  # 跳过 HEAD 预检
        "--skip-head", action="store_true",  # 布尔标志
        help="跳过 HEAD 预检请求，省去一次网络往返，加快单文件下载启动"  # 帮助文本
    )
    p_video.add_argument(  # 下载后转换格式
        "--convert-to", default="",  # 默认为空（不转换）
        help="下载完成后转换为指定格式 (如 mp4、webm、mkv、mov、avi、gif)"  # 帮助文本
    )
    p_video.add_argument(  # 编码速度预设
        "--convert-preset", default="medium",  # 默认 medium 平衡
        choices=["fast", "medium", "slow"],  # 限定三种选项
        help="编码速度预设: fast(快)/medium(平衡)/slow(高质量)，默认 medium"  # 帮助文本
    )
    p_video.add_argument(  # 转换后删除原文件
        "--convert-remove", action="store_true",  # 布尔标志
        help="格式转换成功后删除原始视频文件"  # 帮助文本
    )
    p_video.set_defaults(func=cmd_video_scrape)  # 绑定处理函数

    args = parser.parse_args()  # 解析命令行参数
    if args.command is None:  # 如果用户没有指定任何子命令
        parser.print_help()  # 打印帮助信息
        sys.exit(1)  # 以非零状态码退出
    args.func(args)  # 调用对应子命令的处理函数


if __name__ == "__main__":  # 当脚本直接运行时
    main()  # 启动 CLI 主函数
