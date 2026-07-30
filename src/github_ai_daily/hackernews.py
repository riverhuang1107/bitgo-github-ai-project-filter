from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import httpx

from .models import Repository


TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
SOURCE_NAME = "Hacker News Top Stories"
MAX_STORIES = 50
MAX_CANDIDATES = 20
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_INVALID_OWNERS = {
    "about", "collections", "events", "explore", "features", "join", "login",
    "marketplace", "orgs", "search", "settings", "sponsors", "topics",
}
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


class HackerNewsClient:
    """Read GitHub repository links from the public Hacker News Top Stories feed."""

    def __init__(self, timeout: float = 20.0):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def trending_repositories(
        self, story_limit: int = MAX_STORIES, candidate_limit: int = MAX_CANDIDATES
    ) -> list[Repository]:
        response = self.client.get(TOP_STORIES_URL)
        response.raise_for_status()
        story_ids = response.json()
        if not isinstance(story_ids, list):
            raise RuntimeError("Hacker News Top Stories returned an invalid payload")

        repositories: list[Repository] = []
        for rank, story_id in enumerate(story_ids[:story_limit], start=1):
            if not isinstance(story_id, int):
                continue
            response = self.client.get(ITEM_URL.format(story_id=story_id))
            response.raise_for_status()
            repository = repository_from_story(response.json(), rank)
            if repository is not None:
                repositories.append(repository)
            if len(repositories) >= candidate_limit:
                break
        return repositories

    def close(self) -> None:
        self.client.close()


def repository_from_story(story: object, rank: int) -> Repository | None:
    if not isinstance(story, dict) or story.get("type") != "story":
        return None
    full_name = github_full_name_from_url(story.get("url"))
    if full_name is None:
        return None
    title = story.get("title")
    return Repository(
        full_name=full_name,
        url=f"https://github.com/{full_name}",
        description=title.strip() if isinstance(title, str) else "",
        trending_rank=rank,
        source=SOURCE_NAME,
    )


def github_full_name_from_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.hostname is None or parsed.hostname.casefold() not in _GITHUB_HOSTS:
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repository = parts[:2]
    if repository.endswith(".git"):
        repository = repository[:-4]
    if (
        owner.casefold() in _INVALID_OWNERS
        or not _GITHUB_NAME.fullmatch(owner)
        or not _GITHUB_NAME.fullmatch(repository)
    ):
        return None
    return f"{owner}/{repository}"
