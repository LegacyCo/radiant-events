"""One-off diagnostic: Church Center calendar shape for Radiant (location, paging,
filters). Prints public data only (never the visitor token)."""
import json
import urllib.error
import urllib.request

SUB = "radiantcentralcoast"
ORIGIN = f"https://{SUB}.churchcenter.com"
API = "https://api.churchcenter.com/calendar/v2"
UA = "legacy-church-events-sync/1.0 (probe)"


def req(url, headers=None, data=None):
    r = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


tok = json.loads(req(f"{ORIGIN}/sessions/tokens", {"Origin": ORIGIN, "Accept": "application/json",
                                                    "Content-Type": "application/json"}, b"{}")[1])
AUTH = {"Authorization": f"Bearer {tok['data']['attributes']['token']}", "Origin": ORIGIN, "Accept": "application/json"}


def get(path):
    status, body = req(f"{API}{path}", AUTH)
    try:
        return status, json.loads(body)
    except ValueError:
        return status, {"raw": body[:300].decode(errors="replace")}


def summary(label, path):
    status, d = get(path)
    print(f"\n=== {label}: {path} -> {status}")
    if status != 200:
        print(json.dumps(d)[:400])
        return d
    data = d.get("data") or []
    first = data[0] if isinstance(data, list) and data else data
    print("count on page:", len(data) if isinstance(data, list) else 1, "| links:", d.get("links"))
    print("meta:", json.dumps(d.get("meta"))[:1500])
    if first:
        print("attribute keys:", sorted((first.get("attributes") or {}).keys()))
        print("relationships:", json.dumps(first.get("relationships"))[:800])
        print("first:", first.get("id"), (first.get("attributes") or {}).get("name"),
              (first.get("attributes") or {}).get("starts_at"))
    inc = d.get("included") or []
    print("included types:", sorted({i.get("type") for i in inc}))
    for t in sorted({i.get("type") for i in inc}):
        one = next(i for i in inc if i.get("type") == t)
        print(f"  {t} sample:", json.dumps(one)[:700])
    return d


summary("upcoming", "/events?filter=upcoming")
for inc in ("location", "locations", "event_times", "location,event_times", "event_group", "tags", "resource"):
    summary(f"include {inc}", f"/events?filter=upcoming&include={inc}")
summary("per_page", "/events?filter=upcoming&per_page=100")
summary("where gte", "/events?where[starts_at][gte]=2026-10-01T00:00:00Z&order=starts_at")
summary("past", "/events?filter=past")
summary("order desc", "/events?order=-starts_at")
d = summary("one event", "/events/200190659")
summary("one event + includes", "/events/200190659?include=location,event_times")
summary("event_times of one", "/events/200190659/event_times")
summary("location of one", "/events/200190659/location")
