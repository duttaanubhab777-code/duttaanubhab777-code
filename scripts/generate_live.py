#!/usr/bin/env python3
"""
Live profile generator  (stdlib only, no pip install needed)

Reads your real GitHub data through the GraphQL API and writes three
trading-terminal style animated SVGs into the output folder:

    live-ticker.svg     scrolling ticker tape
    live-dashboard.svg  big number + 60-day chart + watchlist + languages
    live-candles.svg    weekly candlesticks (7-day rolling activity index)

Usage:
    GH_USER=your-name GH_TOKEN=xxx python3 scripts/generate_live.py --out dist
    python3 scripts/generate_live.py --demo --out dist     # fake data, for design tests
"""
import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape

API = "https://api.github.com/graphql"
IST = timezone(timedelta(hours=5, minutes=30))

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    name
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

# ───────────────────────── colours ─────────────────────────
BG = "#0a0d22"
PANEL = "#0f1330"
LINE = "#1d2350"
BORDER = "#262d5c"
TXT = "#e8ebff"
MUTED = "#9aa3c7"
DIM = "#5b6490"
UP = "#3ddc84"
DOWN = "#ff4d6d"
FLAT = "#ffb347"
ORANGE = "#ff7a3d"
BLUE = "#7c8cff"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


# ───────────────────────── data ─────────────────────────
def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "live-profile-generator",
        },
    )
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.load(r)
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            user = payload["data"]["user"]
            if not user:
                raise RuntimeError(f"user '{login}' not found")
            return user
        except (urllib.error.URLError, RuntimeError, TimeoutError, KeyError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    sys.exit(f"GitHub API failed after retries: {last_err}")


def normalize(user):
    cc = user["contributionsCollection"]
    days = []
    for w in cc["contributionCalendar"]["weeks"]:
        for d in w["contributionDays"]:
            days.append((date.fromisoformat(d["date"]), d["contributionCount"]))
    days.sort()

    repos = user["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    lang = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            cur = lang.setdefault(n, [0, e["node"]["color"] or "#8b93b8"])
            cur[0] += e["size"]
    langs = sorted(((n, v[1], v[0]) for n, v in lang.items()), key=lambda x: -x[2])

    return {
        "login": user["login"],
        "name": user["name"] or user["login"],
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
        "stars": stars,
        "commits": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
        "total": cc["contributionCalendar"]["totalContributions"],
        "days": days,
        "langs": langs,
    }


def demo_data():
    rnd = random.Random(7)
    end = datetime.now(timezone.utc).date()
    days = []
    for i in range(365):
        d = end - timedelta(days=364 - i)
        if d < end - timedelta(days=71):
            c = 0
        elif d < end - timedelta(days=23):
            c = rnd.choice([0, 0, 1, 2, 5, 9, 14]) if rnd.random() < 0.55 else 0
        else:
            c = rnd.choice([3, 5, 8, 11, 14, 19, 25, 31])
        days.append((d, c))
    return {
        "login": "demo-user", "name": "Anubhab Dutta", "followers": 4, "repos": 10,
        "stars": 5, "commits": 473, "prs": 3, "issues": 0,
        "total": sum(c for _, c in days), "days": days,
        "langs": [("JavaScript", "#f1e05a", 5650), ("Python", "#3572A5", 1649),
                  ("CSS", "#563d7c", 1769), ("HTML", "#e34c26", 930)],
    }


# ───────────────────────── metrics ─────────────────────────
def window_sum(counts, end_idx, n):
    start = max(0, end_idx - n + 1)
    return sum(counts[start:end_idx + 1])


def compute(data):
    days = data["days"]
    counts = [c for _, c in days]
    n = len(counts)
    last = n - 1

    # "today" is still in progress in the UTC calendar, so a zero today
    # must not break a running streak.
    i = last - 1 if counts[last] == 0 else last
    cur = 0
    while i >= 0 and counts[i] > 0:
        cur += 1
        i -= 1
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)

    rolling = [window_sum(counts, k, 7) for k in range(n)]
    return {
        "counts": counts,
        "rolling": rolling,
        "today": counts[last],
        "yesterday": counts[last - 1] if n > 1 else 0,
        "d7": window_sum(counts, last, 7),
        "d7_prev": window_sum(counts, last - 7, 7) if n > 14 else 0,
        "d30": window_sum(counts, last, 30),
        "d30_prev": window_sum(counts, last - 30, 30) if n > 60 else 0,
        "streak": cur,
        "longest": longest,
        "active_today": counts[last] > 0,
        "active_days": sum(1 for c in counts if c > 0),
    }


def delta(cur, prev):
    """returns (arrow, colour, text)"""
    diff = cur - prev
    if diff > 0:
        pct = f" ({diff / prev * 100:+.0f}%)" if prev else ""
        return "▲", UP, f"{diff:+d}{pct}"
    if diff < 0:
        pct = f" ({diff / prev * 100:+.0f}%)" if prev else ""
        return "▼", DOWN, f"{diff:+d}{pct}"
    return "■", FLAT, "0"


def nice_max(v):
    v = max(v, 1)
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def f1(x):
    return f"{x:.1f}"


def week_groups(days):
    """group (date,count) into Sunday-start weeks -> list of lists of indices"""
    groups = {}
    for idx, (d, _) in enumerate(days):
        sunday = d - timedelta(days=(d.weekday() + 1) % 7)
        groups.setdefault(sunday, []).append(idx)
    return [groups[k] for k in sorted(groups)]


# ───────────────────────── shared svg bits ─────────────────────────
COMMON_CSS = f"""
.m{{font-family:{MONO}}}
.ring{{transform-box:fill-box;transform-origin:center;animation:ring 1.8s ease-out infinite}}
@keyframes ring{{0%{{transform:scale(1);opacity:.8}}100%{{transform:scale(3.2);opacity:0}}}}
.blink{{animation:blink 1.1s steps(1) infinite}}
@keyframes blink{{50%{{opacity:0}}}}
.soft{{animation:soft 2.4s ease-in-out infinite}}
@keyframes soft{{50%{{opacity:.45}}}}
.draw{{stroke-dasharray:1;stroke-dashoffset:1;animation:draw 2.4s ease-out .3s forwards}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
.fade{{animation:fade .9s ease-out both}}
@keyframes fade{{from{{opacity:0}}}}
"""


def live_badge(x, y):
    return (
        f'<circle cx="{x}" cy="{y}" r="5" fill="{UP}"/>'
        f'<circle class="ring" cx="{x}" cy="{y}" r="5" fill="none" stroke="{UP}" stroke-width="1.5"/>'
        f'<text class="m" x="{x + 14}" y="{y + 4}" fill="{UP}" font-size="12" font-weight="700" letter-spacing="2">LIVE</text>'
    )


def stamp(now):
    ist = now.astimezone(IST)
    return ist.strftime("%d %b %Y · %H:%M IST").upper()


# ───────────────────────── 1. ticker ─────────────────────────
def build_ticker(data, m, now):
    ar7, col7, tx7 = delta(m["d7"], m["d7_prev"])
    ar_t, col_t, tx_t = delta(m["today"], m["yesterday"])
    top = data["langs"][0] if data["langs"] else None
    tot_l = sum(l[2] for l in data["langs"]) or 1

    items = [
        ("CONTRIB·1Y", f"{data['total']:,}", ar7, col7, f"{tx7} 7D"),
        ("TODAY", f"{m['today']}", ar_t, col_t, tx_t),
        ("STREAK", f"{m['streak']}d", "▲" if m["active_today"] else "■",
         UP if m["active_today"] else FLAT, f"BEST {m['longest']}d"),
        ("COMMITS", f"{data['commits']:,}", "", MUTED, ""),
        ("PULL·REQ", f"{data['prs']}", "", MUTED, ""),
        ("REPOS", f"{data['repos']}", "", MUTED, ""),
        ("STARS", f"{data['stars']}", "", MUTED, ""),
        ("FOLLOWERS", f"{data['followers']}", "", MUTED, ""),
    ]
    if top:
        items.append(("TOP·LANG", top[0], "", MUTED, f"{top[2] / tot_l * 100:.1f}%"))

    nb = "\u00a0"
    parts, chars = [], 0
    for label, val, arrow, col, note in items:
        t = f'<tspan fill="{DIM}">{escape(label)}</tspan>{nb}<tspan fill="{TXT}" font-weight="700">{escape(val)}</tspan>'
        chars += len(label) + 1 + len(val)
        if arrow:
            t += f'{nb}<tspan fill="{col}">{arrow}</tspan>'
            chars += 2
        if note:
            t += f'{nb}<tspan fill="{col if arrow else MUTED}">{escape(note)}</tspan>'
            chars += 1 + len(note)
        t += f'{nb*3}<tspan fill="{BORDER}">│</tspan>{nb*3}'
        chars += 7
        parts.append(t)

    fs = 13
    char_w = fs * 0.6
    one_w = round(chars * char_w)
    visible = 1000 - 100
    copies = math.ceil(visible / one_w) + 1
    body = "".join(
        f'<text class="m" x="{k * one_w}" y="24" font-size="{fs}" textLength="{one_w}" lengthAdjust="spacing" xml:space="preserve">{"".join(parts)}</text>'
        for k in range(copies)
    )
    dur = max(25, one_w / 45)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 38" width="100%">
<title>Live ticker</title>
<defs>
<clipPath id="clip"><rect x="100" y="0" width="900" height="38"/></clipPath>
<linearGradient id="fl" x1="0" x2="1"><stop offset="0" stop-color="{BG}"/><stop offset="1" stop-color="{BG}" stop-opacity="0"/></linearGradient>
<linearGradient id="fr" x1="0" x2="1"><stop offset="0" stop-color="{BG}" stop-opacity="0"/><stop offset="1" stop-color="{BG}"/></linearGradient>
</defs>
<style>{COMMON_CSS}
.tk{{animation:tk {dur:.0f}s linear infinite}}
@keyframes tk{{to{{transform:translateX(-{one_w}px)}}}}
</style>
<rect width="1000" height="38" rx="10" fill="{BG}" stroke="{BORDER}"/>
<g clip-path="url(#clip)"><g class="tk">{body}</g></g>
<rect x="100" y="1" width="40" height="36" fill="url(#fl)"/>
<rect x="960" y="1" width="39" height="36" fill="url(#fr)"/>
<rect x="1" y="1" width="99" height="36" rx="9" fill="{PANEL}"/>
{live_badge(24, 19)}
</svg>
"""


# ───────────────────────── 2. dashboard ─────────────────────────
def build_dashboard(data, m, now):
    W, H = 1000, 520
    n = 60
    counts = m["counts"][-n:]
    start_day = data["days"][-n][0]
    ar7, col7, tx7 = delta(m["d7"], m["d7_prev"])
    trend = col7

    out = []
    a = out.append

    # header
    name = data["name"].upper().replace(" ", "·")
    a(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="20" fill="{BG}" stroke="{BORDER}"/>')
    a(f'<line x1="0" y1="52" x2="{W}" y2="52" stroke="{LINE}"/>')
    a(live_badge(36, 26))
    a(f'<text class="m" x="112" y="31" fill="{TXT}" font-size="15" font-weight="700" letter-spacing="1">{escape(name)}</text>')
    a(f'<text class="m" x="{W - 52}" y="30" text-anchor="end" fill="{MUTED}" font-size="11">SYNC {escape(stamp(now))}</text>')
    a(f'<rect class="blink" x="{W - 44}" y="20" width="8" height="14" fill="{UP}"/>')

    # headline number
    big = f"{data['total']:,}"
    a(f'<text class="m" x="30" y="82" fill="{BLUE}" font-size="11" letter-spacing="2">TOTAL CONTRIBUTIONS · LAST 12 MONTHS</text>')
    a(f'<text class="m tickfill" x="30" y="132" font-size="52" font-weight="700" fill="{TXT}">{big}</text>')
    chip_x = 30 + len(big) * 31.5 + 22
    chip = f"{ar7} {tx7} · 7D"
    chip_w = len(chip) * 7.4 + 22
    a(f'<rect x="{f1(chip_x)}" y="100" width="{f1(chip_w)}" height="28" rx="14" fill="{trend}" fill-opacity=".14" stroke="{trend}" stroke-opacity=".5"/>')
    a(f'<text class="m soft" x="{f1(chip_x + chip_w / 2)}" y="119" text-anchor="middle" fill="{trend}" font-size="13" font-weight="700">{escape(chip)}</text>')

    # area chart
    x0, x1, y0, y1 = 62, 590, 168, 396
    ymax = nice_max(max(counts) * 1.1)
    for k in range(5):
        gy = y1 - (y1 - y0) * k / 4
        a(f'<line x1="{x0}" y1="{f1(gy)}" x2="{x1}" y2="{f1(gy)}" stroke="{LINE}" stroke-dasharray="3 5"/>')
        a(f'<text class="m" x="{x0 - 8}" y="{f1(gy + 4)}" text-anchor="end" fill="{DIM}" font-size="10">{ymax * k / 4:g}</text>')
    pts = []
    for i, c in enumerate(counts):
        x = x0 + (x1 - x0) * i / (n - 1)
        y = y1 - (y1 - y0) * c / ymax
        pts.append((x, y))
    line = " ".join(f"{'M' if i == 0 else 'L'}{f1(x)} {f1(y)}" for i, (x, y) in enumerate(pts))
    area = f"{line} L{f1(x1)} {y1} L{x0} {y1} Z"
    a(f'<defs><linearGradient id="ar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{trend}" stop-opacity=".38"/><stop offset="1" stop-color="{trend}" stop-opacity="0"/></linearGradient></defs>')
    a(f'<path class="fade" style="animation-delay:1.2s" d="{area}" fill="url(#ar)"/>')
    a(f'<path class="draw" pathLength="1" d="{line}" fill="none" stroke="{trend}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>')
    lx, ly = pts[-1]
    a(f'<line x1="{f1(lx)}" y1="{f1(ly)}" x2="{x1 + 8}" y2="{f1(ly)}" stroke="{trend}" stroke-dasharray="2 4" class="fade" style="animation-delay:2.4s"/>')
    a(f'<circle cx="{f1(lx)}" cy="{f1(ly)}" r="4.5" fill="{trend}" class="fade" style="animation-delay:2.6s"/>')
    a(f'<circle class="ring" cx="{f1(lx)}" cy="{f1(ly)}" r="4.5" fill="none" stroke="{trend}" stroke-width="1.5"/>')
    a(f'<g class="soft"><rect x="{x1 + 8}" y="{f1(ly - 10)}" width="40" height="20" rx="4" fill="{trend}"/>'
      f'<text class="m" x="{x1 + 28}" y="{f1(ly + 4)}" text-anchor="middle" fill="{BG}" font-size="12" font-weight="700">{counts[-1]}</text></g>')
    for k in range(0, n, 12):
        d = start_day + timedelta(days=k)
        a(f'<text class="m" x="{f1(x0 + (x1 - x0) * k / (n - 1))}" y="{y1 + 18}" fill="{DIM}" font-size="10">{d.strftime("%d %b").upper()}</text>')
    a(f'<text class="m" x="{x0}" y="160" fill="{DIM}" font-size="10" letter-spacing="1">DAILY CONTRIBUTIONS · 60D</text>')

    # watchlist
    px = 668
    a(f'<rect x="{px}" y="72" width="302" height="352" rx="12" fill="{PANEL}" stroke="{LINE}"/>')
    a(f'<text class="m" x="{px + 14}" y="94" fill="{BLUE}" font-size="11" letter-spacing="2">WATCHLIST</text>')
    ar_t, col_t, tx_t = delta(m["today"], m["yesterday"])
    ar30, col30, tx30 = delta(m["d30"], m["d30_prev"])
    rows = [
        ("TODAY", f"{m['today']}", ar_t, col_t, tx_t),
        ("7 DAYS", f"{m['d7']}", ar7, col7, tx7),
        ("30 DAYS", f"{m['d30']}", ar30, col30, tx30),
        ("STREAK", f"{m['streak']}d", "▲" if m["active_today"] else "■",
         UP if m["active_today"] else FLAT, f"best {m['longest']}d"),
        ("ACTIVE DAYS", f"{m['active_days']}", "", MUTED, "of 365"),
        ("COMMITS", f"{data['commits']:,}", "", MUTED, "1Y"),
        ("PULL REQ", f"{data['prs']}", "", MUTED, "1Y"),
        ("ISSUES", f"{data['issues']}", "", MUTED, "1Y"),
        ("REPOS", f"{data['repos']}", "", MUTED, "own"),
        ("STARS / FOLLOW", f"{data['stars']} / {data['followers']}", "", MUTED, ""),
    ]
    ry = 104
    for i, (lab, val, arrow, col, note) in enumerate(rows):
        y = ry + i * 31.5
        if i % 2 == 0:
            a(f'<rect x="{px + 6}" y="{f1(y)}" width="290" height="29" rx="6" fill="{BG}" fill-opacity=".55" class="fade" style="animation-delay:{0.3 + i * 0.09:.2f}s"/>')
        a(f'<g class="fade" style="animation-delay:{0.35 + i * 0.09:.2f}s">'
          f'<text class="m" x="{px + 16}" y="{f1(y + 19)}" fill="{MUTED}" font-size="11">{escape(lab)}</text>'
          f'<text class="m" x="{px + 176}" y="{f1(y + 19)}" text-anchor="end" fill="{TXT}" font-size="14" font-weight="700">{escape(val)}</text>'
          f'<text class="m" x="{px + 288}" y="{f1(y + 19)}" text-anchor="end" fill="{col}" font-size="11">{(arrow + " ") if arrow else ""}{escape(note)}</text>'
          f'</g>')

    # languages
    langs = data["langs"]
    total_l = sum(l[2] for l in langs) or 1
    top = langs[:5]
    rest = total_l - sum(l[2] for l in top)
    if rest > 0:
        top.append(("Other", "#5b6490", rest))
    a(f'<text class="m" x="30" y="448" fill="{BLUE}" font-size="11" letter-spacing="2">TOP LANGUAGES · BY CODE SIZE</text>')
    bx, bw = 30, 940
    cx = bx
    for i, (nm, colr, size) in enumerate(top):
        w = max(4, bw * size / total_l)
        a(f'<rect class="seg" style="animation-delay:{0.2 + i * 0.15:.2f}s" x="{f1(cx)}" y="458" width="{f1(max(w - 3, 2))}" height="10" rx="5" fill="{colr}"/>')
        cx += w
    lx_ = 30
    for nm, colr, size in top:
        pct = size / total_l * 100
        a(f'<circle cx="{lx_ + 5}" cy="490" r="4.5" fill="{colr}"/>')
        a(f'<text class="m" x="{lx_ + 16}" y="494" fill="{TXT}" font-size="12">{escape(nm)} <tspan fill="{MUTED}">{pct:.1f}%</tspan></text>')
        lx_ += 22 + (len(nm) + 7) * 7.6 + 18
    a(f'<text class="m" x="{W - 30}" y="{H - 14}" text-anchor="end" fill="{DIM}" font-size="9">auto-refreshed every 15 min · GitHub Actions</text>')

    css = COMMON_CSS + f"""
.tickfill{{animation:tick 6s ease-in-out infinite}}
@keyframes tick{{0%,90%,100%{{fill:{TXT}}}94%{{fill:{UP}}}}}
.seg{{transform-box:fill-box;transform-origin:left center;animation:seg 1.1s cubic-bezier(.2,.8,.2,1) both}}
@keyframes seg{{from{{transform:scaleX(0)}}}}
"""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%">'
            f'<title>Live GitHub dashboard</title><style>{css}</style>' + "".join(out) + "</svg>\n")


# ───────────────────────── 3. candlesticks ─────────────────────────
def build_candles(data, m, now):
    W, H = 1000, 420
    days = data["days"]
    counts, rolling = m["counts"], m["rolling"]

    all_groups = week_groups(days)
    first_active = next((i for i, (_, c) in enumerate(days) if c > 0), 0)
    first_week = next(wi for wi, g in enumerate(all_groups) if first_active in g)
    # start 3 weeks before the first activity, but show between 14 and 26 weeks
    start_w = max(0, min(first_week - 3, len(all_groups) - 14))
    groups = all_groups[max(start_w, len(all_groups) - 26):]
    candles = []
    for g in groups:
        first, last = g[0], g[-1]
        o = rolling[first - 1] if first > 0 else rolling[first]
        c = rolling[last]
        series = [rolling[k] for k in g]
        candles.append({
            "o": o, "c": c,
            "h": max(series + [o]), "l": min(series + [o]),
            "v": sum(counts[k] for k in g),
            "d": days[first][0],
        })
    nC = len(candles)

    out = []
    a = out.append
    a(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="20" fill="{BG}" stroke="{BORDER}"/>')
    a(f'<line x1="0" y1="52" x2="{W}" y2="52" stroke="{LINE}"/>')
    a(live_badge(36, 26))
    a(f'<text class="m" x="112" y="31" fill="{TXT}" font-size="14" font-weight="700" letter-spacing="1">ACTIVITY INDEX</text>')
    a(f'<text class="m" x="262" y="31" fill="{DIM}" font-size="11">7D ROLLING · 1W CANDLES · {len(candles)}W</text>')

    lc = candles[-1]
    ccol = UP if lc["c"] >= lc["o"] else DOWN
    a(f'<text class="m" x="{W - 30}" y="31" text-anchor="end" font-size="11" fill="{MUTED}">'
      f'O <tspan fill="{ccol}">{lc["o"]}</tspan>  H <tspan fill="{ccol}">{lc["h"]}</tspan>  '
      f'L <tspan fill="{ccol}">{lc["l"]}</tspan>  C <tspan fill="{ccol}">{lc["c"]}</tspan>  '
      f'VOL <tspan fill="{TXT}">{lc["v"]}</tspan></text>')

    x0, x1 = 30, 900
    p0, p1 = 74, 280          # price pane
    v0, v1 = 300, 356         # volume pane
    ymax = nice_max(max(c["h"] for c in candles) * 1.12)
    vmax = max(max(c["v"] for c in candles), 1)
    step = (x1 - x0) / nC
    bw = step * 0.56

    def py(v):
        return p1 - (p1 - p0) * v / ymax

    for k in range(5):
        gy = p1 - (p1 - p0) * k / 4
        a(f'<line x1="{x0}" y1="{f1(gy)}" x2="{x1}" y2="{f1(gy)}" stroke="{LINE}" stroke-dasharray="3 5"/>')
        a(f'<text class="m" x="{W - 14}" y="{f1(gy + 4)}" text-anchor="end" fill="{DIM}" font-size="10">{ymax * k / 4:g}</text>')
    a(f'<line x1="{x0}" y1="{v1}" x2="{x1}" y2="{v1}" stroke="{LINE}"/>')
    a(f'<text class="m" x="{x0}" y="{v0 - 6}" fill="{DIM}" font-size="9" letter-spacing="1">VOLUME · CONTRIBUTIONS / WEEK</text>')

    # SMA(4) of closes
    sma = []
    for i in range(nC):
        seg = [candles[j]["c"] for j in range(max(0, i - 3), i + 1)]
        sma.append(sum(seg) / len(seg))

    for i, c in enumerate(candles):
        cx = x0 + (i + 0.5) * step
        up = c["c"] >= c["o"]
        col = UP if up else DOWN
        top, bot = py(max(c["o"], c["c"])), py(min(c["o"], c["c"]))
        body_h = max(bot - top, 2)
        live = i == nC - 1
        delay = f"{i * 0.045:.2f}s"
        cls = "cd live" if live else "cd"
        a(f'<g class="{cls}" style="animation-delay:{delay}">'
          f'<line x1="{f1(cx)}" y1="{f1(py(c["h"]))}" x2="{f1(cx)}" y2="{f1(py(c["l"]))}" stroke="{col}" stroke-width="1.6"/>'
          f'<rect x="{f1(cx - bw / 2)}" y="{f1(top)}" width="{f1(bw)}" height="{f1(body_h)}" rx="2" fill="{col}"/></g>')
        vh = max((v1 - v0 - 16) * c["v"] / vmax, 1.5) if c["v"] else 1.5
        a(f'<rect class="cd" style="animation-delay:{delay}" x="{f1(cx - bw / 2)}" y="{f1(v1 - vh)}" width="{f1(bw)}" height="{f1(vh)}" rx="2" fill="{col}" fill-opacity=".5"/>')
        if i % 4 == 0:
            a(f'<text class="m" x="{f1(cx)}" y="{v1 + 18}" text-anchor="middle" fill="{DIM}" font-size="10">{c["d"].strftime("%d %b").upper()}</text>')

    sline = " ".join(f"{'M' if i == 0 else 'L'}{f1(x0 + (i + 0.5) * step)} {f1(py(v))}" for i, v in enumerate(sma))
    a(f'<path class="draw" pathLength="1" d="{sline}" fill="none" stroke="{ORANGE}" stroke-width="1.8" stroke-linejoin="round" stroke-opacity=".9"/>')
    a(f'<text class="m" x="{x0 + 4}" y="{p0 - 8}" fill="{ORANGE}" font-size="10">━ SMA(4)</text>')

    # live price line + tag
    ly = py(lc["c"])
    a(f'<line class="fade" style="animation-delay:2.2s" x1="{x0}" y1="{f1(ly)}" x2="{x1 + 6}" y2="{f1(ly)}" stroke="{ccol}" stroke-dasharray="2 4" stroke-opacity=".8"/>')
    a(f'<g class="soft"><rect x="{x1 + 6}" y="{f1(ly - 10)}" width="46" height="20" rx="4" fill="{ccol}"/>'
      f'<text class="m" x="{x1 + 29}" y="{f1(ly + 4)}" text-anchor="middle" fill="{BG}" font-size="12" font-weight="700">{lc["c"]}</text></g>')

    a(f'<text class="m" x="{x0}" y="{H - 14}" fill="{DIM}" font-size="9">Index = contributions in the trailing 7 days · candle = one week (O first / C last / H,L extremes) · volume = weekly total</text>')

    css = COMMON_CSS + """
.cd{transform-box:fill-box;transform-origin:50% 100%;animation:grow .7s cubic-bezier(.2,.8,.2,1) both}
@keyframes grow{from{transform:scaleY(0);opacity:0}}
.live{animation:grow .7s cubic-bezier(.2,.8,.2,1) both,glow 1.6s ease-in-out 1.6s infinite}
@keyframes glow{50%{opacity:.55}}
"""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%">'
            f'<title>Weekly activity candlesticks</title><style>{css}</style>' + "".join(out) + "</svg>\n")


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--demo", action="store_true", help="use fake data (design test only)")
    args = ap.parse_args()

    if args.demo:
        data = demo_data()
    else:
        login = os.environ.get("GH_USER")
        token = os.environ.get("GH_TOKEN")
        if not login or not token:
            sys.exit("GH_USER and GH_TOKEN environment variables are required")
        data = normalize(fetch(login, token))

    if len(data["days"]) < 70:
        sys.exit("not enough contribution days returned")

    m = compute(data)
    now = datetime.now(timezone.utc)
    os.makedirs(args.out, exist_ok=True)
    files = {
        "live-ticker.svg": build_ticker(data, m, now),
        "live-dashboard.svg": build_dashboard(data, m, now),
        "live-candles.svg": build_candles(data, m, now),
    }
    for name, svg in files.items():
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"wrote {name} ({len(svg):,} bytes)")
    print(f"total={data['total']} streak={m['streak']} 7d={m['d7']} (prev {m['d7_prev']})")


if __name__ == "__main__":
    main()
    
