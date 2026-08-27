import os
import re
import sys

import requests

USERNAME = "guilhermelcosta"
TOP_N = 6
BAR_WIDTH = 20
README_PATH = "README.md"
START_MARKER = "<!-- LANG-STATS:START -->"
END_MARKER = "<!-- LANG-STATS:END -->"

API_URL = "https://api.github.com"


def _headers():
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repos():
    """Fetch all public, non-fork repositories owned by USERNAME."""
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{API_URL}/users/{USERNAME}/repos",
            headers=_headers(),
            params={"per_page": 100, "page": page, "type": "owner"},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return [r for r in repos if not r.get("fork") and not r.get("archived")]


def fetch_languages(repo_full_name):
    resp = requests.get(f"{API_URL}/repos/{repo_full_name}/languages", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def aggregate_languages():
    totals = {}
    for repo in fetch_repos():
        langs = fetch_languages(repo["full_name"])
        for lang, byte_count in langs.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    return totals


def render_bar(percentage, width=BAR_WIDTH):
    filled = round(width * percentage / 100)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def generate_block(totals):
    total_bytes = sum(totals.values())
    if total_bytes == 0:
        return "No language data available."

    top_langs = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:TOP_N]
    name_width = max([len(name) for name, _ in top_langs] + [len("Time")])

    lines = [f"{'Time'.ljust(name_width)} {render_bar(100)} 100%", ""]
    for name, byte_count in top_langs:
        pct = byte_count / total_bytes * 100
        lines.append(f"{name.ljust(name_width)} {render_bar(pct)} {pct:02.0f}%")

    return "\n".join(lines)


def update_readme(block):
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)

    if not pattern.search(content):
        print(f"Marcadores {START_MARKER} / {END_MARKER} não encontrados no {README_PATH}.")
        sys.exit(1)

    replacement = f"{START_MARKER}\n```text\n{block}\n```\n{END_MARKER}"
    new_content = pattern.sub(replacement, content)

    if new_content == content:
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def main():
    totals = aggregate_languages()
    block = generate_block(totals)
    changed = update_readme(block)
    print("README atualizado." if changed else "Sem mudanças nos stats.")


if __name__ == "__main__":
    main()
