import httpx

from github_ai_daily.github import GitHubClient
from github_ai_daily.models import Repository


TRENDING_HTML = """
<article class="Box-row">
  <h2><a href="/owner/repo"> owner / repo </a></h2>
  <p>An AI toolkit</p>
  <span itemprop="programmingLanguage">Python</span>
  <span class="d-inline-block float-sm-right">1,234 stars today</span>
</article>
"""


def test_parse_and_enrich_trending():
    def handler(request: httpx.Request):
        if request.url.host == "github.com":
            return httpx.Response(200, text=TRENDING_HTML)
        return httpx.Response(
            200,
            json={
                "description": "An AI toolkit",
                "language": "Python",
                "stargazers_count": 10000,
                "forks_count": 800,
                "topics": ["ai", "agents"],
                "updated_at": "2026-06-25T00:00:00Z",
                "html_url": "https://github.com/owner/repo",
            },
        )

    github = GitHubClient()
    github.client = httpx.Client(transport=httpx.MockTransport(handler))
    repos = github.enrich(github.trending())
    assert repos[0].full_name == "owner/repo"
    assert repos[0].stars_today == 1234
    assert repos[0].stars == 10000
    assert repos[0].topics == ["ai", "agents"]


def test_enrich_can_skip_removed_external_repository():
    github = GitHubClient()
    github.client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))
    )

    repositories = github.enrich(
        [Repository("removed/repository", "https://github.com/removed/repository")],
        skip_missing=True,
    )

    assert repositories == []


def test_enrich_continues_with_unenriched_candidates_after_rate_limit():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/one"):
            return httpx.Response(
                200,
                json={
                    "description": "Enriched",
                    "stargazers_count": 10,
                    "forks_count": 2,
                },
            )
        return httpx.Response(403, text="API rate limit exceeded")

    github = GitHubClient()
    github.client = httpx.Client(transport=httpx.MockTransport(handler))
    second = Repository("owner/two", "https://github.com/owner/two", description="From npm")

    repositories = github.enrich(
        [Repository("owner/one", "https://github.com/owner/one"), second],
        tolerate_rate_limit=True,
    )

    assert len(repositories) == 2
    assert repositories[0].description == "Enriched"
    assert repositories[1].description == "From npm"
    assert github.enrichment_warning is not None
    assert "GITHUB_TOKEN" in github.enrichment_warning
