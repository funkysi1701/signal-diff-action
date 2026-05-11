# Signal Diff Crawl Action

Trigger a Signal Diff CI crawl from any GitHub Actions workflow, poll until completion, and optionally fail the build based on crawl results.

## Usage

```yaml
- uses: funkysi1701/signal-diff-action@v1
  with:
    api_base_url: ${{ secrets.SIGNALDIFF_API_BASE_URL }}
    api_key: ${{ secrets.SIGNALDIFF_CI_API_KEY }}
    sitemap_url: https://example.com/sitemap.xml
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `api_base_url` | yes | | Base URL of the Signal Diff API host |
| `api_key` | yes | | Signal Diff CI API key |
| `sitemap_url` | yes | | Sitemap URL to crawl |
| `fail_mode` | no | `error` | Failure policy: `none`, `error`, or `errorOrWarning` |
| `comment_on_pr` | no | `false` | Post a crawl summary comment on PRs |
| `github_token` | no | | GitHub token for PR comments (required when `comment_on_pr=true`) |
| `repository` | no | `${{ github.repository }}` | Repository slug (owner/repo) |
| `ref_name` | no | `${{ github.ref }}` | Git ref for this run |
| `commit_sha` | no | `${{ github.sha }}` | Commit SHA for this run |
| `workflow_run_id` | no | `${{ github.run_id }}` | GitHub workflow run ID |
| `workflow_run_url` | no | auto | GitHub workflow run URL |
| `pull_request_number` | no | auto | PR number associated with this run |

## Outputs

| Output | Description |
|---|---|
| `job_id` | Signal Diff job ID |
| `trigger_url` | Resolved trigger endpoint URL used to start the crawl |
| `status_url` | Status URL for the crawl job |
| `status` | Final crawl status (`complete` or `failed`) |
| `errors` | Final crawl error count |
| `warnings` | Final crawl warning count |
| `pages` | Final crawled page count |

## Fail modes

| Mode | Behaviour |
|---|---|
| `none` | Never fails the workflow based on crawl results |
| `error` | Fails if any errors are found (default) |
| `errorOrWarning` | Fails if any errors or warnings are found |

The workflow always fails if the crawl itself fails to complete.

## Full example

```yaml
name: Signal Diff Crawl
on:
  pull_request:
  workflow_dispatch:

jobs:
  crawl:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: funkysi1701/signal-diff-actio@v1
        with:
          api_base_url: ${{ secrets.SIGNALDIFF_API_BASE_URL }}
          api_key: ${{ secrets.SIGNALDIFF_CI_API_KEY }}
          sitemap_url: https://example.com/sitemap.xml
          fail_mode: error
          comment_on_pr: ${{ github.event_name == 'pull_request' }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Note: no `actions/checkout` step is needed — this action is referenced by name, not local path.

## Setup

### 1. Add secrets to your repository

Go to **Settings → Secrets and variables → Actions** and add:

- `SIGNALDIFF_API_BASE_URL` — your SeoChecker API host URL
- `SIGNALDIFF_CI_API_KEY` — a CI API key from your SeoChecker instance
