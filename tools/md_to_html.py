"""Turn a project markdown file into a standalone HTML page.

Beginners on Windows have no default app for .md, so the guides ship as .html
too: double-click opens them in the browser.

    python tools/md_to_html.py 部署到手机.md 部署到手机.html
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 20px 80px;
  background: #f4f7fb; color: #16202e;
  font: 15px/1.75 system-ui, -apple-system, "Segoe UI", "PingFang HK", "Microsoft JhengHei", sans-serif;
}
main { max-width: 780px; margin: 0 auto; background: #fff; border: 1px solid #e2e8f2;
  border-radius: 16px; padding: 34px 40px; box-shadow: 0 18px 50px -34px rgba(22,32,46,.5); }
h1 { font-size: 26px; margin: 0 0 6px; }
h2 { font-size: 19px; margin: 34px 0 10px; padding-top: 14px; border-top: 1px solid #eef2f8; }
h2:first-of-type { border-top: 0; padding-top: 0; }
h3 { font-size: 16px; margin: 22px 0 8px; }
p { margin: 10px 0; }
a { color: #0d9488; }
strong { color: #0f172a; }
code { background: #f2f5fa; border-radius: 5px; padding: 2px 6px; font-size: 13px;
  font-family: ui-monospace, Consolas, monospace; }
pre { background: #0f172a; color: #e8eefb; padding: 14px 16px; border-radius: 10px; overflow-x: auto; }
pre code { background: none; color: inherit; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14px; }
th, td { border: 1px solid #e2e8f2; padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #f7f9fc; font-weight: 650; }
tr:nth-child(even) td { background: #fbfcfe; }
ul, ol { margin: 10px 0; padding-left: 24px; }
li { margin: 5px 0; }
blockquote { margin: 14px 0; padding: 10px 14px; background: #fff8ec; border-left: 3px solid #d9a441;
  border-radius: 0 8px 8px 0; color: #6b5323; }
blockquote p { margin: 4px 0; }
hr { border: 0; border-top: 1px solid #eef2f8; margin: 26px 0; }
footer { max-width: 780px; margin: 18px auto 0; color: #8b99ad; font-size: 12px; text-align: center; }
@media (max-width: 640px) { body { padding: 16px 10px 40px; } main { padding: 22px 18px; border-radius: 12px; } }
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        out,
    )
    # <https://...> survives escaping as &lt;https://...&gt;
    out = re.sub(
        r"&lt;((?:https?://)[^&<>\s]+)&gt;",
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        out,
    )
    return out


def convert(markdown: str) -> str:
    lines = markdown.splitlines()
    body: list[str] = []
    i = 0
    list_tag: str | None = None

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            body.append(f"</{list_tag}>")
            list_tag = None

    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith("```"):
            close_list()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            body.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
            continue

        if not line.strip():
            close_list()
            i += 1
            continue

        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close_list()
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            body.append("</tbody></table>")
            continue

        if line.strip() in ("---", "***"):
            close_list()
            body.append("<hr>")
            i += 1
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            body.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if line.startswith(">"):
            close_list()
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip(">").strip())
                i += 1
            body.append("<blockquote>" + "".join(f"<p>{inline(q)}</p>" for q in quote if q) + "</blockquote>")
            continue

        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if list_tag != "ul":
                close_list()
                body.append("<ul>")
                list_tag = "ul"
            body.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if list_tag != "ol":
                close_list()
                body.append("<ol>")
                list_tag = "ol"
            body.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        close_list()
        body.append(f"<p>{inline(line)}</p>")
        i += 1

    close_list()
    return "\n".join(body)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法：python tools/md_to_html.py 输入.md [输出.html]")
        return 2
    src = Path(argv[1])
    dst = Path(argv[2]) if len(argv) > 2 else src.with_suffix(".html")
    markdown = src.read_text(encoding="utf-8")
    title = next((l.lstrip("# ").strip() for l in markdown.splitlines() if l.startswith("# ")), src.stem)
    page = f"""<!doctype html>
<html lang="zh-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
<main>
{convert(markdown)}
</main>
<footer>本页由 {src.name} 自动生成 · 用浏览器打开即可</footer>
</body>
</html>
"""
    dst.write_text(page, encoding="utf-8")
    print(f"✓ 已生成 {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
