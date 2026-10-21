"""Download Builderr's public 100-company product sample (https://builderr.ai/signalpost) as a reference set.

The page embeds the profiles produced by Builderr's own reference crawler. We keep only what is needed to
measure overlap: organisation number, verified website domain and company-owned social handles.

    python eval/builderr_reference.py --out eval/reference/builderr-sample-100.json --orgs samples/builderr-sample-100.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signalpost.web import normalize_social, registrable, host_of  # noqa: E402

URL = "https://builderr.ai/signalpost"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="eval/reference/builderr-sample-100.json")
    parser.add_argument("--orgs", default="samples/builderr-sample-100.jsonl")
    args = parser.parse_args()
    request = urllib.request.Request(URL, headers={"User-Agent": "SignalpostResearchAgent/1.0 (evaluation)"})
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8")
    script = re.search(r"const DATA=", html)
    if not script:
        raise SystemExit("DATA block not found on the sample page")
    data, _ = json.JSONDecoder().raw_decode(html[script.end():])
    rows = []
    for item in data:
        web = item.get("web") or {}
        value = web.get("value") or {}
        website = registrable(host_of(value.get("final_url") or "")) if web.get("status") == "available" and value.get("final_url") else None
        handles = []
        for handle in (item.get("external") or {}).get("handles") or []:
            normalized = normalize_social(handle.get("url") or "")
            if normalized:
                handles.append({"platform": normalized[0], "url": normalized[1].lower(), "rights": handle.get("rightsStatus")})
        linkedin = (item.get("external") or {}).get("linkedin") or {}
        rows.append({"organisation_number": item["org"], "name": item.get("name"), "website": website, "handles": handles,
                     "linkedin_experimental": bool(linkedin.get("available")), "linkedin_posts": len(linkedin.get("posts") or []),
                     "linkedin_jobs": len(linkedin.get("jobs") or [])})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": URL, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.orgs).write_text("".join(json.dumps({"organisation_number": r["organisation_number"]}) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} reference companies -> {out}")


if __name__ == "__main__":
    main()
