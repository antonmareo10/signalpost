"""Refresh as a diff: compare this run's verified claims with the previous envelope for the same company.

* Claims have stable keys (``field|qualifier``) so re-running on the same snapshot yields no changes.
* A section that failed or was blocked this run keeps the previous supported values (marked
  ``carried_forward``) and never produces "removed" events.
* Each change cites the claim ids on both sides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MULTI = {"role": ("new_role", "removed_role"), "workplace": ("new_location", "closed_location"),
         "job_posting": ("new_job", "closed_job"), "social_profile": ("new_profile", "removed_profile"),
         "website_post": ("new_post", None), "accounting_period": ("new_filing", None), "group_subsidiary": ("new_subsidiary", "removed_subsidiary"),
         "careers_page": ("new_careers_page", "removed_careers_page"), "former_name": ("name_history_added", None),
         "registry_role_change": ("role_register_updated", None), "secondary_industry": ("industry_added", "industry_removed"),
         "registry_update": ("register_event", None), "employees_history": ("employee_count_event", None),
         "accounts_filed_event": ("filing_event", None), "annual_accounts_copy": ("new_accounts_document", None),
         "industry_en": ("industry_label_added", "industry_label_removed"),
         "secondary_industry_en": ("industry_label_added", "industry_label_removed")}
HIGH = {"legal_name", "business_address", "official_website", "bankrupt", "under_liquidation", "forced_dissolution", "group_parent",
        "accounting_period", "legal_form"}
HIGH_ROLES = {"DAGL", "LEDE"}
IGNORE = {"website_identity_proof", "website_email"}


def load_previous(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    out = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["organisation_number"]] = row
    return out


def latest_history(history_dir: str | Path | None, current_run_id: str) -> Path | None:
    if not history_dir:
        return None
    folder = Path(history_dir)
    if not folder.exists():
        return None
    runs = sorted((p for p in folder.glob("*.jsonl") if p.stem != current_run_id), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


def _display(claim: dict[str, Any]) -> str:
    value = claim.get("display") or claim.get("value")
    return str(value if not isinstance(value, dict) else value.get("title") or value.get("name") or value)[:160]


def diff(current: dict[str, Any], previous: dict[str, Any] | None, failed_sections: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (changes, carried_forward_claims)."""
    if not previous:
        return [], []
    prev_claims = [c for c in previous.get("claims", []) if not c.get("carried_forward_from")]
    prev_claims += [c for c in previous.get("claims", []) if c.get("carried_forward_from")]
    cur_by_key: dict[str, list[dict[str, Any]]] = {}
    for claim in current["claims"]:
        cur_by_key.setdefault(claim["key"], []).append(claim)
    prev_by_key: dict[str, list[dict[str, Any]]] = {}
    for claim in prev_claims:
        prev_by_key.setdefault(claim["key"], []).append(claim)
    changes: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    run_id = previous.get("run", {}).get("run_id")
    observed = previous.get("run", {}).get("completed_at")
    for key, olds in prev_by_key.items():
        old = olds[0]
        field = old["field"]
        if field in IGNORE:
            continue
        news = cur_by_key.get(key)
        if not news:
            if old["section"] in failed_sections:
                keep = dict(old)
                keep["carried_forward_from"] = run_id
                keep["last_observed_at"] = old.get("last_observed_at") or observed
                carried.append(keep)
                continue
            kinds = MULTI.get(field)
            if kinds and kinds[1]:
                changes.append(_change(kinds[1], field, old, None, _materiality(field, old)))
            elif not kinds:
                changes.append(_change("value_removed", field, old, None, _materiality(field, old)))
            continue
        new = news[0]
        if json.dumps(new["value"], sort_keys=True, ensure_ascii=False) != json.dumps(old["value"], sort_keys=True, ensure_ascii=False):
            kind = "changed_description" if field == "website_description" else "website_changed" if field == "official_website" else "changed_value"
            changes.append(_change(kind, field, old, new, _materiality(field, new)))
    for key, news in cur_by_key.items():
        if key in prev_by_key:
            continue
        new = news[0]
        field = new["field"]
        if field in IGNORE:
            continue
        kinds = MULTI.get(field)
        if kinds:
            changes.append(_change(kinds[0], field, None, new, _materiality(field, new)))
        else:
            changes.append(_change("value_added", field, None, new, _materiality(field, new)))
    return changes, carried


def _materiality(field: str, claim: dict[str, Any]) -> str:
    if field in HIGH or (field == "role" and claim.get("role_code") in HIGH_ROLES):
        return "high"
    if field in {"role", "workplace", "job_posting", "employees_registered", "revenue", "net_result", "equity", "share_capital",
                 "social_profile", "careers_page", "public_brand", "group_subsidiary"}:
        return "medium"
    return "low"


def _change(kind: str, field: str, old: dict[str, Any] | None, new: dict[str, Any] | None, materiality: str) -> dict[str, Any]:
    if old and new:
        description = f"{field.replace('_', ' ')} changed from {_display(old)} to {_display(new)}"
    elif new:
        description = f"{kind.replace('_', ' ')}: {_display(new)}"
    else:
        description = f"{kind.replace('_', ' ')}: {_display(old)}"
    return {"type": kind, "field": field, "materiality": materiality, "description": description,
            "previous": {"claim_id": old["id"], "value": old["value"], "evidence_ids": old.get("evidence_ids", [])} if old else None,
            "current": {"claim_id": new["id"], "value": new["value"], "evidence_ids": new.get("evidence_ids", [])} if new else None,
            "claim_ids": [c["id"] for c in (old, new) if c]}
