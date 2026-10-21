"""Exporters: CSV, Markdown and a width-aware console table."""

from __future__ import annotations

import csv
import io
import json
import unicodedata
from typing import Any

from . import data


def origin_city(code: str | None) -> str:
    ap = data.ORIGINS.get((code or "HKG").upper())
    return ap.city_zh if ap else (code or "香港")


COLUMNS = [
    ("city", "目的地"),
    ("code", "机场"),
    ("country", "国家/地区"),
    ("region", "区域"),
    ("price", "价格"),
    ("currency", "币种"),
    ("depart", "出发"),
    ("return", "返程"),
    ("nights", "晚数"),
    ("airline", "航司"),
    ("stops", "转机"),
    ("duration_label", "航程"),
    ("distance_km", "距离km"),
    ("price_per_1000km", "每千公里"),
    ("deal_score", "性价比"),
    ("tags", "标签"),
    ("source", "数据源"),
]


def to_csv(payload: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([label for _, label in COLUMNS] + ["Google Flights", "Trip.com"])
    for row in payload["results"]:
        out = []
        for key, _ in COLUMNS:
            value = row.get(key, "")
            if key == "tags":
                value = " / ".join(value or [])
            out.append(value)
        links = row.get("booking_links") or {}
        out.append(links.get("google", ""))
        out.append(links.get("trip", ""))
        w.writerow(out)
    return buf.getvalue()


def to_markdown(payload: dict[str, Any], limit: int = 30) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    lines: list[str] = []
    params = meta["params"]
    title = (
        f"# {origin_city(meta.get('origin'))}出发 · {params['depart_from']} ~ {params['depart_to']} 出发"
        f"、{params['return_from']} ~ {params['return_to']} 返程 · 最便宜目的地"
    )
    lines.append(title)
    lines.append("")
    basis = {"round_trip": "往返", "one_way": "单程", "mixed": "混合"}.get(
        str(meta.get("price_basis")), str(meta.get("price_basis") or "")
    )
    live_txt = "实时报价" if meta["live"] else "非真实票价"
    lines.append(f"- 数据源：**{meta['provider_name']}**（{live_txt} · {basis}）")
    lines.append(f"- 生成时间：{meta['generated_at']} · 耗时 {meta['elapsed_ms']} ms")
    if summary["count"]:
        cheapest = summary["cheapest"]
        lines.append(
            f"- 共 {summary['count']} 个目的地，中位价 {summary['median']:.0f} HKD，"
            f"最低 **{cheapest['price']:.0f} HKD → {cheapest['city']} ({cheapest['code']})**"
        )
    lines.append("")
    lines.append("| # | 目的地 | 价格 (HKD) | 出发 → 返程 | 晚数 | 航司 | 转机 | 航程 | 性价比 | 标签 |")
    lines.append("|---|--------|-----------:|-------------|-----:|------|-----:|-----:|-------:|------|")
    for i, row in enumerate(payload["results"][:limit], 1):
        lines.append(
            f"| {i} | {row['city']} ({row['code']}) | {row['price']:.0f} "
            f"| {row['depart']} → {row['return']} | {row['nights']} | {row['airline'] or '—'} "
            f"| {'直飞' if row['stops'] == 0 else row['stops']} | {row['duration_label']} "
            f"| {row['deal_score']} | {' / '.join(row['tags'][:3])} |"
        )
    if not meta["live"]:
        lines.append("")
        lines.append("> ⚠️ 当前为演示数据（按距离/季节/航司仿真的报价），非真实票价。")
    if meta.get("warnings"):
        lines.append("")
        for warning in meta["warnings"]:
            lines.append(f"> {warning}")
    return "\n".join(lines) + "\n"


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Console table
# --------------------------------------------------------------------------- #


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(text))


def _pad(text: Any, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(0, width - _width(text))
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def to_console(payload: dict[str, Any], limit: int = 20) -> str:
    meta = payload["meta"]
    rows = payload["results"][:limit]
    head = ["#", "目的地", "机场", "价格", "出发", "返程", "晚", "航司", "转机", "性价比"]
    body: list[list[Any]] = []
    for i, r in enumerate(rows, 1):
        body.append([
            i,
            r["city"],
            r["code"],
            f"{r['price']:.0f}",
            r["depart"][5:],
            r["return"][5:],
            r["nights"],
            (r["airline"] or "—")[:6],
            "直飞" if r["stops"] == 0 else str(r["stops"]),
            r["deal_score"],
        ])
    widths = [
        max(_width(h), *(_width(row[i]) for row in body)) if body else _width(h)
        for i, h in enumerate(head)
    ]
    aligns = ["right", "left", "left", "right", "left", "left", "right", "left", "right", "right"]

    def line(cells: list[Any], sep: str = " │ ") -> str:
        return "│ " + sep.join(_pad(c, w, a) for c, w, a in zip(cells, widths, aligns)) + " │"

    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    mid = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bottom = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    out = [top, line(head), mid]
    out.extend(line(r) for r in body)
    out.append(bottom)

    summary = payload["summary"]
    header = (
        f"{meta['origin']} → 世界  ·  {meta['params']['depart_from']}~{meta['params']['depart_to']} 出发"
        f"  ·  数据源 {meta['provider_name']}"
        f"{'(实时)' if meta['live'] else '(演示)'}"
    )
    if summary["count"]:
        header += (
            f"  ·  最低 {summary['cheapest']['price']:.0f} HKD"
            f" → {summary['cheapest']['city']}"
        )
    out.insert(0, header)
    out.insert(1, "")
    if not meta["live"]:
        out.append("")
        out.append("⚠️  演示数据，非真实票价；配置 SerpApi key 后自动切换为实时报价。")
    for warning in meta.get("warnings") or []:
        out.append(f"⚠️  {warning}")
    return "\n".join(out)
