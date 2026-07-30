from __future__ import annotations

import httpx

from .hackernews import github_full_name_from_url
from .models import Repository


HOTTEST_URL = "https://lobste.rs/hottest.json"
SOURCE_NAME = "Lobsters Hottest"


class LobstersClient:
    """Read GitHub repository links from the public Lobsters hottest feed."""

    def __init__(self, timeout: float = 20.0):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def trending_repositories(self, candidate_limit: int) -> list[Repository]:
        response = self.client.get(HOTTEST_URL)
        response.raise_for_status()
        stories = response.json()
        if not isinstance(stories, list):
            raise RuntimeError("Lobsters hottest feed returned an invalid payload")
        repositories: list[Repository] = []
        for rank, story in enumerate(stories, start=1):
            if not isinstance(story, dict):
                continue
            full_name = github_full_name_from_url(story.get("url"))
            if full_name is None:
                continue
            title = story.get("title")
            repositories.append(
                Repository(
                    full_name=full_name,
                    url=f"https://github.com/{full_name}",
                    description=title.strip() if isinstance(title, str) else "",
                    trending_rank=rank,
                    source=SOURCE_NAME,
                )
            )
            if len(repositories) >= candidate_limit:
                break
        return repositories

    def close(self) -> None:
        self.client.close()
