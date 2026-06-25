from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from .models import Repository


TRENDING_URL = "https://github.com/trending"
API_URL = "https://api.github.com/repos"


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 20.0):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-ai-daily/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=timeout, follow_redirects=True)

    def trending(self, since: str = "daily") -> list[Repository]:
        response = self.client.get(TRENDING_URL, params={"since": since})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        repos: list[Repository] = []
        for rank, article in enumerate(soup.select("article.Box-row"), start=1):
            anchor = article.select_one("h2 a")
            if not anchor:
                continue
            full_name = re.sub(r"\s+", "", anchor.get_text(strip=True))
            description_node = article.select_one("p")
            language_node = article.select_one("[itemprop=programmingLanguage]")
            today = 0
            for span in article.select("span.d-inline-block.float-sm-right"):
                match = re.search(r"([\d,]+)\s+stars?\s+today", span.get_text(" ", strip=True))
                if match:
                    today = int(match.group(1).replace(",", ""))
            repos.append(
                Repository(
                    full_name=full_name,
                    url=f"https://github.com/{full_name}",
                    description=description_node.get_text(" ", strip=True) if description_node else "",
                    language=language_node.get_text(strip=True) if language_node else "",
                    stars_today=today,
                    trending_rank=rank,
                )
            )
        if not repos:
            raise RuntimeError("GitHub Trending returned no repositories; page structure may have changed")
        return repos

    def enrich(self, repos: list[Repository]) -> list[Repository]:
        enriched: list[Repository] = []
        for repo in repos:
            response = self.client.get(f"{API_URL}/{repo.full_name}")
            response.raise_for_status()
            data = response.json()
            repo.description = data.get("description") or repo.description
            repo.language = data.get("language") or repo.language
            repo.stars = int(data.get("stargazers_count", 0))
            repo.forks = int(data.get("forks_count", 0))
            repo.topics = list(data.get("topics") or [])
            repo.updated_at = data.get("updated_at") or ""
            repo.url = data.get("html_url") or repo.url
            enriched.append(repo)
        return enriched

    def close(self) -> None:
        self.client.close()

