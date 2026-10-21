"""Unit tests — run with:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flight_scout import data, providers, service  # noqa: E402
from flight_scout.site_export import build_snapshot, export_site  # noqa: E402
from flight_scout.config import Config, mask, save_config  # noqa: E402
from flight_scout.core import (  # noqa: E402
    Offer,
    ParamError,
    SearchParams,
    annotate,
    apply_filters,
    default_windows,
    distance_from_hkg,
    haversine_km,
)
from flight_scout.report import to_csv, to_markdown  # noqa: E402
from flight_scout.service import run_search  # noqa: E402


class TestGeography(unittest.TestCase):
    def test_known_distances(self):
        tpe = data.BY_CODE["TPE"]
        lhr = data.BY_CODE["LHR"]
        self.assertAlmostEqual(distance_from_hkg(tpe), 806, delta=40)
        self.assertAlmostEqual(distance_from_hkg(lhr), 9630, delta=120)

    def test_haversine_is_symmetric(self):
        a = haversine_km(22.3, 113.9, 51.5, -0.45)
        b = haversine_km(51.5, -0.45, 22.3, 113.9)
        self.assertAlmostEqual(a, b, places=6)


class TestWindows(unittest.TestCase):
    def test_before_christmas_points_to_this_year(self):
        w = default_windows(date(2026, 10, 20))
        self.assertEqual(w["depart_from"], date(2026, 12, 18))
        self.assertEqual(w["return_to"], date(2027, 1, 4))

    def test_after_christmas_points_to_next_year(self):
        w = default_windows(date(2026, 12, 27))
        self.assertEqual(w["depart_from"], date(2027, 12, 18))

    def test_feasible_pairs_respect_constraints(self):
        p = SearchParams.from_dict({})
        pairs = p.feasible_pairs(30)
        self.assertTrue(pairs)
        for dep, ret in pairs:
            self.assertGreaterEqual(dep, p.depart_from)
            self.assertLessEqual(dep, p.depart_to)
            self.assertGreaterEqual(ret, p.return_from)
            self.assertLessEqual(ret, p.return_to)
            self.assertGreaterEqual((ret - dep).days, p.nights_min)
            self.assertLessEqual((ret - dep).days, p.nights_max)


class TestParams(unittest.TestCase):
    def test_rejects_backwards_departure_window(self):
        with self.assertRaises(ParamError):
            SearchParams.from_dict({"depart_from": "2026-12-24", "depart_to": "2026-12-18"})

    def test_rejects_impossible_nights(self):
        with self.assertRaises(ParamError):
            SearchParams.from_dict({
                "depart_from": "2026-12-20", "depart_to": "2026-12-21",
                "return_from": "2026-12-22", "return_to": "2026-12-23",
                "nights_min": 10, "nights_max": 12,
            })

    def test_string_booleans_from_query_strings(self):
        self.assertTrue(SearchParams.from_dict({"direct_only": "true"}).direct_only)
        self.assertFalse(SearchParams.from_dict({"direct_only": "false"}).direct_only)

    def test_bad_date_message_is_chinese(self):
        with self.assertRaises(ParamError) as ctx:
            SearchParams.from_dict({"depart_from": "20/12/2026"})
        self.assertIn("YYYY-MM-DD", str(ctx.exception))


class TestDemoSearch(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.params = SearchParams.from_dict({"nights_min": 4, "nights_max": 10})

    def test_is_deterministic(self):
        a = run_search(self.params, self.cfg)
        b = run_search(self.params, self.cfg)
        self.assertEqual(
            [r["price"] for r in a["results"]],
            [r["price"] for r in b["results"]],
        )

    def test_covers_most_destinations(self):
        payload = run_search(self.params, self.cfg)
        self.assertGreater(payload["summary"]["count"], 80)
        self.assertFalse(payload["meta"]["live"])
        self.assertEqual(payload["meta"]["provider"], "demo")

    def test_results_sorted_by_price(self):
        payload = run_search(self.params, self.cfg)
        prices = [r["price"] for r in payload["results"]]
        self.assertEqual(prices, sorted(prices))

    def test_every_row_has_links_and_dates(self):
        for row in run_search(self.params, self.cfg)["results"]:
            self.assertTrue(row["booking_links"]["google"].startswith("https://www.google.com/travel/flights"))
            self.assertGreater(row["nights"], 0)
            self.assertLessEqual(row["stops"], 1)
            self.assertIn(row["cc"], {v for v in data.COUNTRY_CC.values()})

    def test_direct_filter(self):
        p = SearchParams.from_dict({"direct_only": True})
        payload = run_search(p, self.cfg)
        self.assertTrue(payload["results"])
        self.assertTrue(all(r["stops"] == 0 for r in payload["results"]))

    def test_region_filter(self):
        p = SearchParams.from_dict({"regions": "日本,韩国"})
        payload = run_search(p, self.cfg)
        self.assertTrue(payload["results"])
        self.assertEqual({r["region"] for r in payload["results"]}, {"日本", "韩国"})

    def test_max_price_filter(self):
        p = SearchParams.from_dict({"max_price": 900})
        payload = run_search(p, self.cfg)
        self.assertTrue(all(r["price"] <= 900 for r in payload["results"]))


class TestScoring(unittest.TestCase):
    def _offers(self):
        return [
            Offer(
                code="A", city="甲", city_en="A", country="日本", region="日本", flag="", cc="JP",
                lat=0, lon=0, price=1000, currency="HKD", depart=date(2026, 12, 20),
                ret=date(2026, 12, 26), airline_code="CX", airline="国泰", stops=0,
                duration_min=200, distance_km=2000,
            ),
            Offer(
                code="B", city="乙", city_en="B", country="日本", region="日本", flag="", cc="JP",
                lat=0, lon=0, price=3000, currency="HKD", depart=date(2026, 12, 20),
                ret=date(2026, 12, 26), airline_code="CX", airline="国泰", stops=1,
                duration_min=900, distance_km=9000,
            ),
        ]

    def test_cheapest_scores_highest(self):
        offers = annotate(self._offers())
        self.assertGreater(offers[0].deal_score, offers[1].deal_score)
        self.assertTrue(all(0 <= o.deal_score <= 100 for o in offers))
        self.assertGreater(offers[0].saving_pct, 0)  # cheaper than region median

    def test_tags(self):
        offers = annotate(self._offers())
        self.assertIn("直飞", offers[0].tags)
        self.assertIn("1次转机", offers[1].tags)

    def test_apply_filters(self):
        offers = annotate(self._offers())
        p = SearchParams.from_dict({"direct_only": True})
        self.assertEqual([o.code for o in apply_filters(offers, p)], ["A"])


class TestExports(unittest.TestCase):
    def test_csv_has_header_and_rows(self):
        payload = run_search(SearchParams.from_dict({}), Config())
        text = to_csv(payload)
        lines = text.strip().splitlines()
        self.assertIn("目的地", lines[0])
        self.assertEqual(len(lines), len(payload["results"]) + 1)

    def test_markdown_mentions_demo(self):
        payload = run_search(SearchParams.from_dict({}), Config())
        md = to_markdown(payload)
        self.assertIn("演示数据", md)
        self.assertIn("性价比", md)


class TestAmadeusParsing(unittest.TestCase):
    """The live path cannot be called without a key, so parse canned payloads."""

    def setUp(self):
        self.orig = providers.http_json
        self.cfg = Config(amadeus_client_id="id", amadeus_client_secret="secret", amadeus_env="test")

    def tearDown(self):
        providers.http_json = self.orig

    def test_inspiration_payload_becomes_offers(self):
        def fake(url, **kwargs):
            if "oauth2/token" in url:
                return {"access_token": "tok", "expires_in": 1799}
            return {
                "data": [
                    {"destination": "NRT", "departureDate": "2026-12-21",
                     "returnDate": "2026-12-27", "price": {"total": "812.40"}},
                    {"destination": "TPE", "departureDate": "2026-12-22",
                     "returnDate": "2026-12-28", "price": {"total": "410.10"}},
                    # outside the requested return window -> must be dropped
                    {"destination": "KIX", "departureDate": "2026-12-21",
                     "returnDate": "2027-02-10", "price": {"total": "700.00"}},
                ]
            }

        providers.http_json = fake
        provider = providers.AmadeusProvider(self.cfg, cache_token=False)
        offers = provider.search(SearchParams.from_dict({}), data.DESTINATIONS)
        codes = {o.code for o in offers}
        self.assertEqual(codes, {"NRT", "TPE"})
        nrt = next(o for o in offers if o.code == "NRT")
        self.assertAlmostEqual(nrt.price, 812.40)
        self.assertEqual(nrt.depart, date(2026, 12, 21))
        self.assertGreater(nrt.distance_km, 2000)

    def test_missing_credentials_is_reported(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_provider("amadeus", Config())


class TestTravelpayoutsParsing(unittest.TestCase):
    def setUp(self):
        self.orig = providers.http_json

    def tearDown(self):
        providers.http_json = self.orig

    def test_cheap_feed_becomes_offers(self):
        def fake(url, **kwargs):
            return {
                "success": True,
                "currency": "hkd",
                "data": {
                    "NRT": {"0": {"price": 4200, "airline": "CX", "transfers": 0,
                                  "departure_at": "2026-12-21T00:00:00Z",
                                  "return_at": "2026-12-28T00:00:00Z"}},
                    "TPE": {"0": {"price": 1300, "airline": "UO", "transfers": 0,
                                  "departure_at": "2026-12-20T00:00:00Z",
                                  "return_at": "2026-12-27T00:00:00Z"}},
                },
            }

        providers.http_json = fake
        cfg = Config(travelpayouts_token="tok")
        provider = providers.TravelpayoutsProvider(cfg)
        offers = provider.search(SearchParams.from_dict({}), data.DESTINATIONS)
        self.assertEqual({o.code for o in offers}, {"NRT", "TPE"})
        self.assertEqual({o.currency for o in offers}, {"HKD"})
        self.assertEqual(provider.info.price_basis, "one_way")


class TestSerpApiParsing(unittest.TestCase):
    """Google Travel Explore is the recommended live source."""

    def setUp(self):
        self.orig = providers.http_json

    def tearDown(self):
        providers.http_json = self.orig

    def test_travel_explore_payload_becomes_offers(self):
        def fake(url, **kwargs):
            return {
                "destinations": [
                    {
                        "destination_airport": {"code": "NRT"}, "name": "Tokyo", "country": "Japan",
                        "gps_coordinates": {"latitude": 35.68, "longitude": 139.76},
                        "flight_price": 3280, "flight_duration": 260,
                        "number_of_stops": 0, "airline": "Cathay Pacific", "airline_code": "CX",
                    },
                    {
                        "destination_airport": {"code": "BKK"}, "name": "Bangkok", "country": "Thailand",
                        "gps_coordinates": {"latitude": 13.69, "longitude": 100.75},
                        "flight_price": 1490, "flight_duration": 180,
                        "number_of_stops": 0, "airline": "HK Express", "airline_code": "UO",
                    },
                    {"destination_airport": {"code": "XXX"}, "name": "No price"},
                ]
            }

        providers.http_json = fake
        provider = providers.SerpApiProvider(Config(serpapi_key="k"))
        offers = provider.search(SearchParams.from_dict({}), data.DESTINATIONS)
        codes = {o.code for o in offers}
        self.assertEqual(codes, {"NRT", "BKK"})
        bkk = next(o for o in offers if o.code == "BKK")
        self.assertAlmostEqual(bkk.price, 1490)
        self.assertEqual(bkk.currency, "HKD")
        self.assertEqual(bkk.airline, "HK Express")
        self.assertEqual(provider.info.price_basis, "round_trip")

    def test_error_payload_raises_provider_error(self):
        providers.http_json = lambda url, **kwargs: {"error": "Invalid API key"}
        with self.assertRaises(providers.ProviderError):
            providers.SerpApiProvider(Config(serpapi_key="bad")).check_credentials()


class TestCacheShape(unittest.TestCase):
    """Filters must be applied locally, never by re-querying the provider."""

    def test_region_filter_reuses_one_fetch(self):
        cfg = Config()
        calls = {"n": 0}
        original = providers.DemoProvider.search

        def counting(self, params, destinations):
            calls["n"] += 1
            return original(self, params, destinations)

        providers.DemoProvider.search = counting
        try:
            base = SearchParams.from_dict({})
            offers, meta = service.fetch_offers(base, cfg)
            self.assertEqual(calls["n"], 1)

            everything = service.build_payload(offers, base, meta)
            japan = SearchParams.from_dict({"regions": "日本"})
            only_japan = service.build_payload(offers, japan, meta)

            self.assertEqual(calls["n"], 1, "filtering must not fetch again")
            self.assertLess(only_japan["summary"]["count"], everything["summary"]["count"])
            self.assertEqual({r["region"] for r in only_japan["results"]}, {"日本"})
        finally:
            providers.DemoProvider.search = original

    def test_sort_changes_order_without_refetch(self):
        cfg = Config()
        base = SearchParams.from_dict({})
        offers, meta = service.fetch_offers(base, cfg)
        by_price = service.build_payload(offers, base, meta)["results"]
        cheapest = SearchParams.from_dict({"sort": "price"})
        by_value = SearchParams.from_dict({"sort": "value"})
        a = service.build_payload(offers, cheapest, meta)["results"]
        b = service.build_payload(offers, by_value, meta)["results"]
        self.assertEqual([r["price"] for r in a], sorted(r["price"] for r in a))
        self.assertNotEqual([r["code"] for r in a], [r["code"] for r in b])


class TestStaticSite(unittest.TestCase):
    """The GitHub Pages build must be self-contained and origin-tagged."""

    def test_snapshot_has_every_field_the_page_needs(self):
        snap = build_snapshot(Config(), origins=["HKG", "SZX"], provider="demo")
        self.assertEqual([o["code"] for o in snap["origins"]], ["HKG", "SZX"])
        self.assertIn("window", snap)
        self.assertIn("depart_from", snap["window"])
        self.assertTrue(snap["offers"])
        for offer in snap["offers"]:
            self.assertIn(offer["origin"], ("HKG", "SZX"))
            self.assertTrue(offer["booking_links"]["google"].startswith("https://"))
            self.assertGreater(offer["price"], 0)

    def test_export_writes_a_servable_directory(self):
        out = Path(__file__).resolve().parent / "_site_export_test"
        try:
            result = export_site(out, Config(), origins=["HKG"], provider="demo")
            for name in ("index.html", "style.css", "app.js", ".nojekyll", "data/snapshot.json"):
                self.assertTrue((out / name).exists(), f"缺少 {name}")
            self.assertGreater(result["offers"], 0)
            snap = json.loads((out / "data" / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(len(snap["offers"]), result["offers"])
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestConfigFile(unittest.TestCase):
    def test_save_merges_and_keeps_existing_keys(self):
        path = Path(__file__).resolve().parent / "_config_test.json"
        try:
            path.write_text(json.dumps({"currency": "HKD", "amadeus_env": "test"}), encoding="utf-8")
            save_config({"amadeus_client_id": "id1", "amadeus_client_secret": "sec1"}, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["amadeus_client_id"], "id1")
            self.assertEqual(saved["currency"], "HKD")
        finally:
            path.unlink(missing_ok=True)

    def test_mask_hides_the_secret(self):
        self.assertEqual(mask(""), "")
        masked = mask("abcdefghijklmnop")
        self.assertNotIn("ijkl", masked)
        self.assertTrue(masked.endswith("mnop"))


class TestProviderRegistry(unittest.TestCase):
    def test_auto_falls_back_to_demo(self):
        self.assertEqual(providers.build_provider("auto", Config()).info.id, "demo")

    def test_auto_prefers_amadeus(self):
        cfg = Config(amadeus_client_id="a", amadeus_client_secret="b")
        self.assertEqual(providers.build_provider("auto", cfg).info.id, "amadeus")

    def test_unknown_provider(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_provider("kayak", Config())


if __name__ == "__main__":
    unittest.main(verbosity=2)
