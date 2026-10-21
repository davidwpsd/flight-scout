"""Core domain logic: distances, search parameters, offers, scoring, deep links."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence
from urllib.parse import quote

from . import data
from .data import Airport

# --------------------------------------------------------------------------- #
# Geography
# --------------------------------------------------------------------------- #

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def distance_between(origin: Airport, ap: Airport) -> float:
    """Great-circle distance between a departure airport and a destination."""
    return round(haversine_km(origin.lat, origin.lon, ap.lat, ap.lon))


def distance_from_hkg(ap: Airport) -> float:
    """Kept for callers that assume the default origin."""
    return distance_between(data.ORIGINS.get("HKG", data.ORIGIN), ap)


def resolve_origin(code: str) -> Airport:
    ap = data.ORIGINS.get((code or "HKG").upper())
    if ap is None:
        supported = "、".join(f"{c} {a.city_zh}" for c, a in data.ORIGINS.items())
        raise ParamError(f"暂不支持从 {code} 出发。可选：{supported}")
    return ap


def estimate_duration_min(km: float) -> int:
    """Block time estimate: ~830 km/h plus 45 min taxi/climb/descent."""
    return int(round(km / 830.0 * 60 + 45))


def fmt_duration(minutes: int | None) -> str:
    if not minutes:
        return "—"
    return f"{minutes // 60}h{minutes % 60:02d}"


# --------------------------------------------------------------------------- #
# Search parameters
# --------------------------------------------------------------------------- #


class ParamError(ValueError):
    """Raised for user-supplied parameters that cannot form a valid search."""


def _parse_date(value: Any, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ParamError(f"{name} 日期格式应为 YYYY-MM-DD，收到 {value!r}") from exc


def _as_bool(value: Any) -> bool:
    """Accept JSON booleans and the string forms used by query strings."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def default_windows(today: date | None = None) -> dict[str, date]:
    """The upcoming Christmas/New-Year window, relative to *today*.

    Departure 18–24 Dec (the great exodus), return 26 Dec–4 Jan.
    After 26 Dec the next season is a year away.
    """
    today = today or date.today()
    year = today.year if today <= date(today.year, 12, 26) else today.year + 1
    return {
        "depart_from": date(year, 12, 18),
        "depart_to": date(year, 12, 24),
        "return_from": date(year, 12, 26),
        "return_to": date(year + 1, 1, 4),
    }


DEFAULT_WINDOWS = default_windows()


@dataclass
class SearchParams:
    origin: str = "HKG"
    depart_from: date = DEFAULT_WINDOWS["depart_from"]
    depart_to: date = DEFAULT_WINDOWS["depart_to"]
    return_from: date = DEFAULT_WINDOWS["return_from"]
    return_to: date = DEFAULT_WINDOWS["return_to"]
    nights_min: int = 4
    nights_max: int = 12
    max_price: float | None = None
    regions: list[str] = field(default_factory=list)
    direct_only: bool = False
    max_stops: int | None = None
    provider: str = "auto"
    sort: str = "price"
    limit: int = 200
    verify: int = 0

    # -- construction ------------------------------------------------------ #
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SearchParams":
        p = cls()
        p.origin = str(raw.get("origin") or "HKG").upper().strip()
        if "depart_from" in raw:
            p.depart_from = _parse_date(raw["depart_from"], "depart_from")
        if "depart_to" in raw:
            p.depart_to = _parse_date(raw["depart_to"], "depart_to")
        if "return_from" in raw:
            p.return_from = _parse_date(raw["return_from"], "return_from")
        if "return_to" in raw:
            p.return_to = _parse_date(raw["return_to"], "return_to")
        if raw.get("nights_min") is not None:
            p.nights_min = int(raw["nights_min"])
        if raw.get("nights_max") is not None:
            p.nights_max = int(raw["nights_max"])
        if raw.get("max_price") not in (None, "", 0):
            p.max_price = float(raw["max_price"])
        regions = raw.get("regions") or []
        if isinstance(regions, str):
            regions = [r for r in regions.split(",") if r.strip()]
        p.regions = [str(r) for r in regions]
        p.direct_only = _as_bool(raw.get("direct_only", False))
        if raw.get("max_stops") not in (None, ""):
            p.max_stops = int(raw["max_stops"])
        p.provider = str(raw.get("provider") or "auto").lower()
        p.sort = str(raw.get("sort") or "price")
        if raw.get("limit"):
            p.limit = max(1, min(500, int(raw["limit"])))
        if raw.get("verify") is not None:
            p.verify = max(0, min(25, int(raw["verify"])))
        p.validate()
        return p

    def validate(self) -> None:
        if self.origin not in data.ORIGINS:
            resolve_origin(self.origin)  # raises with the supported list
        if self.depart_from > self.depart_to:
            raise ParamError("出发日期区间起始晚于结束")
        if self.return_from > self.return_to:
            raise ParamError("返程日期区间起始晚于结束")
        if self.nights_min < 1 or self.nights_max < 1:
            raise ParamError("停留晚数须为正值")
        if self.nights_max < self.nights_min:
            raise ParamError("最多晚数不能小于最少晚数")
        if (self.return_to - self.depart_from).days < self.nights_min:
            raise ParamError("返程窗口与出发窗口无交集，请放宽日期或减少停留晚数")
        if (self.depart_to - self.depart_from).days > 60:
            raise ParamError("出发窗口过长（上限 60 天），请缩小区间")

    # -- derived ----------------------------------------------------------- #
    @property
    def depart_dates(self) -> list[date]:
        n = (self.depart_to - self.depart_from).days
        return [self.depart_from + timedelta(days=i) for i in range(n + 1)]

    def feasible_pairs(self, max_pairs: int = 40) -> list[tuple[date, date]]:
        """(depart, return) combinations that satisfy both windows and nights."""
        pairs: list[tuple[date, date]] = []
        for d in self.depart_dates:
            for nights in range(self.nights_min, self.nights_max + 1):
                r = d + timedelta(days=nights)
                if self.return_from <= r <= self.return_to:
                    pairs.append((d, r))
        if not pairs:
            return []
        if len(pairs) <= max_pairs:
            return pairs
        # Deterministic even sampling keeps results stable between requests.
        step = len(pairs) / max_pairs
        return [pairs[min(int(i * step), len(pairs) - 1)] for i in range(max_pairs)]

    def sampled_depart_dates(self, n: int = 6) -> list[date]:
        ds = self.depart_dates
        if len(ds) <= n:
            return ds
        step = (len(ds) - 1) / (n - 1)
        return [ds[min(int(round(i * step)), len(ds) - 1)] for i in range(n)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "depart_from": self.depart_from.isoformat(),
            "depart_to": self.depart_to.isoformat(),
            "return_from": self.return_from.isoformat(),
            "return_to": self.return_to.isoformat(),
            "nights_min": self.nights_min,
            "nights_max": self.nights_max,
            "max_price": self.max_price,
            "regions": self.regions,
            "direct_only": self.direct_only,
            "provider": self.provider,
            "sort": self.sort,
        }


# --------------------------------------------------------------------------- #
# Offers
# --------------------------------------------------------------------------- #


@dataclass
class Offer:
    code: str
    city: str
    city_en: str
    country: str
    region: str
    flag: str
    lat: float
    lon: float
    price: float
    currency: str
    depart: date
    ret: date
    airline_code: str
    airline: str
    stops: int
    duration_min: int
    cc: str = ""
    source: str = "unknown"
    origin: str = "HKG"
    distance_km: float = 0.0
    price_per_1000km: float = 0.0
    deal_score: int = 0
    saving_pct: float = 0.0
    tags: list[str] = field(default_factory=list)
    booking_links: dict[str, str] = field(default_factory=dict)

    @property
    def nights(self) -> int:
        return (self.ret - self.depart).days

    @classmethod
    def from_airport(cls, ap: Airport, origin: str = "HKG", **kw: Any) -> "Offer":
        dep_ap = data.ORIGINS.get(origin, data.ORIGIN)
        km = distance_between(dep_ap, ap)
        return cls(
            code=ap.code,
            city=ap.city_zh,
            city_en=ap.city_en,
            country=ap.country_zh,
            region=ap.region,
            flag=ap.flag,
            cc=ap.cc,
            lat=ap.lat,
            lon=ap.lon,
            origin=dep_ap.code,
            distance_km=km,
            duration_min=kw.pop("duration_min", None) or estimate_duration_min(km),
            **kw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "origin": self.origin,
            "city": self.city,
            "city_en": self.city_en,
            "country": self.country,
            "region": self.region,
            "flag": self.flag,
            "cc": self.cc or self.code[:2],
            "lat": self.lat,
            "lon": self.lon,
            "price": round(self.price, 2),
            "currency": self.currency,
            "depart": self.depart.isoformat(),
            "return": self.ret.isoformat(),
            "nights": self.nights,
            "airline_code": self.airline_code,
            "airline": self.airline,
            "stops": self.stops,
            "duration_min": self.duration_min,
            "duration_label": fmt_duration(self.duration_min),
            "distance_km": round(self.distance_km),
            "price_per_1000km": round(self.price_per_1000km, 1),
            "deal_score": self.deal_score,
            "saving_pct": round(self.saving_pct, 1),
            "tags": self.tags,
            "source": self.source,
            "booking_links": self.booking_links,
        }


# --------------------------------------------------------------------------- #
# Booking deep links (always work, even without any API key)
# --------------------------------------------------------------------------- #


def booking_links(origin: str, code: str, depart: date, ret: date) -> dict[str, str]:
    origin = (origin or "HKG").upper()
    d, r = depart.isoformat(), ret.isoformat()
    ymd_d, ymd_r = depart.strftime("%y%m%d"), ret.strftime("%y%m%d")
    q = quote(f"Flights from {origin} to {code} on {d} returning {r}")
    return {
        "google": f"https://www.google.com/travel/flights?q={q}&curr=HKD&hl=zh-HK",
        "skyscanner": (
            f"https://www.skyscanner.com.hk/transport/flights/{origin.lower()}/{code.lower()}/"
            f"{ymd_d}/{ymd_r}/?adults=1&currency=HKD&locale=zh-HK"
        ),
        "trip": (
            f"https://hk.trip.com/flights/showfarefirst?dcity={origin.lower()}&acity={code.lower()}"
            f"&ddate={d}&rdate={r}&triptype=rt&curr=HKD"
        ),
    }


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _percentile_ranks(values: Sequence[float]) -> list[float]:
    """Rank 0 (lowest value) .. 100 (highest), ties averaged."""
    n = len(values)
    if n <= 1:
        return [0.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank / (n - 1) * 100.0
        i = j + 1
    return ranks


def annotate(offers: list[Offer]) -> list[Offer]:
    """Fill price-per-km, deal score, savings and tags in place."""
    if not offers:
        return offers

    for o in offers:
        if not o.distance_km:
            o.distance_km = distance_between(
                data.ORIGINS.get(o.origin, data.ORIGIN),
                data.BY_CODE.get(o.code)
                or Airport(o.code, o.city, o.city_en, o.country, o.country, o.region, o.lat, o.lon),
            )
        o.price_per_1000km = o.price / max(o.distance_km, 300.0) * 1000.0

    price_rank = _percentile_ranks([o.price for o in offers])
    value_rank = _percentile_ranks([o.price_per_1000km for o in offers])

    by_region: dict[str, list[float]] = {}
    for o in offers:
        by_region.setdefault(o.region, []).append(o.price)
    region_median = {r: statistics.median(v) for r, v in by_region.items()}

    cheapest = min(o.price for o in offers)
    for i, o in enumerate(offers):
        direct_bonus = 100.0 if o.stops == 0 else (55.0 if o.stops == 1 else 15.0)
        # Absolute price dominates: the question is "where is cheapest", not
        # "where is the best price per kilometre".
        o.deal_score = int(round(
            0.72 * (100.0 - price_rank[i])
            + 0.13 * (100.0 - value_rank[i])
            + 0.15 * direct_bonus
        ))
        med = region_median[o.region]
        o.saving_pct = (med - o.price) / med * 100.0 if med else 0.0

        tags: list[str] = []
        if o.stops == 0:
            tags.append("直飞")
        elif o.stops == 1:
            tags.append("1次转机")
        else:
            tags.append(f"{o.stops}次转机")
        if o.price <= cheapest * 1.02:
            tags.append("全场最低")
        if o.deal_score >= 78:
            tags.append("高性价比")
        if o.distance_km < 1500:
            tags.append("短途")
        note = data.SEASON_NOTE.get(o.region)
        if note:
            tags.append(note)
        o.tags = tags
        o.booking_links = booking_links(o.origin, o.code, o.depart, o.ret)

    return offers


SORT_KEYS = {
    "deal": lambda o: (-o.deal_score, o.price),
    "price": lambda o: (o.price, -o.deal_score),
    "value": lambda o: (o.price_per_1000km, o.price),
    "distance": lambda o: (o.distance_km, o.price),
    "nights": lambda o: (-o.nights, o.price),
    "date": lambda o: (o.depart, o.price),
}


def sort_offers(offers: list[Offer], mode: str) -> list[Offer]:
    return sorted(offers, key=SORT_KEYS.get(mode, SORT_KEYS["deal"]))


def summarize(offers: list[Offer], params: SearchParams) -> dict[str, Any]:
    if not offers:
        return {
            "count": 0,
            "cheapest": None,
            "median": None,
            "best_value": None,
            "best_deal": None,
            "by_region": [],
        }
    prices = [o.price for o in offers]
    by_region: dict[str, list[Offer]] = {}
    for o in offers:
        by_region.setdefault(o.region, []).append(o)

    region_rows = []
    for region in data.REGIONS:
        group = by_region.get(region)
        if not group:
            continue
        best = min(group, key=lambda o: o.price)
        region_rows.append({
            "region": region,
            "count": len(group),
            "min": round(min(o.price for o in group), 2),
            "median": round(statistics.median(o.price for o in group), 2),
            "best_code": best.code,
            "best_city": best.city,
        })

    return {
        "count": len(offers),
        "median": round(statistics.median(prices), 2),
        "cheapest": min(offers, key=lambda o: o.price).to_dict(),
        "best_value": min(offers, key=lambda o: o.price_per_1000km).to_dict(),
        "best_deal": max(offers, key=lambda o: (o.deal_score, -o.price)).to_dict(),
        "by_region": region_rows,
    }


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #


def apply_filters(offers: Iterable[Offer], params: SearchParams) -> list[Offer]:
    out = []
    for o in offers:
        if params.regions and o.region not in params.regions:
            continue
        if params.direct_only and o.stops != 0:
            continue
        if params.max_stops is not None and o.stops > params.max_stops:
            continue
        if params.max_price is not None and o.price > params.max_price:
            continue
        out.append(o)
    return out
