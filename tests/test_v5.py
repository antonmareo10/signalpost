"""Offline tests for 1.4.0: the overview, sourced sentences, what changed year on year, the stated reason for every gap,
and the viewer that keeps a compact index in the page and loads large batches' profiles on demand.
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from signalpost.registry import account_claims  # noqa: E402
from signalpost.site import build_site  # noqa: E402
from signalpost.synth import build_summary, check_sentence  # noqa: E402
from test_v2 import ORG, SummaryV2Tests, fetched  # noqa: E402


def year(y: int, revenue: float, operating: float, equity: float, assets: float) -> dict:
    return {"regnskapsperiode": {"fraDato": f"{y}-01-01", "tilDato": f"{y}-12-31"}, "regnskapstype": "SELSKAP", "valuta": "NOK",
            "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": revenue}, "driftsresultat": operating}},
            "eiendeler": {"sumEiendeler": assets}, "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": equity}}}


def ledger_with_accounts(years: list[dict]):
    ledger = SummaryV2Tests().build()
    state, rows = account_claims(ledger, fetched(f"https://data.brreg.no/regnskapsregisteret/regnskap/{ORG}", years))
    assert state == "available"
    return ledger, rows


class OverviewTests(unittest.TestCase):
    def summary(self, years, **ctx):
        ledger, rows = ledger_with_accounts(years)
        base = {"accounts": rows, "changes": [], "missing": ["website", "profiles", "hiring", "activity"], "today": "2026-10-22",
                "states": {"website": "not_available", "hiring": "not_available"},
                "notes": {"website": "no website listed in the register and no verifiable candidate"}}
        base.update(ctx)
        return ledger, build_summary(ledger, base)

    def test_overview_says_what_it_is_how_it_is_doing_what_changed_and_what_is_missing(self):
        ledger, s = self.summary([year(2025, 4_200_000, -127_000, 3_100_000, 4_500_000), year(2024, 4_700_000, 25_000, 3_200_000, 4_600_000),
                                  year(2023, 5_200_000, 90_000, 3_300_000, 4_700_000)])
        overview = s["parts"]["overview"]
        self.assertTrue(overview[0].startswith("WYSSEN NORGE AS is a private limited company in other technical consultancy, founded in 2015"))
        self.assertIn("In 2025 it had revenue of NOK 4.2 m, down 10.6% on 2024 and lower for the second year running, "
                      "made an operating loss of NOK 127 k and had equity of NOK 3.1 m.", overview)
        self.assertTrue(any(t.startswith("Recent changes: registered employees fell from 6 to 5 on 2026-09-14") for t in overview))
        self.assertEqual(overview[-1], "Not found: a verified website, company-owned social profiles, active job ads and "
                                       "dated posts or news on its own channels.")
        self.assertEqual(s["dropped_unsupported_sentences"], 0)
        self.assertTrue(s["text"].startswith("In brief: "))
        self.assertIn(" What changed: ", s["text"])
        self.assertIn(" Not found: ", s["text"])
        changed = " ".join(s["parts"]["what_changed"])
        self.assertIn("Between the 2024 and 2025 accounts, revenue fell 10.6% (from NOK 4.7 m to NOK 4.2 m), the second fall in a row; "
                      "the operating result turned from a profit of NOK 25 k to a loss of NOK 127 k.", changed)
        self.assertTrue(changed.startswith("This is our first run for this company"))

    def test_every_sentence_with_claims_names_its_sources(self):
        ledger, s = self.summary([year(2025, 4_200_000, -127_000, 3_100_000, 4_500_000), year(2024, 4_700_000, 25_000, 3_200_000, 4_600_000)])
        urls = {src["url"] for src in s["sources"]}
        self.assertIn(f"https://data.brreg.no/regnskapsregisteret/regnskap/{ORG}", urls)
        self.assertEqual([src["n"] for src in s["sources"]], list(range(1, len(s["sources"]) + 1)))
        for sentence in s["sentences"]:
            self.assertTrue(check_sentence(sentence, ledger))
            if sentence["claim_ids"]:
                self.assertTrue(sentence["sources"], sentence["text"])
        self.assertIn("### Sources", s["markdown"])
        self.assertRegex(s["markdown"], r"\[1\] .+, retrieved 2026-10-22: https://")
        self.assertTrue(all(src["retrieved_at"] for src in s["sources"]))

    def test_meaningless_ratios_are_left_out(self):
        _, s = self.summary([year(2025, 1_000, -32_000, -1_200_000, 4)])
        money = " ".join(s["parts"]["money"])
        self.assertNotIn("equity ratio", money)
        self.assertNotIn("operating margin", money)
        self.assertIn("had negative equity (NOK -1.2 m)", " ".join(s["parts"]["overview"]))

    def test_since_previous_run(self):
        _, s = self.summary([year(2025, 4_200_000, -127_000, 3_100_000, 4_500_000)], previous_run_id="run-1",
                            previous_completed_at="2026-10-21T10:00:00Z")
        self.assertEqual(s["parts"]["what_changed"][0], "Since our previous run on 2026-10-21, nothing material has changed.")

    def test_flat_years_and_close_amounts_read_correctly(self):
        _, s = self.summary([year(2025, 144_000, -8_210, 100_000, 200_000), year(2024, 144_000, -8_200, 90_000, 190_000)])
        self.assertIn("had revenue of NOK 144 k, unchanged on 2024", " ".join(s["parts"]["overview"]))
        changed = " ".join(s["parts"]["what_changed"])
        self.assertIn("revenue was unchanged at NOK 144 k; the operating result went from NOK -8.20 k to NOK -8.21 k", changed)
        self.assertEqual(s["dropped_unsupported_sentences"], 0)

    def test_net_result_stands_in_when_the_latest_year_has_nothing_else(self):
        ledger, rows = ledger_with_accounts([year(2024, 1_000_000, 50_000, 300_000, 900_000)])
        rows.insert(0, {"year": "2025", "account_type": "SELSKAP"})
        net = next(c for c in ledger.claims if c["field"] == "operating_result")
        rows[0]["net_result"] = {"value": net["value"], "claim_id": net["id"]}
        s = build_summary(ledger, {"accounts": rows, "changes": [], "missing": [], "today": "2026-10-22"})
        self.assertIn("In 2025 it made a net profit of NOK 50 k.", s["parts"]["overview"])


class RoleSignalTests(unittest.TestCase):
    def test_a_new_accountant_is_a_change_but_not_a_leadership_signal(self):
        from signalpost.ledger import Document, canonical_json
        ledger = SummaryV2Tests().build()
        data = {"rollegrupper": [{"type": {"kode": "REGN"}, "sistEndret": "2026-09-01"}, {"type": {"kode": "STYR"}, "sistEndret": "2024-01-02"}]}
        doc = Document(url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}/roller", source_class="official_roles",
                       retrieved_at="2026-10-22T09:00:00Z", sha256="c" * 64, text=canonical_json(data), data=data)
        ledger.json_claim(doc, "/rollegrupper/0/sistEndret", "activity", "registry_role_change", qualifier="REGN", effective_at="2026-09-01",
                          display="Accountant entry last changed in the register on 2026-09-01", extra={"event_date": "2026-09-01"})
        ledger.json_claim(doc, "/rollegrupper/1/sistEndret", "activity", "registry_role_change", qualifier="STYR", effective_at="2024-01-02",
                          display="Board entry last changed in the register on 2024-01-02", extra={"event_date": "2024-01-02"})
        s = build_summary(ledger, {"accounts": [], "changes": [], "missing": [], "today": "2026-10-22"})
        self.assertIn("The most recent registered change to its roles was on 2026-09-01 (accountant entry).", s["parts"]["what_changed"])
        self.assertFalse(any(x["text"].startswith("Leadership or board") for x in s["signals"]))
        self.assertNotIn("accountant", " ".join(s["parts"]["overview"]))

    def test_unspecified_industry_is_not_presented_as_a_line_of_business(self):
        from signalpost.ledger import Ledger
        from test_v2 import entity_doc
        ledger = Ledger(ORG)
        doc = entity_doc({"navn": "S. M. N. INVEST AS", "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                          "naeringskode1": {"kode": "00.000", "beskrivelse": "Uoppgitt"}})
        ledger.json_claim(doc, "/navn", "identity", "legal_name")
        ledger.json_claim(doc, "/organisasjonsform", "identity", "legal_form", value={"code": "AS", "description": "Aksjeselskap"})
        ledger.json_claim(doc, "/naeringskode1", "identity", "industry", value={"code": "00.000", "description": "Uoppgitt"}, qualifier="00.000")
        s = build_summary(ledger, {"accounts": [], "changes": [], "missing": [], "today": "2026-10-22"})
        self.assertEqual(s["parts"]["overview"][0], "S. M. N. INVEST AS is a private limited company.")
        self.assertIn("The register gives no industry for it (NACE 00.000, “Uoppgitt”).", s["parts"]["what_it_does"])


class UnknownTests(unittest.TestCase):
    def test_each_gap_has_its_state_and_reason_and_never_names_the_other_company(self):
        ledger = SummaryV2Tests().build()
        discovery = [{"url": "https://www.usbl.no", "source": "registry_website", "outcome": "related", "reason": "site shows another organisation number (950285680)"},
                     {"url": "https://wyssen.no", "source": "domain_guess_from_legal_name", "outcome": "rejected", "reason": "no identity proof"}]
        s = build_summary(ledger, {"accounts": [], "changes": [], "missing": ["website", "profiles", "hiring", "activity"], "today": "2026-10-22",
                                   "states": {"website": "ambiguous", "hiring": "failed"},
                                   "notes": {"website": "https://www.usbl.no: site shows another organisation number (950285680)",
                                             "hiring": "NAV job feed unavailable: HTTP 503"},
                                   "discovery": discovery})
        unknown = s["parts"]["unknown"]
        self.assertTrue(unknown[0].startswith("Ambiguous: a verified website (a candidate site prints another organisation number"))
        self.assertIn("2 candidate sites checked: the website listed in the register and domains named after the company", unknown[0])
        self.assertNotIn("usbl", " ".join(unknown))
        self.assertNotIn("950285680", " ".join(unknown))
        self.assertTrue(any(u.startswith("Could not be checked in this run: active job ads (NAV job feed unavailable: HTTP 503)") for u in unknown))
        self.assertEqual(s["dropped_unsupported_sentences"], 0)


class SplitViewerTests(unittest.TestCase):
    def envelope(self, org: str, name: str) -> dict:
        ledger = SummaryV2Tests().build()
        summary = build_summary(ledger, {"accounts": [], "changes": [], "missing": [], "today": "2026-10-22"})
        claims = [dict(c) for c in ledger.claims]
        claims[0]["display"] = "</script><script>alert(1)</script>"
        return {"organisation_number": org, "legal_name": name, "status": "available",
                "sections": {"identity": {"state": "available", "claims": 3}, "website": {"state": "blocked", "note": "robots.txt"}},
                "summary": summary, "claims": claims, "evidence": list(ledger.evidence.values()), "changes": [],
                "run": {"run_id": "r", "completed_at": "2026-10-22T10:00:00Z"}, "errors": []}

    def test_large_batches_write_one_profile_file_per_company(self):
        envs = [self.envelope(ORG, "WYSSEN NORGE AS"), self.envelope("not-a-number", "ODD INPUT")]
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp, "data")
            stale.mkdir()
            Path(stale, "123456789.js").write_text("old", encoding="utf-8")
            Path(stale, "keep-me.txt").write_text("not ours", encoding="utf-8")
            page = build_site(envs, Path(tmp), inline_limit=0).read_text(encoding="utf-8")
            files = sorted(p.name for p in stale.iterdir())
            body = Path(stale, f"{ORG}.js").read_text(encoding="utf-8")
        data = json.loads(page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertNotIn("details", data)
        self.assertEqual(data["meta"]["profiles"], "files")
        self.assertEqual(data["companies"][0]["f"], ORG)
        self.assertTrue(re.fullmatch(r"x[0-9a-f]{12}", data["companies"][1]["f"]))
        self.assertIn("keep-me.txt", files)          # only our own stale profile files are removed
        self.assertNotIn("123456789.js", files)
        self.assertEqual(len([f for f in files if f.endswith(".js")]), 2)
        self.assertTrue(body.startswith(f'SP_DETAIL("{ORG}",{{'))
        detail = json.loads(body[len(f'SP_DETAIL("{ORG}",'):].rstrip().rstrip(";").rstrip(")"))
        self.assertEqual(detail["o"], ORG)
        self.assertTrue(detail["sum"] and detail["dc"])
        self.assertEqual(data["companies"][0]["s"][3], "b")  # website: blocked, kept in the index for the cards and filters

    def test_small_batches_stay_one_file_and_markup_in_data_is_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = build_site([self.envelope(ORG, "WYSSEN NORGE AS")], Path(tmp)).read_text(encoding="utf-8")
            self.assertFalse(Path(tmp, "data").exists())
        self.assertNotIn("<script>alert(1)", page)
        data = json.loads(page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertEqual(data["meta"]["profiles"], "inline")
        self.assertEqual(data["details"][ORG]["cl"][0]["d"], "</script><script>alert(1)</script>")


if __name__ == "__main__":
    unittest.main()
