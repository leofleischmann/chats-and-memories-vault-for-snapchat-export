from __future__ import annotations

import json
import os
from typing import Any, Literal, TypedDict

from .importer import parse_utc_timestamp


class InsightsEngagement(TypedDict):
    event: str
    occurrences: int


class InsightsTimeSpent(TypedDict):
    area: str
    percent: float


class InsightsInterest(TypedDict):
    category: str
    kind: Literal["interest", "content"]


class InsightsDeviceHistory(TypedDict, total=False):
    start_ts: str | None
    make: Any
    model: Any
    device_type: Any


class InsightsLoginHistory(TypedDict, total=False):
    created_ts: str | None
    ip: Any
    country: Any
    status: Any
    device: Any


class InsightsAccountHistory(TypedDict):
    section: str
    created_ts: str | None
    value: str


class InsightsSnapshot(TypedDict):
    meta: dict[str, str]
    engagement: list[InsightsEngagement]
    time_spent: list[InsightsTimeSpent]
    interests: list[InsightsInterest]
    web_interactions: list[str]
    ranking: dict[str, str]
    device_history: list[InsightsDeviceHistory]
    login_history: list[InsightsLoginHistory]
    account_history: list[InsightsAccountHistory]


def _safe_read_json(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _normalize_ts(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # Common snapchat export format: "YYYY-MM-DD HH:MM:SS UTC"
    utc = parse_utc_timestamp(s)
    if utc:
        return utc
    # Some sources are already ISO-ish
    if "T" in s and ("Z" in s or "+" in s):
        return s
    return s


def _parse_percent_line(line: str) -> tuple[str, float] | None:
    # Example: "Messaging: 50.57%"
    if not line or ":" not in line:
        return None
    area, rest = line.split(":", 1)
    area = area.strip()
    rest = rest.strip().replace("%", "")
    if not area or not rest:
        return None
    try:
        return area, float(rest)
    except ValueError:
        return None


def build_insights_snapshot(export_root: str) -> dict[str, Any]:
    """Build a single snapshot from various snapchat export JSON files.

    Returned format matches Storage.replace_insights_snapshot().
    """
    user_profile = _safe_read_json(os.path.join(export_root, "json", "user_profile.json"))
    ranking = _safe_read_json(os.path.join(export_root, "json", "ranking.json"))
    account = _safe_read_json(os.path.join(export_root, "json", "account.json"))
    account_history = _safe_read_json(os.path.join(export_root, "json", "account_history.json"))

    out: InsightsSnapshot = {
        "meta": {},
        "engagement": [],
        "time_spent": [],
        "interests": [],
        "web_interactions": [],
        "ranking": {},
        "device_history": [],
        "login_history": [],
        "account_history": [],
    }

    # --- user_profile.json ---
    if user_profile:
        app_profile = user_profile.get("App Profile") or {}
        if isinstance(app_profile, dict):
            for k in ("Country", "Creation Time", "In-app Language", "Platform Version"):
                v = app_profile.get(k)
                if v:
                    out["meta"][f"user_profile.{k}"] = str(v)

        engagement = user_profile.get("Engagement") or []
        if isinstance(engagement, list):
            for e in engagement:
                if not isinstance(e, dict):
                    continue
                event = (e.get("Event") or "").strip()
                if not event:
                    continue
                occ = e.get("Occurrences")
                try:
                    occurrences = int(occ or 0)
                except Exception:
                    occurrences = 0
                out["engagement"].append({"event": event, "occurrences": occurrences})

        time_spent = user_profile.get("Breakdown of Time Spent on App") or []
        if isinstance(time_spent, list):
            for line in time_spent:
                parsed = _parse_percent_line(str(line))
                if parsed:
                    area, pct = parsed
                    out["time_spent"].append({"area": area, "percent": pct})

        for cat in user_profile.get("Interest Categories") or []:
            s = str(cat).strip()
            if s:
                out["interests"].append({"category": s, "kind": "interest"})

        for cat in user_profile.get("Content Categories") or []:
            s = str(cat).strip()
            if s:
                out["interests"].append({"category": s, "kind": "content"})

        interactions = user_profile.get("Interactions") or {}
        if isinstance(interactions, dict):
            web = interactions.get("Web Interactions") or []
            if isinstance(web, list):
                out["web_interactions"] = [str(d).strip() for d in web if str(d).strip()]

    # --- ranking.json ---
    if ranking:
        stats = ranking.get("Statistics") or {}
        if isinstance(stats, dict):
            for k, v in stats.items():
                if v is None:
                    continue
                out["ranking"][str(k)] = str(v)

    # --- account.json ---
    if account:
        basic = account.get("Basic Information") or {}
        if isinstance(basic, dict):
            for k in ("Username", "Name", "Creation Date", "Country", "Last Active"):
                v = basic.get(k)
                if v:
                    out["meta"][f"account.{k}"] = str(v)

        dev = account.get("Device Information") or {}
        if isinstance(dev, dict):
            for k in ("Make", "Model ID", "Model Name", "Language", "OS Type", "OS Version", "Connection Type"):
                v = dev.get(k)
                if v:
                    out["meta"][f"device.{k}"] = str(v)

        dev_hist = account.get("Device History") or []
        if isinstance(dev_hist, list):
            for d in dev_hist:
                if not isinstance(d, dict):
                    continue
                out["device_history"].append(
                    {
                        "start_ts": _normalize_ts(d.get("Start Time")),
                        "make": d.get("Make"),
                        "model": d.get("Model"),
                        "device_type": d.get("Device Type"),
                    }
                )

        login_hist = account.get("Login History") or []
        if isinstance(login_hist, list):
            for l in login_hist:
                if not isinstance(l, dict):
                    continue
                out["login_history"].append(
                    {
                        "created_ts": _normalize_ts(l.get("Created")),
                        "ip": l.get("IP"),
                        "country": l.get("Country"),
                        "status": l.get("Status"),
                        "device": l.get("Device"),
                    }
                )

    # --- account_history.json (flex timeline) ---
    if account_history:
        for section, entries in account_history.items():
            if not isinstance(entries, list):
                continue
            section_name = str(section).strip() or "unknown"
            for e in entries:
                if not isinstance(e, dict):
                    continue
                ts = _normalize_ts(e.get("Date"))
                # Prefer common value keys, otherwise JSON dump of remaining keys.
                value = None
                for key in ("Display Name", "Email Address", "Mobile Number", "Event", "Status"):
                    if e.get(key):
                        value = str(e.get(key))
                        break
                if value is None:
                    payload = {k: v for k, v in e.items() if k != "Date" and v is not None}
                    value = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload else ""
                if value:
                    out["account_history"].append({"section": section_name, "created_ts": ts, "value": value})

    # Normalize ordering a bit for stable UI.
    out["engagement"].sort(key=lambda x: (-int(x.get("occurrences") or 0), str(x.get("event") or "")))
    out["time_spent"].sort(key=lambda x: (-float(x.get("percent") or 0.0), str(x.get("area") or "")))
    out["web_interactions"] = sorted(set(out["web_interactions"]))

    return out

