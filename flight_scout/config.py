"""Runtime configuration.

Priority: explicit ``--config`` file > environment variables > defaults.
Nothing secret is ever written to disk by the app.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class Config:
    serpapi_key: str = ""
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    amadeus_env: str = "test"          # test | production
    travelpayouts_token: str = ""
    default_currency: str = "HKD"
    host: str = "127.0.0.1"
    port: int = 8777
    source: dict[str, str] = field(default_factory=dict)

    # -- capability probes ------------------------------------------------- #
    @property
    def has_serpapi(self) -> bool:
        return bool(self.serpapi_key)

    @property
    def has_amadeus(self) -> bool:
        return bool(self.amadeus_client_id and self.amadeus_client_secret)

    @property
    def has_travelpayouts(self) -> bool:
        return bool(self.travelpayouts_token)

    @property
    def amadeus_base(self) -> str:
        return (
            "https://api.amadeus.com"
            if self.amadeus_env.lower().startswith("prod")
            else "https://test.api.amadeus.com"
        )

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "serpapi",
                "name": "SerpApi · Google Flights",
                "ready": self.has_serpapi,
                "live": True,
                "hint": "免费 250 次/月，直接返回「从香港出发去哪最便宜」的真实往返价",
                "signup": "https://serpapi.com/users/sign_up",
            },
            {
                "id": "travelpayouts",
                "name": "Travelpayouts / Aviasales",
                "ready": self.has_travelpayouts,
                "live": True,
                "hint": "免费 token，覆盖廉价航空特价，报价多为单程",
                "signup": "https://www.travelpayouts.com/",
            },
            {
                "id": "amadeus",
                "name": "Amadeus（企业版）",
                "ready": self.has_amadeus,
                "live": True,
                "hint": "自助免费版已于 2026-07-17 下线，现仅企业合同可用；一般用户请用 SerpApi",
                "signup": "https://developers.amadeus.com/",
            },
            {
                "id": "demo",
                "name": "演示数据（无需 key）",
                "ready": True,
                "live": False,
                "hint": "按距离/季节/航司类型生成的仿真报价，用于体验界面与排序逻辑",
                "signup": "",
            },
        ]


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    file_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if file_path.exists():
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"配置文件不是合法 JSON: {file_path} ({exc})") from exc

    cfg.serpapi_key = str(
        raw.get("serpapi_key") or os.environ.get("SERPAPI_KEY", "")
    ).strip()
    cfg.amadeus_client_id = str(
        raw.get("amadeus_client_id") or os.environ.get("AMADEUS_CLIENT_ID", "")
    ).strip()
    cfg.amadeus_client_secret = str(
        raw.get("amadeus_client_secret") or os.environ.get("AMADEUS_CLIENT_SECRET", "")
    ).strip()
    cfg.amadeus_env = str(
        raw.get("amadeus_env") or os.environ.get("AMADEUS_ENV", "test")
    ).strip()
    cfg.travelpayouts_token = str(
        raw.get("travelpayouts_token") or os.environ.get("TRAVELPAYOUTS_TOKEN", "")
    ).strip()
    cfg.default_currency = str(raw.get("currency") or "HKD")
    cfg.host = str(raw.get("host") or "127.0.0.1")
    cfg.port = int(raw.get("port") or 8777)
    return cfg


def save_config(values: dict[str, str], path: str | Path | None = None) -> Path:
    """Merge *values* into config.json (creating it if needed).

    Used by the in-page setup dialog so nobody has to edit files or set
    environment variables by hand.
    """
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    current: dict[str, Any] = {}
    if target.exists():
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current.update({k: v for k, v in values.items() if v is not None})
    target.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:  # keep the file private on POSIX; Windows inherits the folder ACL
        target.chmod(0o600)
    except OSError:
        pass
    return target


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "•" * len(value)
    return f"{value[:keep]}{'•' * 8}{value[-keep:]}"
