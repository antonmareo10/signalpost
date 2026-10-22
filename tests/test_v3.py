"""Offline tests for v1.2.0: other spellings of the same site (www / apex / root) after a failure that says nothing
about the site, never after a refusal. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signalpost.net import FetchResult  # noqa: E402
from signalpost.web import Candidate, Company, SiteResearcher, alternate_urls, recoverable_failure  # noqa: E402

ORG = "925854743"
PAGE = ("<html><head><title>Bjelk</title></head><body><h1>Bjelk</h1>"
        "<footer>Bjelk AS · Org.nr. 925 854 743 · Oslo</footer></body></html>")


def ok(url: str) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=200, content_type="text/html; charset=utf-8", body=PAGE.encode(),
                       text=PAGE, sha256="a" * 64, retrieved_at="2026-10-22T00:00:00Z")


def failed(url: str, *, status=None, error="", blocked=False) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=status, error=error, blocked=blocked, retrieved_at="2026-10-22T00:00:00Z")


class FakeFetcher:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        answer = self.answers.get(url) or self.answers.get(url.rstrip("/"))
        return answer(url) if answer else failed(url, error="URLError: timed out")


class AlternateSpellingTests(unittest.TestCase):
    def test_which_failures_are_recoverable(self):
        self.assertTrue(recoverable_failure(failed("u", error="unsafe_url: hostname did not resolve", blocked=True)))
        self.assertTrue(recoverable_failure(failed("u", error="URLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")))
        self.assertTrue(recoverable_failure(failed("u", error="URLError: timed out")))
        self.assertTrue(recoverable_failure(failed("u", status=404, error="HTTP 404")))
        self.assertFalse(recoverable_failure(failed("u", error="robots.txt disallows this URL", blocked=True)))
        self.assertFalse(recoverable_failure(failed("u", error="unsafe_url: non-public address blocked", blocked=True)))
        for refusal in (401, 403, 429):
            self.assertFalse(recoverable_failure(failed("u", status=refusal, error=f"HTTP {refusal}")))

    def test_alternates_stay_on_the_same_registrable_domain(self):
        self.assertEqual(alternate_urls("https://mossbilverksted.no"), ["https://www.mossbilverksted.no/"])
        self.assertEqual(alternate_urls("https://www.fjellstova.com"), ["https://fjellstova.com/"])
        self.assertEqual(alternate_urls("https://www.paradigma.no/gammel/side.html"),
                         ["https://www.paradigma.no/", "https://paradigma.no/"])
        self.assertEqual(alternate_urls("https://pdi.trading.no"), ["https://www.pdi.trading.no/"])
        self.assertEqual(alternate_urls("not a url"), [])

    def _research(self, answers, url="https://bjelk.no", strength="weak"):
        fetcher = FakeFetcher(answers)
        researcher = SiteResearcher(fetcher)  # type: ignore[arg-type]
        researcher._name_unique = lambda company: False  # type: ignore[assignment]
        result = researcher.research(Company(org=ORG, name="BJELK AS"), Candidate(url, "domain_guess_from_legal_name", strength))
        return result, fetcher.calls

    def test_dns_failure_on_apex_falls_back_to_www_and_still_needs_proof(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, error="unsafe_url: hostname did not resolve", blocked=True),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "verified")
        self.assertEqual(result.reason, "organisation number shown on the site")
        self.assertEqual(result.home_url, "https://www.bjelk.no/")
        self.assertIn("https://www.bjelk.no/", calls)

    def test_robots_refusal_is_never_retried_under_another_spelling(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, error="robots.txt disallows this URL", blocked=True),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "blocked")
        self.assertNotIn("https://www.bjelk.no/", calls)

    def test_http_refusal_is_never_retried_under_another_spelling(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, status=403, error="HTTP 403"),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "blocked")
        self.assertNotIn("https://www.bjelk.no/", calls)

    def test_refusal_on_the_alternate_is_reported_as_blocked(self):
        result, _ = self._research({
            "https://bjelk.no": lambda u: failed(u, error="URLError: timed out"),
            "https://www.bjelk.no/": lambda u: failed(u, error="robots.txt disallows this URL", blocked=True),
        })
        self.assertEqual(result.state, "blocked")

    def test_both_spellings_down_stays_unreachable(self):
        result, _ = self._research({
            "https://bjelk.no": lambda u: failed(u, error="URLError: timed out"),
        })
        self.assertEqual(result.state, "unreachable")


class SmallCompanyTests(unittest.TestCase):
    def test_activity_tiers(self):
        from signalpost.agent import Agent
        tier = Agent._activity_tier
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", employees=2)), "operating")
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", revenue=1_500_000)), "operating")
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", revenue=300_000)), "small")
        self.assertIsNone(tier(Company(org=ORG, name="BJELK AS", revenue=20_000)))
        self.assertIsNone(tier(Company(org=ORG, name="BJELK HOLDING AS", revenue=5_000_000)))
        self.assertIsNone(tier(Company(org=ORG, name="BJELK AS", revenue=5_000_000, industry="68.209")))

    def _decide(self, note, **proof):
        base = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None, "name_identity": {"url": "u"},
                "name_anywhere": None, "domain_name": None, "legal_name_exact": None, "norwegian_context": True}
        base.update(proof)
        researcher = SiteResearcher(fetcher=None)  # type: ignore[arg-type]
        researcher._name_unique = lambda company: True  # type: ignore[assignment]
        return researcher._decide(Company(org=ORG, name="BJELK AS"), Candidate("https://bjelk.no", "domain_guess_from_legal_name",
                                                                             "weak", note), base, "bjelk.no")

    def test_unique_name_alone_verifies_an_operating_company_but_not_a_small_one(self):
        from signalpost.web import LOW_ACTIVITY
        self.assertEqual(self._decide("")[0], "verified")
        self.assertEqual(self._decide(LOW_ACTIVITY)[0], "rejected")

    def test_small_company_still_verified_by_orgnr_or_registered_contact(self):
        from signalpost.web import LOW_ACTIVITY
        self.assertEqual(self._decide(LOW_ACTIVITY, orgnr={"url": "u", "excerpt": "Org.nr. 925 854 743"})[0], "verified")
        self.assertEqual(self._decide(LOW_ACTIVITY, phone={"url": "u", "digits": "92630552"})[0], "verified")

    def test_brand_separators_are_dropped(self):
        from signalpost.web import clean_brand
        self.assertEqual(clean_brand("Tonemakeriet |"), "Tonemakeriet")
        self.assertEqual(clean_brand("– Bjelk –"), "Bjelk")
        self.assertEqual(clean_brand("Vin & Medisin"), "Vin & Medisin")


if __name__ == "__main__":
    unittest.main()
