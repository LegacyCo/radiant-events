#!/usr/bin/env python3
"""
Church Center events -> website events feed

Pulls events (upcoming and historical) from one of two sources, attaches the
Church Center registration link for each event, and writes static feed files a
Squarespace Code Block can render.

  --source pco   Planning Center Calendar API. Needs a Personal Access Token.
  --source churchcenter
                 Church Center's public calendar + registrations, the same data
                 <subdomain>.churchcenter.com shows visitors. No keys needed, and
                 only events the church published to Church Center come through.
  --source ics   Any public calendar feed (Google Calendar, etc.) plus Church
                 Center's public registrations. No keys needed.
                 Needs: pip install icalendar recurring-ical-events

Output:

  events.json      feed for squarespace-events-embed.html
  events.ics       iCal feed (Google Calendar, Apple Calendar, Outlook)
  events.rss.xml   RSS 2.0 feed (Zapier / Make "new item" triggers)
  changes.json     what was added / updated / removed since the previous run,
                   plus warnings about Register links that look missing

Squarespace has no public API for Events collection items, so this script
never writes to Squarespace directly. See README.md for the full strategy.

PCO auth: Personal Access Token (https://api.planningcenteronline.com/oauth/applications)
  export PCO_APP_ID=...   export PCO_SECRET=...

PCO mode is standard library only. Python 3.9+.
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from difflib import SequenceMatcher
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

API_BASE = "https://api.planningcenteronline.com"
USER_AGENT = "legacy-church-events-sync/1.0"
MAX_RETRIES = 5

# Name matching between calendar events and registrations (ICS mode).
REG_MATCH_STRONG = 0.85        # name similarity that counts as the same event
REG_DATE_TOLERANCE_DAYS = 2    # event date must fall within the signup's dates, give or take
WARN_MATCH = 0.8               # similarity that's worth a "missing Register link?" warning


# ── Planning Center client ────────────────────────────────────────────────

class PCOClient:
    def __init__(self, app_id: str, secret: str, verbose: bool = False):
        token = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self.verbose = verbose
        self.base = API_BASE

    def get(self, url: str) -> dict:
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                # PCO allows 100 requests per 20 seconds; back off when told to.
                if e.code == 429 or e.code >= 500:
                    wait = int(e.headers.get("Retry-After", 2 ** attempt))
                    self._log(f"HTTP {e.code}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                body = e.read().decode(errors="replace")[:500]
                raise PCOError(e.code, url, body) from None
        raise PCOError(429, url, "gave up after repeated rate limiting")

    def paginate(self, path: str, params: dict) -> tuple[list, list]:
        """Follow links.next and return (data, included) across all pages."""
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        data, included = [], []
        while url:
            self._log(f"GET {url}")
            page = self.get(url)
            data.extend(page.get("data", []))
            included.extend(page.get("included", []))
            url = (page.get("links") or {}).get("next")
        return data, included

    def _log(self, msg: str):
        if self.verbose:
            print(f"  · {msg}", file=sys.stderr)


class ChurchCenterClient(PCOClient):
    """Church Center's public API, with the anonymous visitor token the Church
    Center website itself uses. It only sees what the church published there."""

    def __init__(self, subdomain: str, verbose: bool = False):
        origin = f"https://{subdomain}.churchcenter.com"
        tok = json.loads(http_get(f"{origin}/sessions/tokens", data=b"{}", headers={
            "Origin": origin, "Accept": "application/json", "Content-Type": "application/json"}))
        self.headers = {
            "Authorization": f"Bearer {tok['data']['attributes']['token']}",
            "Origin": origin,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self.verbose = verbose
        self.base = "https://api.churchcenter.com"


class PCOError(Exception):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"Planning Center returned HTTP {status} for {url}\n{body}")
        self.status = status


# ── Fetching ──────────────────────────────────────────────────────────────

def fetch_event_instances(client: PCOClient, since: datetime, until: datetime):
    params = {
        "include": "event",
        "order": "starts_at",
        "per_page": 100,
        "where[starts_at][gte]": iso_z(since),
        "where[starts_at][lte]": iso_z(until),
    }
    try:
        instances, included = client.paginate("/calendar/v2/event_instances", params)
    except PCOError as e:
        if e.status != 400:
            raise
        # Church Center's public API may not take date filters. Pull everything, filter below.
        params = {k: v for k, v in params.items() if not k.startswith("where[")}
        instances, included = client.paginate("/calendar/v2/event_instances", params)
    lo, hi = iso_z(since), iso_z(until)
    instances = [i for i in instances if lo <= iso_z(parse_ts((i.get("attributes") or {}).get("starts_at"))
                                                     or since) <= hi]
    events = {i["id"]: i for i in included if i.get("type") == "Event"}
    return instances, events


def fetch_pco_registrations(client: PCOClient, subdomain: str = None) -> list:
    """Registrations (active and archived), normalized. Planning Center calls
    them "events" now and "signups" in older accounts, so try both. Empty list
    if the token has no Registrations access, so Calendar-only churches still sync."""
    last_status = None
    for path in ("/registrations/v2/events", "/registrations/v2/signups"):
        try:
            items, _ = client.paginate(path, {"per_page": 100})
            return [reg_from_item(i, subdomain) for i in items]
        except PCOError as e:
            if e.status not in (401, 403, 404):
                raise
            last_status = e.status
    print(f"⚠️  Skipping Registrations lookup (HTTP {last_status}). "
          "Calendar registration links will still be used.", file=sys.stderr)
    return []


def reg_from_item(item: dict, subdomain: str = None) -> dict:
    """One registration in a shape both sources share."""
    a = item.get("attributes") or {}
    # public_url is the registration's event page; new_registration_url jumps straight into the form.
    url = a.get("public_url") or a.get("new_registration_url") or a.get("registration_url")
    if not url and subdomain and item.get("id"):
        url = f"https://{subdomain}.churchcenter.com/registrations/events/{item['id']}"
    return {
        "id": str(item.get("id") or ""),
        "name": a.get("name") or "",
        "url": url,
        "start": parse_ts(a.get("starts_at")),
        "end": parse_ts(a.get("ends_at")),
        "archived": bool(a.get("archived") or a.get("archived_at")),
        "image": a.get("logo_url") or "",
        "description": a.get("stripped_description") or strip_html(a.get("description")),
        # Listed publicly, not a hidden link-only signup.
        "listed": a.get("listed", True) is not False and not a.get("link_only") and not a.get("direct_link_only")
        and a.get("visibility", "public") == "public",
    }


# ── Public sources (no keys) ──────────────────────────────────────────────

def http_get(url: str, headers: dict = None, data: bytes = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_public_registrations(subdomain: str) -> list:
    """Church Center's public registrations, via the same anonymous token the
    Church Center website uses. Unofficial, so a failure only costs Register
    links for one run, never the whole sync."""
    origin = f"https://{subdomain}.churchcenter.com"
    headers = {"Origin": origin, "Accept": "application/json"}
    try:
        tok = json.loads(http_get(f"{origin}/sessions/tokens", data=b"{}",
                                  headers={**headers, "Content-Type": "application/json"}))
        auth = {**headers, "Authorization": f"Bearer {tok['data']['attributes']['token']}"}
        url = "https://api.churchcenter.com/registrations/v2/events?" + urllib.parse.urlencode(
            {"order": "starts_at", "filter": "unarchived,published", "per_page": 100})
        regs = []
        while url:
            page = json.loads(http_get(url, headers=auth))
            regs += [reg_from_item(i, subdomain) for i in page.get("data", [])]
            url = (page.get("links") or {}).get("next")
        return regs
    except Exception as e:
        print(f"⚠️  Couldn't read Church Center registrations ({e}). "
              "Register links will be missing this run.", file=sys.stderr)
        return []


# ── Normalizing ───────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def strip_html(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_signup_index(regs: list) -> dict:
    """Map normalized registration name -> Church Center registration URL.
    Active registrations win over archived ones with the same name."""
    index = {}
    for r in sorted(regs, key=lambda r: r["archived"]):
        key = normalize_name(r["name"])
        if r["url"] and key and key not in index:
            index[key] = r["url"]
    return index


def registration_warnings(feed: list, regs: list) -> list:
    """Spot Register links that are probably missing or ambiguous, so a name
    mismatch between the calendar and Registrations shows up on the next run."""
    active = [(normalize_name(r["name"]), r["name"]) for r in regs
              if r["url"] and normalize_name(r["name"]) and not r["archived"]]

    warnings, by_key = [], {}
    for key, name in active:
        by_key.setdefault(key, []).append(name)
    for names in by_key.values():
        if len(names) > 1:
            warnings.append(f'{len(names)} open signups are named "{names[0]}". '
                            "Events with that name may link to the wrong one.")

    seen = set()
    for e in feed:
        if e["status"] != "upcoming" or e["registration_url"] or e["event_id"] in seen:
            continue
        seen.add(e["event_id"])
        key = normalize_name(e["title"])
        if not key:
            continue
        for skey, name in active:
            if skey in key or key in skey or SequenceMatcher(None, key, skey).ratio() >= WARN_MATCH:
                title = e["title"]
                warnings.append(f'"{title}" has no Register link, but signup "{name}" looks like a match. '
                                "Attach the signup to the event, or match the names.")
                break
    return warnings


def build_feed(instances, events, signup_index, tz: ZoneInfo, now: datetime,
               include_hidden=False, include_unapproved=False, regs=None, subdomain=None) -> list:
    feed = []
    for inst in instances:
        ia = inst.get("attributes") or {}
        event_id = (((inst.get("relationships") or {}).get("event") or {}).get("data") or {}).get("id")
        ev = events.get(event_id) or {}
        ea = ev.get("attributes") or {}

        if not include_hidden and ea.get("visible_in_church_center") is False:
            continue
        # A = approved, P = pending, R = rejected
        if not include_unapproved and ea.get("approval_status") not in (None, "A"):
            continue

        # Church Center shows the "published" times when an event has setup/teardown padding.
        start = parse_ts(ia.get("published_starts_at") or ia.get("starts_at"))
        end = parse_ts(ia.get("published_ends_at") or ia.get("ends_at")) or start
        if not start:
            continue

        all_day = bool(ia.get("all_day_event"))
        local_start, local_end = start.astimezone(tz), end.astimezone(tz)

        linked = CC_REG_LINK.search(ea.get("description") or "")
        registration_url = (
            ea.get("registration_url")
            or (linked.group(0) if linked else None)
            or signup_index.get(normalize_name(ea.get("name")))
            or (match_registration(ea.get("name") or "", start, regs) if regs else None)
        )

        feed.append({
            "id": inst["id"],
            "event_id": event_id,
            "title": ea.get("name") or ia.get("name") or "Untitled event",
            "summary": strip_html(ea.get("summary")),
            "description": clean_description(ea.get("description")),
            "description_html": ea.get("description") or "",
            "start": iso_z(start),
            "end": iso_z(end),
            "start_local": local_start.isoformat(),
            "end_local": local_end.isoformat(),
            "all_day": all_day,
            "location": ia.get("location") or "",
            "recurrence": ia.get("recurrence_description") or ia.get("compact_recurrence_description") or "",
            "image": ea.get("image_url") or "",
            "featured": bool(ea.get("featured")),
            "registration_url": registration_url,
            "details_url": ia.get("church_center_url")
            or (f"https://{subdomain}.churchcenter.com/calendar/event/{inst['id']}" if subdomain else ""),
            "status": "upcoming" if end >= now else "past",
            "updated_at": ea.get("updated_at") or "",
        })
    feed.sort(key=lambda e: e["start"])
    return feed


# ── Church Center source ──────────────────────────────────────────────────
#
# api.churchcenter.com/calendar/v2/events lists one item per occurrence (a
# weekly event shows up once per week), grouped by event_group. Location comes
# from include=location. Shape confirmed against Radiant's live calendar.

def fetch_church_center_events(client: PCOClient, since: datetime, until: datetime):
    params = {
        "include": "location",
        "per_page": 100,
        "where[starts_at][gte]": iso_z(since),
        "where[starts_at][lte]": iso_z(until),
    }
    items, included = client.paginate("/calendar/v2/events", params)
    lo, hi = iso_z(since), iso_z(until)
    items = [i for i in items if lo <= iso_z(parse_ts((i.get("attributes") or {}).get("starts_at")) or since) <= hi]
    locations = {i["id"]: i.get("attributes") or {} for i in included if i.get("type") == "Location"}
    return items, locations


def format_location(loc: dict) -> str:
    if not loc or loc.get("display_on_church_center") is False:
        return ""
    name = (loc.get("name") or "").strip()
    address = ", ".join(line.strip() for line in (loc.get("full_formatted_address") or "").splitlines() if line.strip())
    if name and address and not address.startswith(name):
        return f"{name} - {address}"
    return address or name


def build_feed_from_church_center(items: list, locations: dict, regs: list, tz: ZoneInfo, now: datetime) -> list:
    feed = []
    for item in items:
        a = item.get("attributes") or {}
        start = parse_ts(a.get("starts_at"))
        if not start:
            continue
        end = parse_ts(a.get("ends_at")) or start
        title = (a.get("name") or "Untitled event").strip()
        description_html = a.get("description") or ""
        linked = CC_REG_LINK.search(description_html)
        reg = find_registration(title, start, regs)
        loc_id = ((((item.get("relationships") or {}).get("location") or {}).get("data")) or {}).get("id")

        feed.append({
            "id": str(item["id"]),
            "event_id": str(a.get("event_group") or item["id"]),
            "title": title,
            "summary": "",
            "description": clean_description(description_html),
            "description_html": description_html,
            "start": iso_z(start),
            "end": iso_z(end),
            "start_local": start.astimezone(tz).isoformat(),
            "end_local": end.astimezone(tz).isoformat(),
            "all_day": bool(a.get("all_day_event")),
            "location": format_location(locations.get(loc_id)),
            "recurrence": (a.get("recurrence_description") or "") if a.get("recurring") else "",
            "image": a.get("image_url") or (reg or {}).get("image") or "",
            "featured": bool(a.get("featured")),
            "registration_url": linked.group(0) if linked else (reg or {}).get("url"),
            "details_url": a.get("public_url") or "",
            "status": "upcoming" if end >= now else "past",
            "updated_at": "",
        })
    feed.sort(key=lambda e: e["start"])
    return feed


def add_registration_only_events(feed: list, regs: list, tz: ZoneInfo, now: datetime,
                                 since: datetime, until: datetime) -> list:
    """Public registrations with no calendar event (a breakfast that only lives in
    Registrations) still belong on the website. Skip any a calendar event covers."""
    used = {e["registration_url"] for e in feed if e["registration_url"]}
    added = []
    for r in regs:
        if r["archived"] or not r["listed"] or not r["url"] or not r["start"] or r["url"] in used:
            continue
        if not (since <= r["start"] <= until):
            continue
        key = normalize_name(r["name"])
        near = [e for e in feed if abs((parse_ts(e["start"]) - r["start"]).total_seconds()) <= 2 * 86400]
        if any(key and (key in normalize_name(e["title"]) or normalize_name(e["title"]) in key
                        or SequenceMatcher(None, key, normalize_name(e["title"])).ratio() >= 0.6) for e in near):
            continue
        end = r["end"] or r["start"]
        added.append({
            "id": f"reg-{r['id']}",
            "event_id": f"reg-{r['id']}",
            "title": r["name"],
            "summary": "",
            "description": r["description"],
            "description_html": "",
            "start": iso_z(r["start"]),
            "end": iso_z(end),
            "start_local": r["start"].astimezone(tz).isoformat(),
            "end_local": end.astimezone(tz).isoformat(),
            "all_day": False,
            "location": "",
            "recurrence": "",
            "image": r["image"],
            "featured": False,
            "registration_url": r["url"],
            "details_url": "",
            "status": "upcoming" if end >= now else "past",
            "updated_at": "",
        })
    return sorted(feed + added, key=lambda e: e["start"])


# ── ICS source ────────────────────────────────────────────────────────────

RRULE_DAYS = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
              "FR": "Friday", "SA": "Saturday", "SU": "Sunday"}
CC_REG_LINK = re.compile(r"https://[a-z0-9-]+\.churchcenter\.com/registrations/events/\d+", re.I)
# The link plus a "Register:" / "Sign up here:" / "Inscríbete:" label in front of it, if any.
REG_LABEL_AND_LINK = re.compile(
    r"(?:\b(?:register|registration|sign[\s-]?up|rsvp|inscr[ií]bete|inscripci[oó]n|reg[ií]strate)"
    r"(?:\s+(?:here|now|aqu[ií]))?\s*[:\-]?\s*)?" + CC_REG_LINK.pattern, re.I)


def describe_rrule(rrule) -> str:
    freq = str((rrule.get("FREQ") or [""])[0]).upper()
    interval = int((rrule.get("INTERVAL") or [1])[0])
    unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}.get(freq)
    if not unit:
        return "Repeats"
    text = {"day": "Daily", "week": "Weekly", "month": "Monthly", "year": "Yearly"}[unit] \
        if interval == 1 else f"Every {interval} {unit}s"
    days = [RRULE_DAYS[str(d)[-2:]] for d in rrule.get("BYDAY", []) if str(d)[-2:] in RRULE_DAYS]
    if unit == "week" and days:
        text += " on " + " & ".join(days)
    return text


def to_local(value, tz: ZoneInfo) -> datetime:
    # Floating times (no timezone in the feed) are the church's local time.
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


def match_registration(title: str, start: datetime, regs: list):
    """URL of the registration for a calendar event, or None."""
    reg = find_registration(title, start, regs)
    return reg["url"] if reg else None


def find_registration(title: str, start: datetime, regs: list):
    """Best registration for a calendar event by name, checked against dates so
    a one-off signup doesn't attach to every week of a recurring event."""
    key = normalize_name(title)
    best, best_ratio = None, 0.0
    for r in regs:
        if r["archived"] or not r["url"]:
            continue
        ratio = SequenceMatcher(None, key, normalize_name(r["name"])).ratio()
        if ratio > best_ratio:
            best, best_ratio = r, ratio
    if not best or best_ratio < REG_MATCH_STRONG:
        return None
    if best["start"]:
        slack = timedelta(days=REG_DATE_TOLERANCE_DAYS)
        first = best["start"] - slack
        last = (best["end"] or best["start"]) + slack
        if not (first <= start <= last):
            return None
    return best


def clean_description(description_html) -> str:
    """Plain text without registration links (the Register button covers them)
    or the "Sign up:" labels they leave behind."""
    text = REG_LABEL_AND_LINK.sub("", strip_html(description_html))
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    text = re.sub(r"[^\S\n]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_feed_from_ics(ics_bytes: bytes, regs: list, tz: ZoneInfo, now: datetime,
                        since: datetime, until: datetime) -> list:
    try:
        import icalendar
        import recurring_ical_events
    except ImportError:
        sys.exit("ICS mode needs two packages: pip install icalendar recurring-ical-events")

    cal = icalendar.Calendar.from_ical(ics_bytes)
    series = {str(c.get("UID")): describe_rrule(c["RRULE"]) for c in cal.walk("VEVENT") if c.get("RRULE")}

    feed = []
    for comp in recurring_ical_events.of(cal).between(since, until):
        if str(comp.get("CLASS", "PUBLIC")).upper() in ("PRIVATE", "CONFIDENTIAL"):
            continue
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        title = str(comp.get("SUMMARY", "")).strip()
        if not title:
            continue

        raw_start = comp["DTSTART"].dt
        raw_end = comp["DTEND"].dt if comp.get("DTEND") else None
        all_day = not isinstance(raw_start, datetime)
        if all_day:
            # DTEND on all-day events is the day after the last day.
            last_day = raw_end - timedelta(days=1) if raw_end and raw_end > raw_start else raw_start
            start = datetime.combine(raw_start, dtime.min, tzinfo=tz)
            end = datetime.combine(last_day, dtime(23, 59), tzinfo=tz)
        else:
            start = to_local(raw_start, tz)
            if raw_end is not None:
                end = to_local(raw_end, tz)
            elif comp.get("DURATION"):
                end = start + comp["DURATION"].dt
            else:
                end = start

        uid = str(comp.get("UID") or title)
        description_html = str(comp.get("DESCRIPTION", ""))
        linked = CC_REG_LINK.search(description_html)
        registration_url = linked.group(0) if linked else match_registration(title, start, regs)
        modified = comp.get("LAST-MODIFIED")

        feed.append({
            "id": hashlib.sha1(f"{uid}|{iso_z(start)}".encode()).hexdigest()[:16],
            "event_id": uid,
            "title": title,
            "summary": "",
            "description": clean_description(description_html),
            "description_html": description_html,
            "start": iso_z(start),
            "end": iso_z(end),
            "start_local": start.isoformat(),
            "end_local": end.isoformat(),
            "all_day": all_day,
            "location": str(comp.get("LOCATION", "")).strip(),
            "recurrence": series.get(uid, ""),
            "image": "",
            "featured": False,
            "registration_url": registration_url,
            "details_url": str(comp.get("URL", "")),
            "status": "upcoming" if end >= now else "past",
            "updated_at": iso_z(modified.dt) if modified and isinstance(modified.dt, datetime) else "",
        })
    feed.sort(key=lambda e: e["start"])
    return feed


def exclude_titles(feed: list, patterns: list) -> list:
    needles = [p.strip().lower() for p in patterns if p.strip()]
    return [e for e in feed if not any(n in e["title"].lower() for n in needles)]


# ── Change detection ──────────────────────────────────────────────────────

CHANGE_FIELDS = ("title", "summary", "start", "end", "all_day", "location",
                 "image", "registration_url", "details_url", "featured")


def diff_feeds(previous: list, current: list, since: str = "") -> dict:
    prev = {e["id"]: e for e in previous}
    curr = {e["id"]: e for e in current}
    added = [curr[i] for i in curr if i not in prev]
    # Events that slid out the back of the history window aren't "removed".
    removed = [prev[i] for i in prev if i not in curr and prev[i]["start"] >= since]
    updated = []
    for i in curr.keys() & prev.keys():
        fields = [f for f in CHANGE_FIELDS if curr[i].get(f) != prev[i].get(f)]
        if fields:
            updated.append({**curr[i], "changed_fields": fields})
    return {"added": added, "updated": updated, "removed": removed}


def load_previous(path_or_url: str) -> list:
    if not path_or_url:
        return []
    try:
        if path_or_url.startswith(("http://", "https://")):
            req = urllib.request.Request(path_or_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp).get("events", [])
        if os.path.exists(path_or_url):
            with open(path_or_url) as f:
                return json.load(f).get("events", [])
    except Exception as e:  # first run, bad JSON, 404: treat as empty
        print(f"⚠️  Could not read previous feed ({e}); treating everything as new.", file=sys.stderr)
    return []


# ── Writers ───────────────────────────────────────────────────────────────

def write_json(path, feed, meta):
    with open(path, "w") as f:
        json.dump({**meta, "count": len(feed), "events": feed}, f, indent=2)


def ics_escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line: str) -> str:
    # RFC 5545: lines over 75 octets continue on the next line with a leading space.
    out, chunk = [], ""
    for ch in line:
        if len((chunk + ch).encode()) > 75:
            out.append(chunk)
            chunk = " " + ch
        else:
            chunk += ch
    out.append(chunk)
    return "\r\n".join(out)


def write_ics(path, feed, cal_name, now):
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Legacy Creative//PCO Events Sync//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(cal_name)}",
    ]
    for e in feed:
        lines += ["BEGIN:VEVENT", f"UID:pco-instance-{e['id']}@churchcenter", f"DTSTAMP:{stamp}"]
        if e["all_day"]:
            start_d = datetime.fromisoformat(e["start_local"]).date()
            end_d = datetime.fromisoformat(e["end_local"]).date() + timedelta(days=1)  # DTEND is exclusive
            lines += [f"DTSTART;VALUE=DATE:{start_d:%Y%m%d}", f"DTEND;VALUE=DATE:{end_d:%Y%m%d}"]
        else:
            lines += [f"DTSTART:{parse_ts(e['start']):%Y%m%dT%H%M%SZ}",
                      f"DTEND:{parse_ts(e['end']):%Y%m%dT%H%M%SZ}"]
        lines.append(f"SUMMARY:{ics_escape(e['title'])}")
        desc = e["summary"] or e["description"]
        if e["registration_url"]:
            desc = f"{desc}\n\nRegister: {e['registration_url']}".strip()
        if desc:
            lines.append(f"DESCRIPTION:{ics_escape(desc)}")
        if e["location"]:
            lines.append(f"LOCATION:{ics_escape(e['location'])}")
        url = e["registration_url"] or e["details_url"]
        if url:
            lines.append(f"URL:{url}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    with open(path, "w", newline="") as f:
        f.write("\r\n".join(ics_fold(l) for l in lines) + "\r\n")


def write_rss(path, feed, cal_name, site_url, now):
    items = []
    for e in feed:
        if e["status"] != "upcoming":
            continue
        link = e["registration_url"] or e["details_url"] or site_url
        when = datetime.fromisoformat(e["start_local"])
        when_txt = when.strftime("%A, %B %-d, %Y") + ("" if e["all_day"] else when.strftime(" at %-I:%M %p"))
        body = f"{when_txt}. {e['location']}\n\n{e['summary'] or e['description']}".strip()
        items.append(
            "    <item>\n"
            f"      <title>{xml_escape(e['title'])}</title>\n"
            f"      <link>{xml_escape(link)}</link>\n"
            f"      <guid isPermaLink=\"false\">pco-instance-{e['id']}</guid>\n"
            f"      <pubDate>{format_datetime(parse_ts(e['start']))}</pubDate>\n"
            f"      <description>{xml_escape(body)}</description>\n"
            + (f"      <enclosure url=\"{xml_escape(e['image'])}\" type=\"image/jpeg\" length=\"0\"/>\n" if e["image"] else "")
            + "    </item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n  <channel>\n'
        f"    <title>{xml_escape(cal_name)}</title>\n"
        f"    <link>{xml_escape(site_url)}</link>\n"
        f"    <description>{xml_escape(cal_name)} from Church Center</description>\n"
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        + "\n".join(items) + "\n  </channel>\n</rss>\n"
    )
    with open(path, "w") as f:
        f.write(xml)


def run_summary(feed: list, changes: dict, warnings: list, count: int = 10) -> str:
    """Markdown for the GitHub Actions run page, so anyone can check a run without opening the feed."""
    upcoming = [e for e in feed if e["status"] == "upcoming"]
    md = [
        "## Events feed",
        f"{len(feed)} events ({len(upcoming)} upcoming, {len(feed) - len(upcoming)} past). "
        f"{sum(1 for e in upcoming if e['image'])} upcoming have an image, "
        f"{sum(1 for e in upcoming if e['registration_url'])} have a Register link.",
        f"Changes since last run: {len(changes['added'])} added, {len(changes['updated'])} updated, "
        f"{len(changes['removed'])} removed.",
        "",
        f"### Next {min(count, len(upcoming))} events",
        "| When | Event | Where | Image | Register |",
        "|---|---|---|---|---|",
    ]
    for e in upcoming[:count]:
        when = datetime.fromisoformat(e["start_local"]).strftime("%a %b %-d, %-I:%M %p")
        title = e["title"].replace("|", "/")
        where = (e["location"] or "").replace("|", "/")
        md.append(f"| {when} | {title} | {where} | {'yes' if e['image'] else ''} | {'yes' if e['registration_url'] else ''} |")
    if warnings:
        md += ["", "### Warnings"] + [f"- {w}" for w in warnings]
    return "\n".join(md) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Sync Church Center events + registration links to a website feed.")
    p.add_argument("--source", choices=("pco", "churchcenter", "ics"), default=os.environ.get("EVENTS_SOURCE") or "pco",
                   help="pco = Planning Center API (needs a token), churchcenter = Church Center's public "
                        "calendar (needs --church-center-subdomain), ics = public calendar feed (default pco)")
    p.add_argument("--ics-url", default=os.environ.get("ICS_URL"), help="Calendar feed URL for --source ics")
    p.add_argument("--church-center-subdomain", default=os.environ.get("CHURCH_CENTER_SUBDOMAIN"),
                   help="e.g. radiantcentralcoast. Builds Register links and enables public registrations")
    p.add_argument("--output-dir", default="./church_events_output", help="Where to write the feed files")
    p.add_argument("--days-back", type=int, default=365, help="Historical window in days (default 365)")
    p.add_argument("--days-ahead", type=int, default=365, help="Future window in days (default 365)")
    p.add_argument("--timezone", default=os.environ.get("PCO_TIMEZONE") or "America/New_York",
                   help="Church timezone, IANA name (default $PCO_TIMEZONE or America/New_York)")
    p.add_argument("--calendar-name", default=os.environ.get("PCO_CALENDAR_NAME") or "Church Events")
    p.add_argument("--site-url", default=os.environ.get("SITE_URL") or "https://example.com/events",
                   help="Your Squarespace events page, used as the RSS channel link")
    p.add_argument("--previous", help="Previous events.json (path or URL) for change detection. "
                                      "Defaults to <output-dir>/events.json")
    p.add_argument("--include-hidden", action="store_true", help="Include events not published to Church Center")
    p.add_argument("--include-unapproved", action="store_true", help="Include pending/rejected events")
    p.add_argument("--skip-registrations", action="store_true", help="Don't query the Registrations API")
    p.add_argument("--exclude-title", action="append", default=[], metavar="TEXT",
                   help="Drop events whose title contains TEXT (any case). Repeatable. "
                        "Also reads EXCLUDE_TITLES, one per line")
    p.add_argument("--min-events", type=int, default=1,
                   help="Refuse to publish a feed with fewer events than this (default 1), so a "
                        "broken source never blanks the website")
    p.add_argument("--dump-raw", action="store_true", help="Also write raw API responses (for debugging field names)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    tz = ZoneInfo(args.timezone)
    now = datetime.now(timezone.utc)
    since, until = now - timedelta(days=args.days_back), now + timedelta(days=args.days_ahead)
    os.makedirs(args.output_dir, exist_ok=True)
    out = lambda name: os.path.join(args.output_dir, name)

    sub = args.church_center_subdomain
    print(f"📅 Fetching events {since:%Y-%m-%d} → {until:%Y-%m-%d} ({args.source})", file=sys.stderr)

    if args.source == "pco":
        app_id, secret = os.environ.get("PCO_APP_ID"), os.environ.get("PCO_SECRET")
        if not app_id or not secret:
            sys.exit("Set PCO_APP_ID and PCO_SECRET (Planning Center Personal Access Token).")
        client = PCOClient(app_id, secret, verbose=args.verbose)
        instances, events = fetch_event_instances(client, since, until)
        regs = [] if args.skip_registrations else fetch_pco_registrations(client, sub)
        print(f"   {len(instances)} instances, {len(events)} events, {len(regs)} registrations", file=sys.stderr)
        raw = {"instances": instances, "events": list(events.values())}
        feed = build_feed(instances, events, build_signup_index(regs), tz, now,
                          include_hidden=args.include_hidden, include_unapproved=args.include_unapproved)
    elif args.source == "churchcenter":
        if not sub:
            sys.exit("Set --church-center-subdomain (or CHURCH_CENTER_SUBDOMAIN) for --source churchcenter.")
        client = ChurchCenterClient(sub, verbose=args.verbose)
        items, locations = fetch_church_center_events(client, since, until)
        regs = [] if args.skip_registrations else fetch_public_registrations(sub)
        print(f"   {len(items)} event dates, {len(regs)} registrations", file=sys.stderr)
        raw = {"events": items, "locations": locations}
        feed = build_feed_from_church_center(items, locations, regs, tz, now)
        feed = add_registration_only_events(feed, regs, tz, now, since, until)
    else:
        if not args.ics_url:
            sys.exit("Set --ics-url (or ICS_URL) for --source ics.")
        ics_bytes = http_get(args.ics_url)
        regs = [] if args.skip_registrations or not sub else fetch_public_registrations(sub)
        raw = {"ics_bytes": len(ics_bytes)}
        feed = build_feed_from_ics(ics_bytes, regs, tz, now, since, until)
        print(f"   {len(feed)} event dates, {len(regs)} registrations", file=sys.stderr)

    if args.dump_raw:
        with open(out("raw_source.json"), "w") as f:
            json.dump({**raw, "registrations": regs}, f, indent=2, default=str)

    excludes = [x for x in args.exclude_title + os.environ.get("EXCLUDE_TITLES", "").splitlines() if x.strip()]
    feed = exclude_titles(feed, excludes)
    if len(feed) < args.min_events:
        sys.exit(f"Only {len(feed)} events came back (minimum {args.min_events}). Not publishing, "
                 "so the website keeps its last good list. Check the source.")

    warnings = registration_warnings(feed, regs)
    for w in warnings:
        print(f"⚠️  {w}", file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning title=Registration link::{w}")  # shows on the Actions run page

    previous = load_previous(args.previous or out("events.json"))
    changes = diff_feeds(previous, feed, since=iso_z(since))

    source = {"pco": "Planning Center Calendar", "churchcenter": "Church Center",
              "ics": "Calendar feed + Church Center"}[args.source]
    meta = {"generated_at": iso_z(now), "source": source, "timezone": args.timezone,
            "window": {"since": iso_z(since), "until": iso_z(until)}}
    write_json(out("events.json"), feed, meta)
    write_ics(out("events.ics"), feed, args.calendar_name, now)
    write_rss(out("events.rss.xml"), feed, args.calendar_name, args.site_url, now)
    with open(out("changes.json"), "w") as f:
        json.dump({"generated_at": meta["generated_at"], **changes, "warnings": warnings}, f, indent=2)

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        summary = run_summary(feed, changes, warnings)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)  # shows on the run page
        print(summary, file=sys.stderr)  # and in the log

    upcoming = sum(1 for e in feed if e["status"] == "upcoming")
    with_reg = sum(1 for e in feed if e["registration_url"])
    print(f"✅ {len(feed)} events written to {args.output_dir} "
          f"({upcoming} upcoming, {len(feed) - upcoming} past, {with_reg} with registration links)", file=sys.stderr)
    print(f"   Changes: +{len(changes['added'])} added, ~{len(changes['updated'])} updated, "
          f"-{len(changes['removed'])} removed", file=sys.stderr)


if __name__ == "__main__":
    main()
