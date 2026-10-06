"""Génère les graphiques du profil GitHub (assets/*.svg), en clair et en sombre.

Lancé chaque nuit par .github/workflows/stats.yml. Lit les données avec le jeton
PROFILE_STATS_TOKEN (lecture seule : contenu et métadonnées des dépôts).

    PROFILE_STATS_TOKEN=... python scripts/generate.py
"""
import collections
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TZ = ZoneInfo(os.environ.get("PROFILE_TZ", "America/Toronto"))
STATS_REPO = os.environ.get("PROFILE_STATS_REPO", "elens-platform")

# ---------------------------------------------------------------- données


def api(url, body=None):
    token = os.environ.get("PROFILE_STATS_TOKEN")
    if not token:
        sys.exit("PROFILE_STATS_TOKEN manquant : voir scripts/LISEZMOI.md.")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "User-Agent": "profile-stats",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def gql(query, **variables):
    res = api("https://api.github.com/graphql", {"query": query, "variables": variables})
    if res.get("errors"):
        sys.exit(f"GraphQL : {res['errors']}")
    return res["data"]


Q_PROFILE = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    id login
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        name
        defaultBranchRef { name }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      }
    }
  }
}"""

Q_HISTORY = """
query($owner: String!, $name: String!, $author: ID!, $since: GitTimestamp!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor, since: $since, author: {id: $author}) {
        pageInfo { hasNextPage endCursor } nodes { authoredDate }
      }
    } } }
  }
}"""

LANG_NAMES = {"PLpgSQL": "SQL", "PLSQL": "SQL", "TSQL": "SQL"}
# Langages qui gonflent les octets sans être du code écrit à la main (sorties de notebooks, maquettes).
LANG_IGNORE = {l.strip() for l in os.environ.get("PROFILE_LANG_IGNORE", "Jupyter Notebook,HTML").split(",") if l.strip()}


def fetch(end):
    start = end - dt.timedelta(days=364)
    v = gql(Q_PROFILE, **{"from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"})["viewer"]
    cal = v["contributionsCollection"]["contributionCalendar"]
    days = {dt.date.fromisoformat(d["date"]): d["contributionCount"]
            for w in cal["weeks"] for d in w["contributionDays"]}
    commit_days = collections.Counter()

    langs = collections.Counter()
    hours = collections.Counter()
    for repo in v["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            if e["node"]["name"] not in LANG_IGNORE:
                langs[LANG_NAMES.get(e["node"]["name"], e["node"]["name"])] += e["size"]
        if not repo["defaultBranchRef"]:
            continue
        cursor = None
        while True:
            h = gql(Q_HISTORY, owner=v["login"], name=repo["name"], author=v["id"],
                    since=f"{start}T00:00:00Z", cursor=cursor)["repository"]["defaultBranchRef"]["target"]["history"]
            for n in h["nodes"]:
                t = dt.datetime.fromisoformat(n["authoredDate"].replace("Z", "+00:00"))
                if t.utcoffset() == dt.timedelta(0):  # heure sans fuseau d'origine : ramenée à l'heure locale
                    t = t.astimezone(TZ)
                hours[t.hour] += 1
                commit_days[t.date()] += 1
            if not h["pageInfo"]["hasNextPage"]:
                break
            cursor = h["pageInfo"]["endCursor"]

    # Le calendrier ne compte les contributions privées que si le profil les publie ; les commits lus
    # dépôt par dépôt servent de plancher, pour que le graphe ne tombe jamais à zéro.
    for d, n in commit_days.items():
        if start <= d <= end:
            days[d] = max(days.get(d, 0), n)

    numbers = None
    branch = next((r["defaultBranchRef"]["name"] for r in v["repositories"]["nodes"]
                   if r["name"] == STATS_REPO and r["defaultBranchRef"]), None)
    if branch:
        tree = api(f"https://api.github.com/repos/{v['login']}/{STATS_REPO}/git/trees/{branch}?recursive=1")
        paths = [t["path"] for t in tree["tree"] if t["type"] == "blob"]
        count = lambda rx: sum(1 for p in paths if re.search(rx, p))
        numbers = [
            (count(r"\.test\.tsx?$"), "tests"),
            (count(r"^supabase/migrations/.*(?<!\.down)\.sql$"), "migrations"),
            (count(r"^src/app/(.*/)?page\.tsx$"), "pages web"),
            (count(r"^supabase/tests/[^/]+\.sql$"), "suites SQL"),
        ]
    total = max(cal["totalContributions"], sum(days.values()))
    print(f"calendrier GitHub : {cal['totalContributions']} · commits lus : {sum(commit_days.values())} · total retenu : {total}")
    print("langages :", ", ".join(f"{k} {v // 1024} Ko" for k, v in langs.most_common(6)))
    print("chiffres :", numbers)
    return dict(end=end, start=start, days=days, total=total, hours=hours, langs=langs, numbers=numbers)


# ---------------------------------------------------------------- dessin

GLYPHS = json.loads((Path(__file__).parent / "glyphs.json").read_text())
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',Arial,sans-serif"
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TH = {
    "light": dict(bg="#fbfaf7", edge="#e6e2d8", ink="#15151a", muted="#726d63", faint="#8a847a", hair="#efebe3",
                  acc="#3a7560", seq=["#efebe3", "#c9ddd2", "#8dbaa4", "#56937a", "#2f5f4e"]),
    "dark": dict(bg="#17171c", edge="#2c2c33", ink="#f7f5f0", muted="#a8a294", faint="#7d786e", hair="#24242b",
                 acc="#7fb59e", seq=["#24242b", "#24433a", "#33684f", "#58987d", "#8fc7ae"]),
}


def serif(s, x, y, size, fill, w="500", anchor="start"):
    """Texte en Cormorant Garamond italique, converti en tracés (aucune police à charger)."""
    font = GLYPHS[w]; k = size / font["upm"]; parts = []; cx = 0
    for ch in s:
        adv, d = font["glyphs"].get(ch) or font["glyphs"][" "]
        if d:
            parts.append(f'<path transform="translate({cx})" d="{d}"/>')
        cx += adv
    width = cx * k
    x0 = x - (width if anchor == "end" else width / 2 if anchor == "middle" else 0)
    return f'<g transform="translate({x0:.1f} {y}) scale({k:.5f})" fill="{fill}">{"".join(parts)}</g>'


def sans(s, x, y, size, fill, anchor="start", weight=400):
    return (f'<text x="{x}" y="{y}" font-family="{SANS}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{s}</text>')


def card(w, h, c, inner):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h}" width="{w:g}" height="{h}">'
            f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="14" fill="{c["bg"]}" stroke="{c["edge"]}"/>'
            f'{inner}</svg>')


def bar_v(x, y0, w, h, r=3):
    if h <= 0:
        return ""
    r = min(r, w / 2, h); y = y0 - h
    return (f"M{x:.1f} {y0}V{y+r:.1f}Q{x:.1f} {y:.1f} {x+r:.1f} {y:.1f}H{x+w-r:.1f}"
            f"Q{x+w:.1f} {y:.1f} {x+w:.1f} {y+r:.1f}V{y0}Z")


def bar_h(x0, y, w, h, r=3):
    if w <= 0:
        return ""
    r = min(r, h / 2, w); x = x0 + w
    return (f"M{x0} {y:.1f}H{x-r:.1f}Q{x:.1f} {y:.1f} {x:.1f} {y+r:.1f}V{y+h-r:.1f}"
            f"Q{x:.1f} {y+h:.1f} {x-r:.1f} {y+h:.1f}H{x0}Z")


def nb(n):
    return f"{n:,}".replace(",", " ")


def contributions(D, c):
    days, start, end = D["days"], D["start"], D["end"]
    best = run = 0; d = start
    while d <= end:
        run = run + 1 if days.get(d) else 0; best = max(best, run); d += dt.timedelta(days=1)
    rec = max(days, key=days.get)
    wday = collections.Counter()
    for d, v in days.items():
        wday[d.weekday()] += v
    nz = sorted(v for v in days.values() if v) or [1]
    q = [nz[int(len(nz) * f)] for f in (.25, .5, .75)]
    lvl = lambda v: 0 if v == 0 else 1 if v <= q[0] else 2 if v <= q[1] else 3 if v <= q[2] else 4

    W, H = 880, 298; o = [serif(nb(D["total"]), 36, 78, 54, c["ink"], "600"),
                          sans("contributions sur la dernière année", 40, 102, 14, c["muted"])]
    tiles = [(f"{best} jour{'s' if best > 1 else ''}", "meilleure série"),
             (f"{nb(days[rec])} en un jour", f"record · {rec.day} {MOIS[rec.month-1]}"),
             (JOURS[max(wday, key=wday.get)], "jour le plus actif")]
    for i, (v, l) in enumerate(tiles):
        x = 400 + i * 160
        o.append(f'<line x1="{x-18}" y1="44" x2="{x-18}" y2="104" stroke="{c["edge"]}"/>')
        o.append(serif(v, x, 76, 30 if len(v) < 12 else 26, c["ink"])); o.append(sans(l, x, 100, 12.5, c["muted"]))
    gx, gy, s, g = 70, 150, 12, 3
    first = start - dt.timedelta(days=start.weekday()); lastm = None
    for wk in range(53):
        for di in range(7):
            d = first + dt.timedelta(days=wk * 7 + di)
            if d < start or d > end:
                continue
            v = days.get(d, 0)
            o.append(f'<rect x="{gx+wk*(s+g)}" y="{gy+di*(s+g)}" width="{s}" height="{s}" rx="2.5" '
                     f'fill="{c["seq"][lvl(v)]}"><title>{d.isoformat()} : {v}</title></rect>')
            if di == 0 and d.month != lastm and d.day <= 7:
                lastm = d.month; o.append(sans(MOIS[d.month - 1], gx + wk * (s + g), gy - 9, 11.5, c["muted"]))
    for di, t in ((0, "lun"), (2, "mer"), (4, "ven")):
        o.append(sans(t, gx - 10, gy + di * (s + g) + 10, 11, c["muted"], "end"))
    ly = gy + 7 * (s + g) + 18; lx = gx + 48 * (s + g) - 34
    o.append(sans("Moins", lx - 8, ly + 10, 11, c["muted"], "end"))
    for i in range(5):
        o.append(f'<rect x="{lx+i*(s+g)}" y="{ly}" width="{s}" height="{s}" rx="2.5" fill="{c["seq"][i]}"/>')
    o.append(sans("Plus", lx + 5 * (s + g) + 4, ly + 10, 11, c["muted"]))
    o.append(sans(f"Mis à jour le {end.day} {MOIS[end.month-1]} {end.year}", gx, ly + 10, 11, c["faint"]))
    return card(W, H, c, "".join(o))


W_ROW, GAP, CH = 880, 12, 176  # même largeur que le graphe : les bords tombent alignés
CW = (W_ROW - 3 * GAP) / 4


def small_month(D, c):
    per = collections.Counter()
    for d, v in D["days"].items():
        per[(d.year, d.month)] += v
    ms = []; y, m = D["start"].year, D["start"].month
    while (y, m) <= (D["end"].year, D["end"].month):
        ms.append((y, m)); m += 1; y += m > 12; m = (m - 1) % 12 + 1
    o = [serif("Contributions par mois", 16, 30, 19, c["ink"])]
    x0, base, ph = 16, 146, 92; step = (CW - 32 - 2) / len(ms); bw = step * .7
    mx = max(per[k] for k in ms) or 1
    o.append(f'<line x1="{x0}" y1="{base}" x2="{CW-16}" y2="{base}" stroke="{c["edge"]}"/>')
    for i, k in enumerate(ms):
        v = per[k]; x = x0 + 2 + i * step; h = ph * v / mx
        o.append(f'<path d="{bar_v(x, base, bw, h, 2.5)}" fill="{c["acc"]}" fill-opacity="{1 if v == mx else .6}">'
                 f'<title>{MOIS[k[1]-1]} {k[0]} : {v}</title></path>')
        if v == mx:
            o.append(sans(nb(v), x + bw / 2, base - h - 5, 10, c["ink"], "end" if i > len(ms) - 3 else "middle", 600))
    a, b = ms[0], ms[-1]
    o.append(sans(f"{MOIS[a[1]-1]} {a[0]}", x0, base + 15, 9.5, c["muted"]))
    o.append(sans(f"{MOIS[b[1]-1]} {b[0]}", CW - 16, base + 15, 9.5, c["muted"], "end"))
    return card(CW, CH, c, "".join(o))


def small_hour(D, c):
    hours = D["hours"]; o = [serif("Quand je code", 16, 30, 19, c["ink"])]
    x0, base, ph = 16, 146, 92; step = (CW - 34) / 24; bw = step * .72; gap = step - bw
    mx = max(hours.values(), default=0) or 1; pk = max(hours, key=hours.get) if hours else None
    o.append(f'<line x1="{x0}" y1="{base}" x2="{CW-16}" y2="{base}" stroke="{c["edge"]}"/>')
    for hh in range(24):
        v = hours.get(hh, 0); x = x0 + 2 + hh * (bw + gap); h = ph * v / mx
        o.append(f'<path d="{bar_v(x, base, bw, h, 2)}" fill="{c["acc"]}" fill-opacity="{1 if hh == pk else .6}">'
                 f'<title>{hh} h : {v}</title></path>')
        if hh in (0, 12):
            o.append(sans(f"{hh} h", x, base + 15, 9.5, c["muted"]))
        if hh == pk:
            o.append(sans(f"pic à {hh} h", x + bw / 2, base - h - 5, 10, c["ink"],
                          "end" if hh > 19 else "start" if hh < 4 else "middle", 600))
    o.append(sans("23 h", CW - 16, base + 15, 9.5, c["muted"], "end"))
    return card(CW, CH, c, "".join(o))


def small_lang(D, c):
    top = D["langs"].most_common(); tot = sum(v for _, v in top) or 1
    items = top[:2] + ([("Autres", sum(v for _, v in top[2:]))] if len(top) > 2 else [])
    o = [serif("Langages", 16, 30, 19, c["ink"]), sans("tous mes dépôts", 16, 47, 9.5, c["muted"])]
    mx = max((v for _, v in items), default=1) or 1
    for i, (k, v) in enumerate(items):
        y = 70 + i * 34
        o.append(sans(k, 16, y, 11, c["ink"], weight=500))
        o.append(sans(f"{round(100 * v / tot)} %", CW - 16, y, 10.5, c["muted"], "end"))
        o.append(f'<rect x="16" y="{y+6}" width="{CW-32}" height="8" rx="3" fill="{c["hair"]}"/>')
        o.append(f'<path d="{bar_h(16, y + 6, (CW - 32) * v / mx, 8)}" fill="{c["acc"]}"/>')
    return card(CW, CH, c, "".join(o))


def small_nums(D, c):
    o = [serif("En chiffres", 16, 30, 19, c["ink"]), sans("eLens Platform", 16, 47, 9.5, c["muted"])]
    for i, (v, l) in enumerate(D["numbers"]):
        x = 16 + (i % 2) * 98; y = 92 + (i // 2) * 52
        o.append(serif(nb(v), x, y, 28, c["acc"], "600")); o.append(sans(l, x + 1, y + 16, 10, c["muted"]))
    return card(CW, CH, c, "".join(o))


def row(cards, c):
    """Les petites cartes côte à côte, dans une seule image de la largeur du graphe."""
    global CW
    CW = (W_ROW - (len(cards) - 1) * GAP) / len(cards)
    parts = []
    for i, fn in enumerate(cards):
        svg = fn(c).replace('<svg xmlns="http://www.w3.org/2000/svg" ', f'<svg x="{i * (CW + GAP):.1f}" y="0" ', 1)
        parts.append(svg)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W_ROW} {CH}" width="{W_ROW}" height="{CH}">'
            f'{"".join(parts)}</svg>')


def render(D):
    ASSETS.mkdir(exist_ok=True)
    small = [small_month, small_hour, small_lang] + ([small_nums] if D["numbers"] else [])
    for theme, c in TH.items():
        (ASSETS / f"contributions-{theme}.svg").write_text(contributions(D, c), encoding="utf-8")
        (ASSETS / f"cartes-{theme}.svg").write_text(row([lambda c, f=f: f(D, c) for f in small], c), encoding="utf-8")


if __name__ == "__main__":
    render(fetch(dt.datetime.now(TZ).date()))
    print("graphiques régénérés dans", ASSETS)
