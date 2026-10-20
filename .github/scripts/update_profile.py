"""Regenerate dark_mode.svg and light_mode.svg with live GitHub stats.

Runs daily via GitHub Actions. Standard library only.
"""

import html
import json
import os
import urllib.request
from datetime import date, datetime, timezone

USER = "guilhermelcosta"
API = "https://api.github.com"

# Static profile facts. Edit these when they change.
ROLE = "Senior Software Engineer"
HOST = "NTT DATA"
LOCATION = "Belo Horizonte, BR"
OS = "Linux"

WIDTH = 840
HEIGHT = 445
PAD = 28
FONT = "Consolas, Menlo, monospace"

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
PRIVATE_TOKEN = os.environ.get("ACCESS_TOKEN") or TOKEN

PALETTES = {
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "text": "#c9d1d9",
        "key": "#ffa657",
        "dim": "#484f58",
        "accent": "#58a6ff",
        "green": "#3fb950",
        "red": "#f85149",
        "heat": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "text": "#24292f",
        "key": "#953800",
        "dim": "#afb8c1",
        "accent": "#0969da",
        "green": "#1a7f37",
        "red": "#cf222e",
        "heat": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
}


def graphql(query, variables=None, token=None):
    req = urllib.request.Request(
        f"{API}/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Authorization": f"Bearer {token or TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{USER}-profile-card",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


CORE_QUERY = """
query($login: String!) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {
      totalCount
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { contributionCount date weekday }
        }
      }
    }
  }
}
"""

LOC_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, author: {id: $id}, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes { additions deletions }
          }
        }
      }
    }
  }
}
"""


def yearly_commits(created_year):
    aliases = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", '
        f'to: "{y + 1}-01-01T00:00:00Z") '
        "{ totalCommitContributions restrictedContributionsCount }"
        for y in range(created_year, datetime.now(timezone.utc).year + 1)
    )
    data = graphql(f'query {{ user(login: "{USER}") {{ {aliases} }} }}')["user"]
    return sum(
        year["totalCommitContributions"] + year["restrictedContributionsCount"]
        for year in data.values()
    )


def lines_of_code(repo_names, user_id):
    added = deleted = 0
    for name in repo_names:
        cursor = None
        try:
            while True:
                data = graphql(
                    LOC_QUERY,
                    {"owner": USER, "name": name, "id": user_id, "cursor": cursor},
                    token=PRIVATE_TOKEN,
                )["repository"]["defaultBranchRef"]
                if data is None:
                    break  # empty repository
                history = data["target"]["history"]
                added += sum(node["additions"] for node in history["nodes"])
                deleted += sum(node["deletions"] for node in history["nodes"])
                if not history["pageInfo"]["hasNextPage"]:
                    break
                cursor = history["pageInfo"]["endCursor"]
        except Exception as exc:  # keep the card alive if one repo fails
            print(f"lines_of_code {name}: {exc}")
    return added, deleted


def fetch_stats():
    user = graphql(CORE_QUERY, {"login": USER})["user"]
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))

    languages = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            languages[name] = languages.get(name, 0) + edge["size"]

    added, deleted = lines_of_code(
        [repo["name"] for repo in user["repositories"]["nodes"]], user["id"]
    )

    return {
        "created": created,
        "repos": user["repositories"]["totalCount"],
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(repo["stargazerCount"] for repo in user["repositories"]["nodes"]),
        "followers": user["followers"]["totalCount"],
        "commits": yearly_commits(created.year),
        "loc_add": added,
        "loc_del": deleted,
        "languages": sorted(languages.items(), key=lambda item: item[1], reverse=True),
        "calendar": user["contributionsCollection"]["contributionCalendar"],
        "contributions": user["contributionsCollection"]["contributionCalendar"][
            "totalContributions"
        ],
    }


def duration(start, today):
    years = today.year - start.year
    months = today.month - start.month
    if today.day < start.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    if years == 0:
        return f"{months} mos"
    return f"{years} yrs, {months} mos"


def number(value):
    return f"{value:,}"


def kv(key, value, width):
    """Key/value with dot leaders, sized in monospace characters."""
    dots = "." * max(width - len(key) - len(str(value)) - 3, 1)
    return [(f"{key}: ", "key"), (f"{dots} ", "dim"), (str(value), "text")]


def loc_segments(stats, width):
    added = number(stats["loc_add"])
    deleted = number(stats["loc_del"])
    net = number(stats["loc_add"] - stats["loc_del"])
    plain = f"Lines of Code: {net} ( +{added}, -{deleted} )"
    dots = "." * max(width - len(plain) - 1, 1)
    return [
        ("Lines of Code: ", "key"),
        (f"{dots} ", "dim"),
        (net, "text"),
        (" ( ", "dim"),
        (f"+{added}", "green"),
        (", ", "dim"),
        (f"-{deleted}", "red"),
        (" )", "dim"),
    ]


def language_segments(stats):
    languages = stats["languages"]
    total = sum(size for _, size in languages)
    if not total:
        return [("n/a", "text")]

    top = languages[:5]
    rest = sum(size for _, size in languages[5:])
    parts = []
    for index, (name, size) in enumerate(top):
        if index:
            parts.append(("  ·  ", "dim"))
        parts.append((name, "accent"))
        parts.append((f" {size / total * 100:.0f}%", "text"))
    if rest:
        parts.append(("  ·  ", "dim"))
        parts.append(("Other", "accent"))
        parts.append((f" {rest / total * 100:.0f}%", "text"))
    return parts


def level(count):
    if count == 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 9:
        return 3
    return 4


def heatmap(weeks, x0, y0, palette):
    cell, gap = 11, 3
    parts = []
    for column, week in enumerate(weeks[-53:]):
        for day in week["contributionDays"]:
            x = x0 + column * (cell + gap)
            y = y0 + day["weekday"] * (cell + gap)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{palette["heat"][level(day["contributionCount"])]}"/>'
            )
    return parts


def month_labels(weeks, x0, y0, palette):
    labels = []
    current = None
    for column, week in enumerate(weeks[-53:]):
        day = date.fromisoformat(week["contributionDays"][0]["date"])
        if day.month == current:
            continue
        current = day.month
        labels.append(
            f'<text x="{x0 + column * 14}" y="{y0}" fill="{palette["dim"]}" '
            f'font-size="10px">{day.strftime("%b")}</text>'
        )
    return labels


def render(mode, stats):
    p = PALETTES[mode]
    today = datetime.now(timezone.utc).date()
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}" font-size="13px" '
        f'role="img" aria-label="Guilherme Costa GitHub stats">',
        "<title>Guilherme Costa - GitHub stats</title>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="10" '
        f'fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]

    out.append(
        f'<text x="{PAD}" y="42" fill="{p["accent"]}" font-size="14px">'
        f"{USER}@github</text>"
    )
    out.append(
        f'<line x1="190" y1="38" x2="665" y2="38" stroke="{p["border"]}"/>'
    )
    out.append(
        f'<text x="{WIDTH - PAD}" y="42" text-anchor="end" fill="{p["dim"]}" '
        f'font-size="11px">updated {today.isoformat()}</text>'
    )
    out.append(
        f'<line x1="{PAD}" y1="58" x2="{WIDTH - PAD}" y2="58" stroke="{p["border"]}"/>'
    )

    left = [
        kv("Role", ROLE, 50),
        kv("Host", HOST, 50),
        kv("Location", LOCATION, 50),
        kv("OS", OS, 50),
        kv("Uptime", f"{duration(stats['created'].date(), today)} on GitHub", 50),
    ]
    right = [
        kv("Repos", f"{stats['repos']} {{contributed: {stats['contributed']}}}", 48),
        kv("Stars", number(stats["stars"]), 48),
        kv("Commits", number(stats["commits"]), 48),
        kv("Followers", number(stats["followers"]), 48),
        loc_segments(stats, 48),
    ]

    for index, (left_row, right_row) in enumerate(zip(left, right)):
        y = 86 + index * 21
        for x, segments in ((PAD, left_row), (440, right_row)):
            spans = "".join(
                f'<tspan fill="{p[color]}">{html.escape(text)}</tspan>'
                for text, color in segments
            )
            out.append(f'<text x="{x}" y="{y}" xml:space="preserve">{spans}</text>')

    # Languages
    out.append(
        f'<text x="{PAD}" y="208" fill="{p["accent"]}">─ languages </text>'
    )
    out.append(
        f'<line x1="140" y1="204" x2="{WIDTH - PAD}" y2="204" stroke="{p["border"]}"/>'
    )
    spans = "".join(
        f'<tspan fill="{p[color]}">{html.escape(text)}</tspan>'
        for text, color in language_segments(stats)
    )
    out.append(f'<text x="{PAD}" y="236" xml:space="preserve">{spans}</text>')

    # Contributions
    out.append(
        f'<text x="{PAD}" y="272" fill="{p["accent"]}">─ contributions </text>'
    )
    out.append(
        f'<line x1="172" y1="268" x2="{WIDTH - PAD}" y2="268" stroke="{p["border"]}"/>'
    )
    out.extend(month_labels(stats["calendar"]["weeks"], PAD, 296, p))
    out.extend(heatmap(stats["calendar"]["weeks"], PAD, 306, p))

    out.append(
        f'<text x="{PAD}" y="424" fill="{p["text"]}">{number(stats["contributions"])}'
        f'<tspan fill="{p["dim"]}"> contributions in the last year</tspan></text>'
    )

    legend_x = WIDTH - PAD - 144
    out.append(
        f'<text x="{legend_x}" y="424" fill="{p["dim"]}" font-size="11px">Less</text>'
    )
    for index, color in enumerate(p["heat"]):
        out.append(
            f'<rect x="{legend_x + 34 + index * 14}" y="414" width="11" height="11" '
            f'rx="2" fill="{color}"/>'
        )
    out.append(
        f'<text x="{WIDTH - PAD}" y="424" text-anchor="end" fill="{p["dim"]}" '
        f'font-size="11px">More</text>'
    )

    out.append("</svg>")
    return "\n".join(out)


def main():
    stats = fetch_stats()
    print("stats:", {k: v for k, v in stats.items() if k not in ("calendar", "languages")})
    for mode in PALETTES:
        with open(f"{mode}_mode.svg", "w", encoding="utf-8") as handle:
            handle.write(render(mode, stats))
        print(f"wrote {mode}_mode.svg")


if __name__ == "__main__":
    main()
