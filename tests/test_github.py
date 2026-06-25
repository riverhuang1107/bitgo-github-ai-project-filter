import httpx

from github_ai_daily.github import GitHubClient


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

