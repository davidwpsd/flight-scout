"""Search orchestration: fetch once, then filter/score/rank locally.

Splitting "fetch" from "shape" matters for cost: region chips, budget and sort
order only change how the same offers are presented, so they must not trigger a
new API call. The server caches the fetch result and re-shapes it per request.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime
from typing import Any

from . import data
from .config import Config
from .core import Offer, SearchParams, annotate, apply_filters, sort_offers, summarize
from .providers import ProviderError, build_provider


def fetch_offers(params: SearchParams, cfg: Config) -> tuple[list[Offer], dict[str, Any]]:
    """Call the data source once and return raw offers plus describing metadata.

    Region / budget / sort are deliberately ignored here: they are applied later
    by ``build_payload``, so the caller can reuse this result.
    """
    started = time.perf_counter()
    provider = build_provider(params.provider, cfg)
    destinations = list(data.DESTINATIONS)

    warnings: list[str] = []
    try:
        offers = provider.search(params, destinations)
    except ProviderError as exc:
        if params.provider != "auto":
            raise
        warnings.append(f"实时数据源不可用，已回退到演示数据：{exc}")
        provider = build_provider("demo", cfg)
        offers = provider.search(params, destinations)

    # Never offer a flight to the city you are already departing from.
    offers = [o for o in offers if o.price > 0 and o.code != params.origin.upper()]
    offers.sort(key=lambda o: o.price)
    if params.limit:
        offers = offers[: params.limit * 2]

    if params.verify and provider.info.live:
        try:
            offers = provider.verify(offers[: params.verify], params) + offers[params.verify :]
        except ProviderError as exc:  # verification is best-effort
            warnings.append(f"报价复核失败，展示的是参考价：{exc}")

    meta = {
        "origin": params.origin,
        "provider": provider.info.id,
        "provider_name": provider.info.name,
        "live": provider.info.live,
        "note": provider.info.note,
        "price_basis": provider.info.price_basis,
        "currency": cfg.default_currency,
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fetch_ms": int((time.perf_counter() - started) * 1000),
        "destination_pool": len(destinations),
        "warnings": warnings,
    }
    return offers, meta


def build_payload(
    offers: list[Offer], params: SearchParams, meta: dict[str, Any]
) -> dict[str, Any]:
    """Apply the user's filters, re-score, sort and summarise cached offers."""
    started = time.perf_counter()
    working = [copy.copy(o) for o in offers]  # annotate() writes to each offer

    working = apply_filters(working, params)
    annotate(working)
    working = sort_offers(working, params.sort)[: params.limit]

    return {
        "meta": {
            **meta,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "params": params.to_dict(),
        },
        "summary": summarize(working, params),
        "results": [o.to_dict() for o in working],
    }


def run_search(params: SearchParams, cfg: Config) -> dict[str, Any]:
    """Fetch + shape in one go (used by the CLI)."""
    offers, meta = fetch_offers(params, cfg)
    return build_payload(offers, params, meta)


def providers_payload(cfg: Config) -> list[dict[str, Any]]:
    return cfg.describe()
