"""One-off diagnostic: which Church Center calendar endpoints exist for Radiant,
and what fields they return. Prints public data only (never the visitor token)."""
import json
import re
import urllib.error
import urllib.request

SUB = "radiantcentralcoast"
ORIGIN = f"https://{SUB}.churchcenter.com"
API = "https://api.churchcenter.com"
UA = "legacy-church-events-sync/1.0 (probe)"


def req(url, headers=None, data=None):
    r = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()
    except Exception as e:
        return None, "", str(e).encode()


tok = json.loads(req(f"{ORIGIN}/sessions/tokens", {"Origin": ORIGIN, "Accept": "application/json",
                                                    "Content-Type": "application/json"}, b"{}")[2])
AUTH = {"Authorization": f"Bearer {tok['data']['attributes']['token']}", "Origin": ORIGIN, "Accept": "application/json"}


def show(label, url, headers=AUTH, n=1500):
    status, ctype, body = req(url, headers)
    print(f"\n=== {label}\n{url}\n-> {status} {ctype}")
    if n:
        print(body[:n].decode(errors="replace"))
    return status, body


print("##### API roots")
for u in (f"{API}/calendar/v2", f"{API}/registrations/v2", f"{API}/"):
    show("root", u, n=3000)

print("\n##### Candidate calendar endpoints")
for path in ("events", "events?filter=upcoming", "events?include=event_times", "event_times",
             "event_instances?filter=future", "calendar_events", "events_with_instances"):
    show(path, f"{API}/calendar/v2/{path}", n=2500)

print("\n##### Registrations sample (field names, images)")
show("registrations", f"{API}/registrations/v2/events?per_page=2", n=5000)

print("\n##### What the Church Center calendar page calls")
status, html = show("calendar page", f"{ORIGIN}/calendar", headers={"Accept": "text/html"}, n=0)
text = html.decode(errors="replace")
print("api paths in page:", sorted(set(re.findall(r"[a-z_]+/v2/[a-z_/]+", text)))[:60])
scripts = re.findall(r'<script[^>]+src="([^"]+)"', text)
print("scripts:", scripts[:30])
found = set()
for src in scripts:
    src = "https:" + src if src.startswith("//") else (ORIGIN + src if src.startswith("/") else src)
    s, _, js = req(src)
    if s == 200:
        found |= set(re.findall(rb"calendar/v2/[a-z_]+(?:/[a-z_]+)?", js))
        found |= set(re.findall(rb"/calendar/[a-z_]+\.json", js))
print("calendar endpoints in JS:", sorted(x.decode() for x in found))

print("\n##### Calendar feed candidates")
for u in (f"{ORIGIN}/calendar.ics", f"{ORIGIN}/calendar/feed.ics", f"{ORIGIN}/calendar?format=ics",
          f"{ORIGIN}/calendar.json"):
    show("feed?", u, headers={"Accept": "*/*"}, n=300)
