import httpx

from github_ai_daily.hackernews import HackerNewsClient, SOURCE_NAME


def test_reads_github_repositories_from_top_stories():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/topstories.json"):
            return httpx.Response(200, json=[101, 102, 103])
        if request.url.path.endswith("/101.json"):
            return httpx.Response(
                200,
                json={
                    "type": "story",
                    "title": "Useful AI project",
                    "url": "https://github.com/example/project/releases",
                },
            )
        if request.url.path.endswith("/102.json"):
            return httpx.Response(
                200,
                json={"type": "story", "title": "Not a repository", "url": "https://example.com"},
            )
        return httpx.Response(
            200,
            json={"type": "story", "title": "GitHub topic", "url": "https://github.com/topics/ai"},
        )

    client = HackerNewsClient()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))

    repositories = client.trending_repositories(story_limit=3)

    assert [(repo.full_name, repo.source) for repo in repositories] == [
        ("example/project", SOURCE_NAME)
    ]
    assert repositories[0].description == "Useful AI project"
