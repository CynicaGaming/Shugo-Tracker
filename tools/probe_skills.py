"""One-off: find where NCSOFT's site gets skill descriptions / specialties (run in CI, results pushed to a branch)."""
import json
import re
import sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
out = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); out.append(s)

s = requests.Session(); s.headers.update(UA)
# a real character
r = s.get("https://api-search.plaync.com/aion2global/search/v2/character",
          params={"keyword": "Luna", "page": 1, "size": 5, "localeInfo": "en-US", "region": "as"}, timeout=20)
c = [x for x in r.json()["list"] if x.get("level", 0) >= 45][0]
cid = requests.utils.unquote(c["characterId"]); sid = c["serverId"]
log("char", c["name"], sid, cid)
q = {"lang": "en-US", "characterId": cid, "serverId": sid, "region": "as"}
eq = s.get("https://aion2.plaync.com/api/character/equipment", params=q, timeout=20).json()
skills = eq["skill"]["skillList"]
log("skill keys", sorted(skills[0].keys()))
sk = next(x for x in skills if x.get("acquired"))
log("sample skill", json.dumps(sk))

# scripts on the site
pages = ["https://aion2.plaync.com/en-us/characters/index",
         f"https://aion2.plaync.com/en-us/characters/server/{sid}/{requests.utils.quote(cid)}"]
js = set()
for p in pages:
    h = s.get(p, timeout=20)
    log("page", p, h.status_code, len(h.text))
    for m in re.findall(r'src="([^"]+\.js[^"]*)"', h.text):
        js.add(requests.compat.urljoin(p, m))
    for m in re.findall(r'"(/api/[^"]+)"', h.text):
        log("  api in html:", m)
apis = set()
seen = set()
queue = list(js)
while queue and len(seen) < 80:
    u = queue.pop()
    if u in seen:
        continue
    seen.add(u)
    try:
        t = s.get(u, timeout=20).text
    except Exception as e:
        log("js fail", u, e); continue
    for m in re.findall(r'["\'`](/api/[A-Za-z0-9_\-/{}$.]+)', t):
        apis.add(m)
    for m in re.findall(r'["\']([^"\']*?/_next/static/chunks/[^"\']+\.js)["\']', t):
        queue.append(requests.compat.urljoin(u, m))
    for m in re.findall(r'["\'](static/chunks/[^"\']+\.js)["\']', t):
        queue.append(requests.compat.urljoin(u.split("static/")[0], m))
    for kw in ("skillDetail", "skill/detail", "specialty", "Specialty", "skillTooltip", "tooltip", "description"):
        for m in re.finditer(kw, t):
            log(f"  [{kw}] {u.rsplit('/',1)[-1]}: ...{t[max(0,m.start()-120):m.end()+120]!r}")
            break
log("JS files scanned:", len(seen))
for a in sorted(apis):
    log("API:", a)

# try likely endpoints
cands = [
    ("character/skill", {**q}),
    ("character/skillDetail", {**q, "skillId": sk["id"]}),
    ("character/skill/detail", {**q, "skillId": sk["id"], "skillLevel": sk.get("skillLevel")}),
    ("skill/detail", {"lang": "en-US", "id": sk["id"], "level": sk.get("skillLevel")}),
    ("gamedata/skill", {"lang": "en-US", "id": sk["id"]}),
    ("character/equipment/item", {**q, "id": eq["equipment"]["equipmentList"][0]["id"]}),
]
for path, params in cands:
    try:
        rr = s.get("https://aion2.plaync.com/api/" + path, params=params, timeout=20)
        log("TRY", path, rr.status_code, rr.text[:600].replace("\n", " "))
    except Exception as e:
        log("TRY", path, "ERR", e)
for a in sorted(apis):
    if "skill" in a.lower() or "item" in a.lower() or "tooltip" in a.lower():
        path = a.split("/api/", 1)[1].split("?")[0]
        if "{" in path or "$" in path:
            continue
        for params in ({**q, "skillId": sk["id"], "skillLevel": sk.get("skillLevel"), "id": sk["id"], "level": sk.get("skillLevel")},):
            try:
                rr = s.get("https://aion2.plaync.com/api/" + path, params=params, timeout=20)
                log("TRY*", path, rr.status_code, rr.text[:800].replace("\n", " "))
            except Exception as e:
                log("TRY*", path, "ERR", e)
open(sys.argv[1] if len(sys.argv) > 1 else "probe.txt", "w", encoding="utf-8").write("\n".join(out))
