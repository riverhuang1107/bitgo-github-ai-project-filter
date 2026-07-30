from __future__ import annotations

import httpx

from .hackernews import github_full_name_from_url
from .models import Repository


SEARCH_URL = "https://registry.npmjs.org/-/v1/search"
SOURCE_NAME = "npm AI package search"
SEARCH_QUERIES = ("keywords:ai", "keywords:llm", "keywords:machine-learning")


class NpmClient:
    """Read GitHub repository links from public npm AI package search results."""

    def __init__(self, timeout: float = 20.0):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def trending_repositories(self, candidate_limit: int) -> list[Repository]:
        repositories: list[Repository] = []
        seen: set[str] = set()
        for query in SEARCH_QUERIES:
            response = self.client.get(
                SEARCH_URL, params={"text": query, "size": candidate_limit}
            )
            response.raise_for_status()
            payload = response.json()
            packages = payload.get("objects") if isinstance(payload, dict) else None
            if not isinstance(packages, list):
                raise RuntimeError("npm package search returned an invalid payload")
            for result in packages:
                package = result.get("package") if isinstance(result, dict) else None
                if not isinstance(package, dict):
                    continue
                links = package.get("links")
                repository_url = links.get("repository") if isinstance(links, dict) else None
                full_name = github_full_name_from_url(repository_url)
                if full_name is None or full_name.casefold() in seen:
                    continue
                seen.add(full_name.casefold())
                name = package.get("name")
                description = package.get("description")
                repositories.append(
                    Repository(
                        full_name=full_name,
                        url=f"https://github.com/{full_name}",
                        description=(
                            f"npm package {name}: {description}".strip()
                            if isinstance(name, str) and isinstance(description, str)
                            else str(description or name or "")
                        ),
                        trending_rank=len(repositories) + 1,
                        source=SOURCE_NAME,
                    )
                )
                if len(repositories) >= candidate_limit:
                    return repositories
        return repositories

    def close(self) -> None:
        self.client.close()
