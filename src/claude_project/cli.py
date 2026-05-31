"""CLI 入口 —— 命令行分析工具"""

import argparse
import sys
from datetime import datetime, timezone

from .tracker import UsageTracker, detect_model_provider
from .analyzer import UsageAnalyzer
from .scraper import ImageScraper, ScrapeConfig


def cmd_report(args):
    """生成每日报告"""
    analyzer = UsageAnalyzer()
    print(analyzer.daily_report(days=args.days))


def cmd_compare(args):
    """DeepSeek vs Kimi 对比"""
    analyzer = UsageAnalyzer()
    print(analyzer.deepseek_vs_kimi_report(days=args.days))


def cmd_record(args):
    """手动记录一条 API 调用"""
    tracker = UsageTracker()
    tracker.quick_record(
        session_id=args.session or "manual",
        model=args.model,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        cost_usd=args.cost or 0.0,
        endpoint=args.endpoint or "",
    )
    provider = detect_model_provider(args.model)
    print(
        f"✅ 已记录: {args.model} ({provider}) "
        f"入 {args.input_tokens:,} / 出 {args.output_tokens:,} tokens"
    )


def cmd_status(args):
    """查看追踪状态"""
    tracker = UsageTracker()
    analyzer = UsageAnalyzer()

    dates = tracker.available_dates()
    sessions = analyzer.analyze_sessions(days=30)
    history = analyzer.analyze_history(days=30)

    print("📊 API 使用追踪状态")
    print("=" * 50)
    print(f"  数据目录: {tracker.logs_dir}")
    print(f"  有记录的天数: {len(dates)}")
    if dates:
        print(f"  范围: {dates[0]} ~ {dates[-1]}")

    # 统计日志中的记录数
    total_records = 0
    total_tokens = 0
    for d in dates:
        records = tracker.read_day(d)
        total_records += len(records)
        for r in records:
            total_tokens += r.input_tokens + r.output_tokens

    print(f"  API 调用记录: {total_records} 条")
    print(f"  总 Token: {total_tokens:,}")
    print(f"  Claude Code 会话: {len(sessions)} 个")
    if history:
        total_msgs = sum(h["message_count"] for h in history)
        print(f"  消息数: {total_msgs} 条")
    print()


def cmd_scrape(args):
    """从网页抓取图片"""
    from pathlib import Path

    # 解析扩展名过滤
    exts = set()
    if args.extensions:
        for ext in args.extensions.split(","):
            ext = ext.strip().lstrip(".")
            if ext:
                exts.add(f".{ext}")

    config = ScrapeConfig(
        url=args.url,
        output_dir=Path(args.output).resolve(),
        max_images=args.max,
        extensions=exts,
        recursive=args.recursive,
        max_depth=args.depth,
        timeout=args.timeout,
    )

    scraper = ImageScraper(config)
    result = scraper.scrape()

    # 输出摘要
    print(f"\n{'=' * 50}")
    print(f"  抓取完成: {args.url}")
    print(f"{'=' * 50}")
    print(f"  下载成功: {result['downloaded']} 张")
    print(f"  跳过:     {result['skipped']} 张")
    if result["errors"]:
        print(f"  失败:     {result['errors']} 张")
    if result.get("pages_visited", 1) > 1:
        print(f"  访问页面: {result['pages_visited']} 个")
    print(f"  保存目录: {config.output_dir}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="API 使用分析工具",
        prog="api-usage",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # report
    p_report = subparsers.add_parser("report", help="生成每日报告")
    p_report.add_argument("--days", type=int, default=7, help="统计天数 (默认 7)")
    p_report.set_defaults(func=cmd_report)

    # compare
    p_compare = subparsers.add_parser("compare", help="DeepSeek vs Kimi 对比")
    p_compare.add_argument("--days", type=int, default=7, help="统计天数 (默认 7)")
    p_compare.set_defaults(func=cmd_compare)

    # record
    p_record = subparsers.add_parser("record", help="手动记录 API 调用")
    p_record.add_argument("--model", "-m", required=True, help="模型名称")
    p_record.add_argument("--input-tokens", "-i", type=int, required=True)
    p_record.add_argument("--output-tokens", "-o", type=int, required=True)
    p_record.add_argument("--cost", "-c", type=float, help="费用 (USD)")
    p_record.add_argument("--endpoint", "-e", help="API 端点")
    p_record.add_argument("--session", "-s", help="会话 ID")
    p_record.set_defaults(func=cmd_record)

    # status
    p_status = subparsers.add_parser("status", help="查看追踪状态")
    p_status.set_defaults(func=cmd_status)

    # scrape
    p_scrape = subparsers.add_parser("scrape", help="从网页抓取图片")
    p_scrape.add_argument("url", help="目标网页 URL")
    p_scrape.add_argument("--output", "-o", default="./images", help="图片保存目录 (默认 ./images)")
    p_scrape.add_argument("--max", "-n", type=int, default=0, help="最大下载数量 (0=不限制)")
    p_scrape.add_argument(
        "--extensions", "-e", default="",
        help="文件扩展名过滤，逗号分隔 (如 jpg,png)"
    )
    p_scrape.add_argument(
        "--recursive", "-r", action="store_true",
        help="递归抓取同域链接页面"
    )
    p_scrape.add_argument(
        "--depth", "-d", type=int, default=2,
        help="递归深度 (默认 2，仅在 -r 时生效)"
    )
    p_scrape.add_argument("--timeout", "-t", type=int, default=30, help="请求超时秒数 (默认 30)")
    p_scrape.set_defaults(func=cmd_scrape)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
