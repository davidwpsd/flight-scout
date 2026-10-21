"""Tiny stdlib HTTP server: JSON API + static dashboard.

Deliberately dependency-free so the tool runs on a bare Python 3.10+ install.
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__, data
from .config import DEFAULT_CONFIG_PATH, WEB_DIR, Config, mask, save_config
from .console_setup import setup_console
from .core import DEFAULT_WINDOWS, ParamError, SearchParams, default_windows
from .providers import (
    ProviderError,
    build_provider,
    validate_amadeus,
    validate_serpapi,
    validate_travelpayouts,
)
from .report import to_csv, to_markdown
from .service import build_payload, fetch_offers

CACHE_TTL = 600  # seconds
# key -> (stored_at, offers, meta); filters/sort are applied per request
_CACHE: dict[str, tuple[float, Any, Any]] = {}


def _meta_payload(cfg: Config) -> dict[str, Any]:
    windows = default_windows()
    return {
        "version": __version__,
        "origin": "HKG",
        "origin_name": data.ORIGINS["HKG"].city_zh,
        "origins": [
            {
                "code": code,
                "city": ap.city_zh,
                "label": data.ORIGIN_LABELS.get(code, ap.city_zh),
            }
            for code, ap in data.ORIGINS.items()
        ],
        "currency": cfg.default_currency,
        "destinations": len(data.DESTINATIONS),
        "regions": data.REGIONS,
        "region_counts": {
            r: sum(1 for a in data.DESTINATIONS if a.region == r) for r in data.REGIONS
        },
        "providers": cfg.describe(),
        "defaults": {
            "depart_from": windows["depart_from"].isoformat(),
            "depart_to": windows["depart_to"].isoformat(),
            "return_from": windows["return_from"].isoformat(),
            "return_to": windows["return_to"].isoformat(),
            "nights_min": 4,
            "nights_max": 12,
        },
        "presets": _presets(windows),
    }


def _presets(windows: dict[str, Any]) -> list[dict[str, Any]]:
    year = windows["depart_from"].year
    return [
        {
            "id": "xmas",
            "label": "圣诞主场",
            "desc": "12/20 出发，节后回",
            "params": {
                "depart_from": f"{year}-12-19",
                "depart_to": f"{year}-12-23",
                "return_from": f"{year}-12-26",
                "return_to": f"{year}-12-31",
                "nights_min": 4,
                "nights_max": 12,
            },
        },
        {
            "id": "newyear",
            "label": "跨年长线",
            "desc": "12/27 出发，1 月回",
            "params": {
                "depart_from": f"{year}-12-27",
                "depart_to": f"{year}-12-31",
                "return_from": f"{year + 1}-01-02",
                "return_to": f"{year + 1}-01-06",
                "nights_min": 5,
                "nights_max": 14,
            },
        },
        {
            "id": "shoulder",
            "label": "错峰捡漏",
            "desc": "节前一周出发",
            "params": {
                "depart_from": f"{year}-12-12",
                "depart_to": f"{year}-12-17",
                "return_from": f"{year}-12-19",
                "return_to": f"{year}-12-24",
                "nights_min": 4,
                "nights_max": 10,
            },
        },
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = f"FlightScout/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        if self.path.startswith("/api/"):
            print(f"  · {self.command} {self.path.split('?')[0]}")

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    # -- routing ----------------------------------------------------------- #
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/api/meta":
                return self._json(_meta_payload(self.server.cfg))
            if path == "/api/config":
                return self._json(self._config_payload())
            if path == "/api/health":
                return self._json({"ok": True, "version": __version__})
            if path == "/api/search":
                params = {k: v[0] for k, v in query.items() if v}
                return self._search(params)
            if path == "/api/export.csv":
                params = {k: v[0] for k, v in query.items() if v}
                payload = self._run_cached(params)
                body = ("\ufeff" + to_csv(payload)).encode("utf-8")
                return self._send(
                    HTTPStatus.OK, body, "text/csv; charset=utf-8",
                )
            if path == "/api/export.md":
                params = {k: v[0] for k, v in query.items() if v}
                payload = self._run_cached(params)
                return self._send(HTTPStatus.OK, to_markdown(payload).encode("utf-8"), "text/markdown; charset=utf-8")
            if path in ("/", "/index.html"):
                return self._static("index.html")
            return self._static(path.lstrip("/"))
        except (ParamError, ProviderError) as exc:
            self._error(str(exc), 400)
        except BrokenPipeError:
            pass
        except Exception:  # noqa: BLE001 - never kill the server thread
            traceback.print_exc()
            self._error("服务器内部错误，详见控制台日志", 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            try:
                return self._save_config()
            except ParamError as exc:
                return self._error(str(exc), 400)
            except ProviderError as exc:
                return self._error(str(exc), 400)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                return self._error("保存失败，请查看控制台日志", 500)
        if parsed.path != "/api/search":
            return self._error("未找到该接口", 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            params = json.loads(raw or b"{}")
            if not isinstance(params, dict):
                raise ParamError("请求体必须是 JSON 对象")
            self._search(params)
        except json.JSONDecodeError:
            self._error("请求体不是合法 JSON")
        except ParamError as exc:
            self._error(str(exc), 400)
        except ProviderError as exc:
            self._error(str(exc), 502)
        except BrokenPipeError:
            pass
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._error("服务器内部错误，详见控制台日志", 500)

    # -- helpers ----------------------------------------------------------- #
    def _search(self, raw: dict[str, Any]) -> None:
        payload = self._run_cached(raw)
        self._json(payload)

    # ---- in-page setup ---------------------------------------------------- #
    def _is_local(self) -> bool:
        """Only the computer that runs the server may change its settings."""
        addr = (self.client_address or ("",))[0]
        return addr in ("::1", "localhost") or addr.startswith("127.")

    def _config_payload(self) -> dict[str, Any]:
        cfg = self.server.cfg
        provider = build_provider("auto", cfg)
        return {
            "serpapi": {"configured": cfg.has_serpapi, "key": mask(cfg.serpapi_key)},
            "amadeus": {
                "configured": cfg.has_amadeus,
                "client_id": mask(cfg.amadeus_client_id),
                "env": cfg.amadeus_env,
            },
            "travelpayouts": {"configured": cfg.has_travelpayouts},
            "active_provider": provider.info.id,
            "live": provider.info.live,
            "local": self._is_local(),
            "config_file": str(DEFAULT_CONFIG_PATH),
        }

    def _save_config(self) -> None:
        if not self._is_local():
            return self._error("只有运行本工具的那台电脑才能修改设置", 403)

        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            if origin not in (f"http://{host}", f"https://{host}"):
                return self._error("只接受来自本页面的保存请求", 403)

        length = int(self.headers.get("Content-Length") or 0)
        raw: dict[str, Any] = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(raw, dict):
            raise ParamError("请求体必须是 JSON 对象")

        serp = str(raw.get("serpapi_key") or "").strip()
        cid = str(raw.get("amadeus_client_id") or "").strip()
        secret = str(raw.get("amadeus_client_secret") or "").strip()
        env = str(raw.get("amadeus_env") or "test").strip().lower()
        token = str(raw.get("travelpayouts_token") or "").strip()
        if env not in ("test", "production"):
            raise ParamError("环境只能是 test 或 production")
        if bool(cid) != bool(secret):
            raise ParamError("API Key 和 API Secret 需要同时填写")
        if not any((serp, cid, secret, token)):
            raise ParamError("没有填写任何内容")

        # Verify before saving so nobody ends up with a silently broken setup.
        if serp:
            try:
                validate_serpapi(serp)
            except ProviderError as exc:
                traceback.print_exc()
                raise ProviderError(
                    "SerpApi 拒绝了这个 key。请到 serpapi.com 的 Dashboard 重新复制，"
                    "注意不要带上空格或引号。"
                ) from exc
        if cid and secret:
            try:
                validate_amadeus(cid, secret, env)
            except ProviderError as exc:
                traceback.print_exc()
                raise ProviderError(
                    "Amadeus 拒绝了这组密钥。请确认 Key 与 Secret 都完整复制（前后没有空格），"
                    "并且「环境」选的是你账号对应的那个。"
                ) from exc
        if token:
            try:
                validate_travelpayouts(token)
            except ProviderError as exc:
                traceback.print_exc()
                raise ProviderError(
                    "Travelpayouts token 验证失败，请检查是否复制完整。"
                ) from exc

        # Empty fields mean "leave what is already saved alone".
        updates: dict[str, str] = {}
        if serp:
            updates["serpapi_key"] = serp
        if cid and secret:
            updates.update({
                "amadeus_client_id": cid,
                "amadeus_client_secret": secret,
                "amadeus_env": env,
            })
        if token:
            updates["travelpayouts_token"] = token
        save_config(updates)

        cfg = self.server.cfg
        cfg.serpapi_key = updates.get("serpapi_key", cfg.serpapi_key)
        cfg.amadeus_client_id = updates.get("amadeus_client_id", cfg.amadeus_client_id)
        cfg.amadeus_client_secret = updates.get("amadeus_client_secret", cfg.amadeus_client_secret)
        cfg.amadeus_env = updates.get("amadeus_env", cfg.amadeus_env)
        cfg.travelpayouts_token = updates.get("travelpayouts_token", cfg.travelpayouts_token)
        _CACHE.clear()
        self._json({"ok": True, "config": self._config_payload()})

    def _fetch_key(self, params: SearchParams) -> str:
        """Only parameters that change the upstream query belong in the key.

        Region, budget and sort are applied locally, so poking at the dashboard
        never spends another API call.
        """
        return json.dumps({
            "origin": params.origin,
            "depart_from": params.depart_from.isoformat(),
            "depart_to": params.depart_to.isoformat(),
            "return_from": params.return_from.isoformat(),
            "return_to": params.return_to.isoformat(),
            "nights_min": params.nights_min,
            "nights_max": params.nights_max,
            "direct_only": params.direct_only,
            "provider": params.provider,
            "verify": params.verify,
            "limit": params.limit,
        }, sort_keys=True)

    def _run_cached(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = SearchParams.from_dict(raw)
        key = self._fetch_key(params)
        now = time.time()
        hit = _CACHE.get(key)
        fresh = bool(hit and now - hit[0] < CACHE_TTL)

        if fresh:
            _, offers, meta = hit  # type: ignore[misc]
        else:
            offers, meta = fetch_offers(params, self.server.cfg)
            _CACHE[key] = (now, offers, meta)  # type: ignore[assignment]
            if len(_CACHE) > 32:
                for stale in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:8]:
                    _CACHE.pop(stale, None)

        payload = build_payload(offers, params, meta)
        payload["meta"]["cached"] = fresh
        return payload

    def _static(self, relative: str) -> None:
        target = (WEB_DIR / relative).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._error("页面不存在", 404)
        ctype, _ = mimetypes.guess_type(str(target))
        self._send(HTTPStatus.OK, target.read_bytes(), f"{ctype or 'application/octet-stream'}; charset=utf-8")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two processes bind the same port, which makes
    # a restart silently keep serving the old code. Fail instead, so _pick_port
    # moves to the next free port.
    allow_reuse_address = os.name != "nt"

    def __init__(self, addr: tuple[str, int], cfg: Config):
        super().__init__(addr, Handler)
        self.cfg = cfg


def _pick_port(host: str, port: int) -> int:
    for candidate in range(port, port + 12):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise SystemExit(f"端口 {port}~{port + 11} 都被占用，请用 --port 指定其它端口")


def lan_addresses() -> list[str]:
    """Best-effort list of this machine's LAN IPv4 addresses."""
    found: list[str] = []

    def add(ip: str) -> None:
        if ip and not ip.startswith("127.") and ip not in found:
            found.append(ip)

    try:  # the address used for outbound traffic = the one colleagues can reach
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(str(info[4][0]))
    except OSError:
        pass
    return found


def _provider_label(cfg: Config) -> str:
    if cfg.has_serpapi:
        return "SerpApi · Google Flights"
    if cfg.has_travelpayouts:
        return "Travelpayouts"
    if cfg.has_amadeus:
        return "Amadeus"
    return "演示数据"


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8777, open_browser: bool = True) -> int:
    setup_console()
    port = _pick_port(host, port)
    httpd = Server((host, port), cfg)
    shared = host not in ("127.0.0.1", "localhost", "::1")
    local_url = f"http://127.0.0.1:{port}"

    print()
    print("  ✈  Flight Scout — 香港出发·圣诞机票雷达")
    print(f"  ➜  本机打开   {local_url}")
    if shared:
        for ip in lan_addresses():
            print(f"  ➜  同事访问   http://{ip}:{port}")
        print("  ➜  仅限同一 Wi-Fi / 局域网；设置只有本机可改")
    print(f"  ➜  数据源：{_provider_label(cfg)}   (Ctrl+C 退出)")
    print()
    if open_browser:
        try:
            threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()
        except Exception:  # noqa: BLE001 - a missing browser must not stop the server
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    from .config import load_config

    c = load_config()
    raise SystemExit(serve(c, host=c.host, port=c.port))
