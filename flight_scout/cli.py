"""Command-line interface.

    python flightscout.py providers
    python flightscout.py search --nights 4:10 --regions 日本,东南亚
    python flightscout.py search --format csv --out result.csv
    python flightscout.py serve --port 8777
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import load_config
from .console_setup import setup_console
from .core import DEFAULT_WINDOWS, ParamError, SearchParams, default_windows
from .providers import ProviderError
from .report import to_console, to_csv, to_json, to_markdown
from .service import run_search


def _date_range(text: str, fallback: tuple[date, date]) -> tuple[date, date]:
    if not text:
        return fallback
    if ":" in text:
        a, b = text.split(":", 1)
    elif ".." in text:
        a, b = text.split("..", 1)
    else:
        a = b = text
    return date.fromisoformat(a.strip()), date.fromisoformat(b.strip())


def _int_range(text: str, fallback: tuple[int, int]) -> tuple[int, int]:
    if not text:
        return fallback
    if ":" in text:
        a, b = text.split(":", 1)
    elif "-" in text and not text.strip().startswith("-"):
        a, b = text.split("-", 1)
    else:
        a = b = text
    return int(a), int(b)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightscout",
        description="香港出发·圣诞机票雷达：找出假期里最便宜的目的地",
    )
    parser.add_argument("--config", help="配置文件路径 (默认 config.json)")
    sub = parser.add_subparsers(dest="command", required=False)

    p_search = sub.add_parser("search", help="搜索最便宜的目的地")
    w = default_windows()
    p_search.add_argument("--from", dest="origin", default="HKG", help="出发机场，默认 HKG")
    p_search.add_argument("--depart", default="", help="出发区间 YYYY-MM-DD:YYYY-MM-DD")
    p_search.add_argument("--return", dest="ret", default="", help="返程区间 YYYY-MM-DD:YYYY-MM-DD")
    p_search.add_argument("--nights", default="", help="停留晚数 a:b，默认 4:12")
    p_search.add_argument("--max-price", type=float, default=None, help="价格上限")
    p_search.add_argument("--regions", default="", help="区域，逗号分隔，如 日本,东南亚")
    p_search.add_argument("--direct", action="store_true", help="只要直飞")
    p_search.add_argument("--provider", default="auto", help="auto|demo|amadeus|travelpayouts")
    p_search.add_argument("--sort", default="price", choices=["price", "deal", "value", "distance", "nights", "date"])
    p_search.add_argument("--verify", type=int, default=0, help="用详细报价复核前 N 个结果（消耗 API 配额）")
    p_search.add_argument("--limit", type=int, default=200)
    p_search.add_argument("--format", dest="fmt", default="table", choices=["table", "csv", "json", "md"])
    p_search.add_argument("--top", type=int, default=25, help="表格/报告显示行数")
    p_search.add_argument("--out", default="", help="输出文件路径")

    p_serve = sub.add_parser("serve", help="启动网页仪表盘")
    p_serve.add_argument("--port", type=int, default=0, help="端口，默认读配置/8777")
    p_serve.add_argument("--host", default="", help="监听地址，默认 127.0.0.1")
    p_serve.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")

    p_export = sub.add_parser("export-site", help="生成 GitHub Pages 静态站点（快照）")
    p_export.add_argument("--out", default="site", help="输出目录，默认 site")
    p_export.add_argument("--origins", default="HKG", help="出发地，逗号分隔，如 HKG,SZX")
    p_export.add_argument("--provider", default="auto", help="auto|demo|serpapi|travelpayouts")
    p_export.add_argument("--depart", default="", help="出发区间 YYYY-MM-DD:YYYY-MM-DD")
    p_export.add_argument("--return", dest="ret", default="", help="返程区间")
    p_export.add_argument("--nights", default="", help="停留晚数 a:b")

    sub.add_parser("providers", help="查看可用数据源与配置状态")
    return parser


def cmd_providers(cfg) -> int:
    print(f"{'ID':<16}{'状态':<8}{'类型':<8}说明")
    print("-" * 88)
    for row in cfg.describe():
        status = "已配置" if row["ready"] else "未配置"
        kind = "实时" if row["live"] else "演示"
        print(f"{row['id']:<16}{status:<8}{kind:<8}{row['hint']}")
        if row["signup"]:
            print(f"{'':<32}注册: {row['signup']}")
    print()
    print("提示：设置环境变量 SERPAPI_KEY（推荐，免费 250 次/月），")
    print("     或 TRAVELPAYOUTS_TOKEN / AMADEUS_CLIENT_ID+SECRET，重启后自动使用实时数据。")
    print("     也可以直接启动网页，点右上角标签在页面里填写，无需命令行。")
    return 0


def cmd_search(args, cfg) -> int:
    dep_a, dep_b = _date_range(args.depart, (DEFAULT_WINDOWS["depart_from"], DEFAULT_WINDOWS["depart_to"]))
    ret_a, ret_b = _date_range(args.ret, (DEFAULT_WINDOWS["return_from"], DEFAULT_WINDOWS["return_to"]))
    n_min, n_max = _int_range(args.nights, (4, 12))
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]

    params = SearchParams.from_dict({
        "origin": args.origin,
        "depart_from": dep_a.isoformat(),
        "depart_to": dep_b.isoformat(),
        "return_from": ret_a.isoformat(),
        "return_to": ret_b.isoformat(),
        "nights_min": n_min,
        "nights_max": n_max,
        "max_price": args.max_price,
        "regions": regions,
        "direct_only": args.direct,
        "provider": args.provider,
        "sort": args.sort,
        "verify": args.verify,
        "limit": args.limit,
    })
    payload = run_search(params, cfg)

    if args.fmt == "csv":
        text = to_csv(payload)
    elif args.fmt == "json":
        text = to_json(payload)
    elif args.fmt == "md":
        text = to_markdown(payload, limit=args.top)
    else:
        text = to_console(payload, limit=args.top)

    if args.out:
        target = Path(args.out)
        if target.parent and str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8-sig" if args.fmt == "csv" else "utf-8")
        print(f"已写入 {target}")
        if args.fmt != "csv":
            print()
            print(text)
    else:
        print(text)
    return 0


def cmd_export_site(args, cfg) -> int:
    from .site_export import export_site

    origins = [o.strip().upper() for o in args.origins.split(",") if o.strip()]
    override: dict[str, str] = {}
    if args.depart or args.ret or args.nights:
        dep_a, dep_b = _date_range(args.depart, (DEFAULT_WINDOWS["depart_from"], DEFAULT_WINDOWS["depart_to"]))
        ret_a, ret_b = _date_range(args.ret, (DEFAULT_WINDOWS["return_from"], DEFAULT_WINDOWS["return_to"]))
        n_min, n_max = _int_range(args.nights, (4, 12))
        override = {
            "depart_from": dep_a.isoformat(),
            "depart_to": dep_b.isoformat(),
            "return_from": ret_a.isoformat(),
            "return_to": ret_b.isoformat(),
            "nights_min": n_min,
            "nights_max": n_max,
        }

    result = export_site(args.out, cfg, origins=origins, provider=args.provider, params_override=override)
    print(f"✓ 已生成静态站点：{result['out']}")
    print(f"  出发地：{', '.join(o['label'] for o in result['origins'])}")
    print(f"  报价条数：{result['offers']}   数据时间：{result['generated_at']}")
    print(f"  数据源：{'实时' if result['live'] else '演示数据'}")
    if not result["offers"]:
        print("✗ 快照里没有任何报价，检查密钥 / 额度 / 日期窗口", file=sys.stderr)
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    cfg = load_config(args.config)

    try:
        if args.command == "providers":
            return cmd_providers(cfg)
        if args.command == "search":
            return cmd_search(args, cfg)
        if args.command == "export-site":
            return cmd_export_site(args, cfg)
    except (ParamError, ProviderError, ValueError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    if args.command == "serve":
        from .server import serve

        port = args.port or cfg.port
        host = args.host or cfg.host
        return serve(cfg, host=host, port=port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
