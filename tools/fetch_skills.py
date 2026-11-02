"""Collect AION 2 skill descriptions from MetaBot.GG into shugotracker/data/skills.json.gz.

    python tools/fetch_skills.py            # all skills (~280 pages, about 5 minutes at 1 request/second)
    python tools/fetch_skills.py frost      # just these slugs, printed (for checking the parser)

MetaBot.GG reads the skills from the AION 2 Global client and lets apps show the data on one condition: credit
MetaBot.GG with a link to the page each skill came from. Every entry keeps that page's URL, and the app links it.
Their skill IDs are the game's own, the same ones NCSOFT's character API returns, so entries are keyed by ID.

Run by the "Update skill data" workflow; the file only changes when the skills do (no timestamps, gzip mtime 0).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://metabot.gg"
INDEX = BASE + "/en/aion-2/skills"
OUT = os.path.join(os.path.dirname(__file__), "..", "shugotracker", "data", "skills.json.gz")
UA = "ShugoTracker skill data (+https://github.com/CynicaGaming/Shugo-Tracker)"
DELAY_S = 1.0             # well under MetaBot's ~60 requests/minute
MIN_SKILLS = 200          # fewer than this means the site changed: keep the old file rather than ship a broken one

_RSC = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', re.S)
_LDJSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_ICON_ID = re.compile(r"/web/aion2/skills/(\d+)\.webp")


def get(url: str) -> str:
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
                print(f"  {e.code} on {url}, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"gave up on {url}")


def skill_slugs(index_html: str) -> list[str]:
    seen: dict[str, None] = {}
    for slug in re.findall(r"/en/aion-2/skills/([a-z0-9-]+)", index_html):
        seen.setdefault(slug, None)
    return list(seen)


def _flight_text(html: str) -> str:
    """The page's React Server Components payload, decoded and joined (where the per-level data lives)."""
    return "".join(json.loads(f'"{m}"') for m in _RSC.findall(html))


def _json_array_at(text: str, start: int) -> list:
    """Parse the JSON array that opens at text[start] ('['), however much follows it."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated array")


def parse_skill_page(html: str, url: str) -> tuple[str, dict] | None:
    """(skill id, entry) from one MetaBot skill page, or None if it doesn't look like one.
    The id is the game's skill ID, or "name:<class>:<skill>" for the odd page without an icon to read it from."""
    sid = name = cls = ""
    for block in _LDJSON.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if d.get("@type") == "BreadcrumbList":
            crumbs = [it.get("name") or "" for it in d.get("itemListElement") or []]
            if len(crumbs) >= 2:
                cls, name = crumbs[-2], crumbs[-1]
        elif str(d.get("@id") or "").endswith("#entity"):     # the skill itself: its icon is named by its ID
            m = _ICON_ID.search(str(d.get("image") or ""))
            sid = m.group(1) if m else sid
    flight = _flight_text(html)
    if not sid:
        m = _ICON_ID.search(html)
        if m:
            sid = m.group(1)
        elif name and cls:                       # no icon on the page, so no ID: the app matches these by name
            sid = f"name:{cls}:{name}"
        else:
            return None
    at = flight.find('"levels":[')
    if at < 0 or not name:
        return None
    levels = sorted(_json_array_at(flight, at + len('"levels":')), key=lambda lv: lv.get("level") or 0)
    if not levels:
        return None
    return sid, {
        "name": name,
        "class": cls,
        "url": url,
        "text": [(lv.get("text") or "").strip() for lv in levels],
        "cd": [lv.get("cooldown") or "" for lv in levels],
        "mp": [lv.get("mp") or "" for lv in levels],
    }


def write(skills: dict) -> None:
    data = {"source": "MetaBot.GG", "source_url": INDEX, "skills": dict(sorted(skills.items()))}
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)


def main(argv: list[str]) -> int:
    only = argv[1:]
    slugs = only or skill_slugs(get(INDEX))
    print(f"{len(slugs)} skills", file=sys.stderr)
    skills: dict[str, dict] = {}
    failed: list[str] = []
    for i, slug in enumerate(slugs, 1):
        url = f"{INDEX}/{slug}"
        try:
            got = parse_skill_page(get(url), url)
        except Exception as e:  # noqa: BLE001
            print(f"  {slug}: {e}", file=sys.stderr)
            got = None
        if got is None:
            failed.append(slug)
        else:
            sid, entry = got
            skills[sid] = entry
        if i % 25 == 0:
            print(f"  {i}/{len(slugs)}", file=sys.stderr)
        if i < len(slugs):
            time.sleep(DELAY_S)
    for slug in list(failed):                     # one more go for any that hit a hiccup
        time.sleep(DELAY_S * 3)
        url = f"{INDEX}/{slug}"
        try:
            got = parse_skill_page(get(url), url)
        except Exception as e:  # noqa: BLE001
            print(f"  {slug} (retry): {e}", file=sys.stderr)
            continue
        if got is not None:
            skills[got[0]] = got[1]
            failed.remove(slug)
    if failed:
        print(f"couldn't read {len(failed)}: {', '.join(failed)}", file=sys.stderr)
    if only:
        print(json.dumps(skills, ensure_ascii=False, indent=1)[:4000])
        return 0
    if len(skills) < MIN_SKILLS:
        print(f"only {len(skills)} skills read; keeping the existing file", file=sys.stderr)
        return 1
    write(skills)
    print(f"wrote {len(skills)} skills to {os.path.normpath(OUT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
