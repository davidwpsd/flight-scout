"""Pluggable flight data providers.

Three implementations share one tiny interface:

* ``DemoProvider``      – offline, deterministic, clearly labelled as demo
* ``AmadeusProvider``   – Flight Inspiration Search (+ optional fare verification)
* ``TravelpayoutsProvider`` – Aviasales "cheap prices" feed

Adding a source means implementing ``search()`` and registering it in
``build_provider()``; nothing else in the app needs to change.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from . import data
from .config import Config
from .core import Offer, SearchParams, distance_between, estimate_duration_min
from .data import Airport

USER_AGENT = "flight-scout/1.0 (+https://localhost)"


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


class ProviderError(RuntimeError):
    """Raised when an upstream data source fails in a way worth showing users."""


_SSL_CONTEXT: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """TLS context verified against the OS trust store.

    Some Windows machines ship a Python whose bundled CA file is stale or absent,
    which makes every HTTPS call fail with "certificate has expired" even though
    the browser opens the same site fine. Building the context from the Windows
    ROOT store (what browsers use) fixes that while keeping verification on.
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT

    if os.name == "nt":
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.check_hostname = True
            loaded = 0
            for cert, encoding, _trust in ssl.enum_certificates("ROOT"):
                if encoding != "x509_asn":
                    continue
                try:
                    ctx.load_verify_locations(cadata=cert)
                    loaded += 1
                except (ssl.SSLError, ValueError):
                    continue
            if loaded >= 10:
                _SSL_CONTEXT = ctx
                return _SSL_CONTEXT
        except (AttributeError, OSError, ssl.SSLError):
            pass

    _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    form: bool = False,
    timeout: int = 20,
    retries: int = 2,
) -> dict[str, Any]:
    body = None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        if form:
            body = urllib.parse.urlencode(payload).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(payload).encode()
            hdrs["Content-Type"] = "application/json"

    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                last = exc
                continue
            raise ProviderError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}") from exc
        except urllib.error.URLError as exc:
            last = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise ProviderError(f"网络无法访问 {url.split('?')[0]}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"返回内容不是 JSON: {url.split('?')[0]}") from exc
    raise ProviderError(str(last))


def airline_name(code: str) -> str:
    meta = data.AIRLINES.get((code or "").upper())
    return meta[0] if meta else (code or "未知航司")


def airline_kind(code: str) -> str:
    meta = data.AIRLINES.get((code or "").upper())
    return meta[1] if meta else "full"


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #


@dataclass
class ProviderInfo:
    id: str
    name: str
    live: bool
    note: str
    price_basis: str  # round_trip | one_way | mixed


class Provider:
    info: ProviderInfo

    def search(self, params: SearchParams, destinations: Sequence[Airport]) -> list[Offer]:
        raise NotImplementedError

    def verify(self, offers: list[Offer], params: SearchParams) -> list[Offer]:
        """Optional second pass that replaces estimates with bookable fares."""
        return offers

    # ---- shared filter ---------------------------------------------------- #
    @staticmethod
    def keep(offer: Offer, params: SearchParams) -> bool:
        if not (params.depart_from <= offer.depart <= params.depart_to):
            return False
        if not (params.return_from <= offer.ret <= params.return_to):
            return False
        return params.nights_min <= offer.nights <= params.nights_max


# --------------------------------------------------------------------------- #
# Demo provider — deterministic synthetic model
# --------------------------------------------------------------------------- #

PEAK = [
    ((12, 19), (12, 23), 1.42),
    ((12, 24), (12, 26), 1.30),
    ((12, 27), (12, 31), 1.24),
    ((1, 1), (1, 4), 1.14),
]


def _peak_factor(d: date) -> float:
    for (m1, d1), (m2, d2), f in PEAK:
        if (d.month, d.day) >= (m1, d1) and (d.month, d.day) <= (m2, d2):
            return f
    return 1.0


class DemoProvider(Provider):
    info = ProviderInfo(
        id="demo",
        name="演示数据",
        live=False,
        note="按航线距离、圣诞旺季系数与航司类型生成的仿真报价，非真实票价，仅用于体验与排序。",
        price_basis="round_trip",
    )

    def search(self, params: SearchParams, destinations: Sequence[Airport]) -> list[Offer]:
        pairs = params.feasible_pairs(max_pairs=10)
        if not pairs:
            return []
        offers: list[Offer] = []
        for ap in destinations:
            offer = self._best_for_airport(ap, pairs, params)
            if offer:
                offers.append(offer)
        return offers

    def _best_for_airport(
        self, ap: Airport, pairs: list[tuple[date, date]], params: SearchParams
    ) -> Offer | None:
        origin = data.ORIGINS.get(params.origin, data.ORIGIN)
        km = distance_between(origin, ap)
        best: Offer | None = None
        for depart, ret in pairs:
            o = self._quote(ap, km, depart, ret, params.origin)
            if o and (best is None or o.price < best.price):
                best = o
        return best

    def _quote(
        self, ap: Airport, km: float, depart: date, ret: date, origin_code: str = "HKG"
    ) -> Offer | None:
        seed = f"{origin_code}|{ap.code}|{depart.isoformat()}|{ret.isoformat()}"
        rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())

        pool = [c for c in ap.airlines if c in data.AIRLINES] or ["CX"]
        code = rng.choice(pool)
        kind = airline_kind(code)

        # Low-season round-trip baseline, calibrated against typical HKG fares:
        # Taipei ~1.0k, Bangkok ~1.4k, Tokyo ~2.0k, London ~6.0k HKD.
        base = 700.0 + 0.48 * min(km, 4000.0) + 0.62 * max(0.0, km - 4000.0)
        base *= 1.0 if kind == "full" else 0.68
        if code == "CX":
            base *= 1.12
        base *= data.XMAS_FACTOR.get(ap.region, 1.0) * _peak_factor(depart)
        base *= rng.uniform(0.90, 1.12)
        price = max(base, 420.0)

        stops = 0
        extra_min = 0
        if km > 6500 and rng.random() < 0.42:
            stops = 1
            price *= 0.88
            extra_min = 175

        return Offer.from_airport(
            ap,
            origin=origin_code,
            price=round(price / 10.0) * 10.0 + 9.0,
            currency="HKD",
            depart=depart,
            ret=ret,
            airline_code=code,
            airline=airline_name(code),
            stops=stops,
            duration_min=estimate_duration_min(km) + extra_min,
            source="demo",
        )


# --------------------------------------------------------------------------- #
# SerpApi — Google Travel Explore ("where is cheapest from HKG")
# --------------------------------------------------------------------------- #


class SerpApiProvider(Provider):
    """One call returns a ranked list of destinations with real round-trip fares.

    This is the closest replacement for the retired Amadeus "Flight Inspiration
    Search": Google Travel Explore answers exactly "from HKG, where is cheap".
    """

    info = ProviderInfo(
        id="serpapi",
        name="SerpApi · Google Flights",
        live=True,
        note="Google Travel Explore 实时往返报价；每次搜索约 5 次调用，免费额度 250 次/月，结果缓存 10 分钟。",
        price_basis="round_trip",
    )

    ENDPOINT = "https://serpapi.com/search"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -- low level --------------------------------------------------------- #
    def _query(self, origin: str, out_date: date, ret_date: date, direct_only: bool = False) -> dict[str, Any]:
        qs = urllib.parse.urlencode({
            "engine": "google_travel_explore",
            "departure_id": origin,
            "type": 1,                      # round trip
            "outbound_date": out_date.isoformat(),
            "return_date": ret_date.isoformat(),
            "currency": self.cfg.default_currency,
            "gl": "hk",
            "hl": "zh-cn",                  # simplified, matching the rest of the UI
            "travel_mode": 1,               # flights only
            "stops": 1 if direct_only else 0,
            "adults": 1,
            "api_key": self.cfg.serpapi_key,
        })
        payload = http_json(f"{self.ENDPOINT}?{qs}", timeout=60)
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(f"SerpApi: {payload['error']}")
        return payload

    def check_credentials(self) -> None:
        today = date.today()
        self._query("HKG", today + timedelta(days=45), today + timedelta(days=52))

    # -- search ------------------------------------------------------------ #
    def search(self, params: SearchParams, destinations: Sequence[Airport]) -> list[Offer]:
        pairs = params.feasible_pairs(max_pairs=30)
        if not pairs:
            return []
        k = min(5, len(pairs))
        picks = [0] if k == 1 else [round(i * (len(pairs) - 1) / (k - 1)) for i in range(k)]

        best: dict[str, Offer] = {}

        for i, idx in enumerate(picks):
            out_date, ret_date = pairs[idx]
            if i:
                time.sleep(0.25)  # stay well inside the free throughput limit
            payload = self._query(params.origin, out_date, ret_date, params.direct_only)

            for row in payload.get("destinations") or []:
                code = str(((row.get("destination_airport") or {}).get("code")) or "").upper()
                if not code or code == params.origin.upper():
                    continue  # no airport code, or "fly to where you already are"
                try:
                    price = float(row["flight_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if price <= 0:
                    continue

                ap = data.BY_CODE.get(code)
                if ap is None:
                    # A real, priced destination outside our curated table: keep it
                    # rather than throwing away data the user paid a query for.
                    coords = row.get("gps_coordinates") or {}
                    lat = float(coords.get("latitude") or 0.0)
                    lon = float(coords.get("longitude") or 0.0)
                    if not lat and not lon:
                        continue  # without coordinates distance/price-per-km would lie
                    name = str(row.get("name") or code).strip()
                    if name.endswith("市") and len(name) > 2:
                        name = name[:-1]
                    ap = Airport(
                        code=code,
                        city_zh=name,
                        city_en=name,
                        country_zh=str(row.get("country") or "其他"),
                        country_en=str(row.get("country") or ""),
                        region=data.region_for_country(row.get("country")),
                        lat=lat,
                        lon=lon,
                    )

                duration = row.get("flight_duration")
                offer = Offer.from_airport(
                    ap,
                    origin=params.origin,
                    price=price,
                    currency=self.cfg.default_currency,
                    depart=out_date,
                    ret=ret_date,
                    airline_code=str(row.get("airline_code") or ""),
                    airline=str(row.get("airline") or airline_name(str(row.get("airline_code") or ""))),
                    stops=int(row.get("number_of_stops") or 0),
                    duration_min=int(duration) if duration else 0,
                    source="serpapi",
                )
                if not self.keep(offer, params):
                    continue
                prev = best.get(code)
                if prev is None or offer.price < prev.price:
                    best[code] = offer

        return list(best.values())


# --------------------------------------------------------------------------- #
# Amadeus Self-Service
# --------------------------------------------------------------------------- #


class AmadeusProvider(Provider):
    info = ProviderInfo(
        id="amadeus",
        name="Amadeus Self-Service",
        live=True,
        note="Flight Inspiration Search 发现低价目的地，再用 Flight Offers Search 复核前 N 个报价。",
        price_basis="round_trip",
    )

    def __init__(self, cfg: Config, cache_token: bool = True):
        self.cfg = cfg
        self.base = cfg.amadeus_base
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._cache_enabled = cache_token
        self._cache_file: Path = Path(__file__).resolve().parent.parent / "data" / ".amadeus_token.json"

    # -- auth -------------------------------------------------------------- #
    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if self._cache_enabled and self._cache_file.exists():
            try:
                cached = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if cached.get("base") == self.base and time.time() < cached.get("exp", 0) - 60:
                    self._token = cached["token"]
                    self._token_exp = cached["exp"]
                    return self._token
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        resp = http_json(
            f"{self.base}/v1/security/oauth2/token",
            method="POST",
            form=True,
            payload={
                "grant_type": "client_credentials",
                "client_id": self.cfg.amadeus_client_id,
                "client_secret": self.cfg.amadeus_client_secret,
            },
        )
        token = resp.get("access_token")
        if not token:
            raise ProviderError("Amadeus 未返回 access_token，请检查 client id / secret")
        self._token = token
        self._token_exp = time.time() + float(resp.get("expires_in", 1799))
        try:
            if not self._cache_enabled:
                raise OSError("token cache disabled")
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(
                json.dumps({"token": token, "exp": self._token_exp, "base": self.base}),
                encoding="utf-8",
            )
        except OSError:
            pass
        return token

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return http_json(
            f"{self.base}{path}?{qs}",
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )

    def check_credentials(self) -> None:
        """Raise ProviderError when the configured key/secret are rejected."""
        self._token = None
        self._token_exp = 0.0
        self._access_token()

    # -- search ------------------------------------------------------------ #
    def search(self, params: SearchParams, destinations: Sequence[Airport]) -> list[Offer]:
        wanted = {ap.code for ap in destinations}
        by_dest: dict[str, dict[str, Any]] = {}

        for depart in params.sampled_depart_dates(5):
            payload = self._get(
                "/v1/shopping/flight-destinations",
                {
                    "origin": params.origin,
                    "departureDate": depart.isoformat(),
                    "oneWay": "false",
                    "nonStop": "true" if params.direct_only else "",
                },
            )
            for row in payload.get("data") or []:
                code = str(row.get("destination", "")).upper()
                if not code or (wanted and code not in wanted):
                    continue
                try:
                    price = float(row["price"]["total"])
                    dep = date.fromisoformat(row["departureDate"])
                    ret = date.fromisoformat(row["returnDate"])
                except (KeyError, TypeError, ValueError):
                    continue
                prev = by_dest.get(code)
                if prev and prev["price"] <= price:
                    continue
                by_dest[code] = {"price": price, "depart": dep, "ret": ret, "raw": row}

        offers: list[Offer] = []
        for code, entry in by_dest.items():
            ap = data.BY_CODE.get(code) or Airport(
                code=code, city_zh=code, city_en=code, country_zh="其他",
                country_en="", region="其他", lat=0.0, lon=0.0,
            )
            dep, ret = entry["depart"], entry["ret"]
            if not (params.return_from <= ret <= params.return_to):
                continue
            if params.nights_min <= (ret - dep).days <= params.nights_max:
                pass
            else:
                continue
            offers.append(Offer.from_airport(
                ap,
                origin=params.origin,
                price=entry["price"],
                currency="USD" if self.cfg.amadeus_env == "test" else self.cfg.default_currency,
                depart=dep,
                ret=ret,
                airline_code="",
                airline="",
                stops=0,
                duration_min=0,
                source="amadeus",
            ))
        return offers

    # -- verification ------------------------------------------------------ #
    def verify(self, offers: list[Offer], params: SearchParams) -> list[Offer]:
        if not offers:
            return offers
        # Cheapest first: those are the rows users will look at.
        todo = sorted(offers, key=lambda o: o.price)
        for offer in todo:
            try:
                payload = self._get(
                    "/v2/shopping/flight-offers",
                    {
                        "originLocationCode": params.origin,
                        "destinationLocationCode": offer.code,
                        "departureDate": offer.depart.isoformat(),
                        "returnDate": offer.ret.isoformat(),
                        "adults": 1,
                        "currencyCode": self.cfg.default_currency,
                        "max": 3,
                        "nonStop": "true" if params.direct_only else "false",
                    },
                )
            except ProviderError:
                return offers
            rows = payload.get("data") or []
            if not rows:
                continue
            best = min(rows, key=lambda r: float(r["price"]["grandTotal"]))
            price = float(best["price"]["grandTotal"])
            itin = best.get("itineraries") or [{}]
            segments = (itin[0].get("segments") or [{}])
            carrier = (best.get("validatingAirlineCodes") or [""])[0]
            total_min = sum(
                _iso_duration_min(i.get("duration", "")) for i in itin
            ) or 0
            offer.price = price
            offer.currency = best["price"].get("currency", self.cfg.default_currency)
            offer.stops = len(segments) - 1
            offer.airline_code = carrier
            offer.airline = airline_name(carrier)
            offer.duration_min = total_min
            offer.source = "amadeus-verified"
            time.sleep(0.12)  # stay well under the 10 req/s test quota
        return offers


def _iso_duration_min(value: str) -> int:
    """PT12H35M -> 755"""
    if not value or not value.startswith("PT"):
        return 0
    body = value[2:]
    num, total = "", 0
    for ch in body:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            total += int(num or 0) * 60
            num = ""
        elif ch == "M":
            total += int(num or 0)
            num = ""
    return total


# --------------------------------------------------------------------------- #
# Travelpayouts / Aviasales
# --------------------------------------------------------------------------- #


class TravelpayoutsProvider(Provider):
    info = ProviderInfo(
        id="travelpayouts",
        name="Travelpayouts",
        live=True,
        note="Aviasales 特价库：报价通常为单程最低价，适合比价排序，下单前请核对。",
        price_basis="one_way",
    )

    ENDPOINT = "https://api.travelpayouts.com/v1/prices/cheap"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def check_credentials(self) -> None:
        qs = urllib.parse.urlencode({
            "origin": "HKG",
            "destination": "TPE",
            "depart_date": "2026-12",
            "currency": "hkd",
            "token": self.cfg.travelpayouts_token,
        })
        payload = http_json(f"{self.ENDPOINT}?{qs}")
        if payload.get("error"):
            raise ProviderError(f"Travelpayouts 拒绝了这个 token：{payload.get('error')}")

    def search(self, params: SearchParams, destinations: Sequence[Airport]) -> list[Offer]:
        wanted = {ap.code for ap in destinations}
        offers: list[Offer] = []
        seen: set[str] = set()
        months = sorted({d.strftime("%Y-%m") for d in params.sampled_depart_dates(5)})

        for month in months:
            qs = urllib.parse.urlencode({
                "origin": params.origin,
                "destination": "-",
                "depart_date": month,
                "currency": self.cfg.default_currency.lower(),
                "token": self.cfg.travelpayouts_token,
            })
            payload = http_json(f"{self.ENDPOINT}?{qs}")
            if not payload.get("success", True):
                raise ProviderError(f"Travelpayouts 返回错误: {payload}")
            for code, variants in (payload.get("data") or {}).items():
                code = code.upper()
                if wanted and code not in wanted:
                    continue
                for variant in (variants or {}).values():
                    try:
                        price = float(variant["price"])
                        dep = datetime.fromisoformat(
                            str(variant["departure_at"]).replace("Z", "+00:00")
                        ).date()
                        ret_raw = variant.get("return_at")
                        ret = (
                            datetime.fromisoformat(str(ret_raw).replace("Z", "+00:00")).date()
                            if ret_raw else dep
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                    offer = Offer.from_airport(
                        data.BY_CODE[code],
                        origin=params.origin,
                        price=price,
                        currency=str(payload.get("currency", self.cfg.default_currency)).upper(),
                        depart=dep,
                        ret=ret,
                        airline_code=str(variant.get("airline", "")),
                        airline=airline_name(str(variant.get("airline", ""))),
                        stops=int(variant.get("transfers", 0) or 0),
                        duration_min=0,
                        source="travelpayouts",
                    )
                    if not self.keep(offer, params):
                        continue
                    if code in seen and any(o.price <= price for o in offers if o.code == code):
                        continue
                    seen.add(code)
                    offers.append(offer)
        return offers


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def validate_serpapi(api_key: str) -> None:
    SerpApiProvider(Config(serpapi_key=api_key)).check_credentials()


def validate_amadeus(client_id: str, client_secret: str, env: str = "test") -> None:
    """Check a key/secret pair without touching the on-disk token cache."""
    AmadeusProvider(
        Config(amadeus_client_id=client_id, amadeus_client_secret=client_secret, amadeus_env=env),
        cache_token=False,
    ).check_credentials()


def validate_travelpayouts(token: str) -> None:
    TravelpayoutsProvider(Config(travelpayouts_token=token)).check_credentials()


def build_provider(name: str, cfg: Config) -> Provider:
    name = (name or "auto").lower()
    if name == "auto":
        if cfg.has_serpapi:
            name = "serpapi"
        elif cfg.has_travelpayouts:
            name = "travelpayouts"
        elif cfg.has_amadeus:
            name = "amadeus"
        else:
            name = "demo"
    if name in ("demo", "mock", "offline"):
        return DemoProvider()
    if name in ("serpapi", "serp"):
        if not cfg.has_serpapi:
            raise ProviderError("未配置 SerpApi key：请设置 SERPAPI_KEY 或在网页里填写")
        return SerpApiProvider(cfg)
    if name == "amadeus":
        if not cfg.has_amadeus:
            raise ProviderError("未配置 Amadeus key：请设置 AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET")
        return AmadeusProvider(cfg)
    if name in ("travelpayouts", "aviasales", "tp"):
        if not cfg.has_travelpayouts:
            raise ProviderError("未配置 TRAVELPAYOUTS_TOKEN")
        return TravelpayoutsProvider(cfg)
    raise ProviderError(f"未知数据源: {name}")
