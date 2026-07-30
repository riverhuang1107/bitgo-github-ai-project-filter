import httpx

from github_ai_daily.lobsters import LobstersClient, SOURCE_NAME as LOBSTERS_SOURCE
from github_ai_daily.npm import NpmClient, SOURCE_NAME as NPM_SOURCE


def test_reads_github_repository_from_lobsters():
    client = LobstersClient()
    client.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=[
                    {"title": "Project release", "url": "https://github.com/example/lobster"},
                    {"title": "Article", "url": "https://example.com/article"},
                ],
            )
        )
    )

    repositories = client.trending_repositories(candidate_limit=10)

    assert [(repository.full_name, repository.source) for repository in repositories] == [
        ("example/lobster", LOBSTERS_SOURCE)
    ]


def test_reads_github_repository_from_npm_search():
    client = NpmClient()
    client.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "objects": [
                        {
                            "package": {
                                "name": "ai-tool",
                                "description": "An AI package",
                                "links": {"repository": "https://github.com/example/npm-tool"},
                            }
                        },
                        {"package": {"name": "no-repository", "links": {}}},
                    ]
                },
            )
        )
    )

    repositories = client.trending_repositories(candidate_limit=10)

    assert [(repository.full_name, repository.source) for repository in repositories] == [
        ("example/npm-tool", NPM_SOURCE)
    ]
    assert repositories[0].description == "npm package ai-tool: An AI package"
