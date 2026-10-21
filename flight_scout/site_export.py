"""Build a static site snapshot for GitHub Pages.

The page cannot call SerpApi directly (the key would leak), so a scheduled job
fetches the prices here, scores them, and writes one JSON file. The browser then
only filters/sorts that snapshot — no backend needed.

    python flightscout.py export-site --out site
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import __version__, data
from .config import WEB_DIR, Config
from .core import SearchParams, annotate, apply_filters
from .service import fetch_offers

SNAPSHOT_VERSION = 1


def _origin_meta(code: str) -> dict[str, str]:
    ap = data.ORIGINS.get(code) or data.ORIGIN
    return {
        "code": ap.code,
        "city": ap.city_zh,
        "label": data.ORIGIN_LABELS.get(ap.code, ap.city_zh),
    }


def build_snapshot(
    cfg: Config,
    origins: Iterable[str] = ("HKG",),
    provider: str = "auto",
    params_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One fetch per origin; every offer is kept and fully annotated."""
    origin_codes = [o.upper() for o in origins]
    offers: list[dict[str, Any]] = []
    per_origin: dict[str, Any] = {}
    warnings: list[str] = []
    window: dict[str, Any] = {}

    for code in origin_codes:
        raw: dict[str, Any] = {"origin": code, "provider": provider, "limit": 300}
        if params_override:
            raw.update(params_override)
        params = SearchParams.from_dict(raw)
        fetched, meta = fetch_offers(params, cfg)
        annotate(fetched)
        if not window:
            window = params.to_dict()
        offers.extend(o.to_dict() for o in fetched)
        per_origin[code] = {
            "live": meta["live"],
            "provider": meta["provider"],
            "provider_name": meta["provider_name"],
            "price_basis": meta["price_basis"],
            "count": len(fetched),
            "warnings": meta.get("warnings") or [],
        }
        warnings.extend(meta.get("warnings") or [])

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "app_version": __version__,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "currency": cfg.default_currency,
        "origin": origin_codes[0] if origin_codes else "HKG",
        "origins": [_origin_meta(c) for c in origin_codes],
        "regions": data.REGIONS,
        "destination_count": len(data.DESTINATIONS),
        "per_origin": per_origin,
        "window": window,
        "warnings": warnings,
        "offers": offers,
    }


def export_site(
    out_dir: str | Path,
    cfg: Config,
    origins: Iterable[str] = ("HKG",),
    provider: str = "auto",
    params_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot(cfg, origins, provider, params_override)

    # Static assets, copied verbatim.
    for name in ("index.html", "style.css", "app.js"):
        src = WEB_DIR / name
        if not src.exists():
            raise FileNotFoundError(f"缺少前端文件：{src}")
        shutil.copy2(src, out / name)

    data_dir = out / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    # GitHub Pages runs Jekyll by default; this switches it off.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    return {
        "out": str(out),
        "origins": list(snapshot["origins"]),
        "offers": len(snapshot["offers"]),
        "generated_at": snapshot["generated_at"],
        "live": all(m["live"] for m in snapshot["per_origin"].values()),
    }


def default_offers_for_origin(snapshot: dict[str, Any], origin: str) -> list[dict[str, Any]]:
    """Helper used by tests and the static fallback."""
    return [o for o in snapshot["offers"] if o.get("origin") == origin.upper()]


__all__ = [
    "SNAPSHOT_VERSION",
    "build_snapshot",
    "export_site",
    "default_offers_for_origin",
    "apply_filters",
]
