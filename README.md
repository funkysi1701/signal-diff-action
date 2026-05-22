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
| `github_token` | no | `${{ github.token }}` | GitHub token for PR comments and code-change collection |
| `collect_code_changes` | no | `true` | After crawl completes, summarize git changes and attach to the job |
| `max_changed_files` | no | `50` | Max changed file paths in the summary |
| `baseline_ref` | no | | Baseline commit for push/dispatch (overrides `GET /api/ci/last-run`) |
| `repository` | no | `${{ github.repository }}` | Repository slug (owner/repo) |
| `ref_name` | no | `${{ github.ref }}` | Git ref for this run |
| `commit_sha` | no | `${{ github.sha }}` | Commit SHA for this run |
| `workflow_run_id` | no | `${{ github.run_id }}` | GitHub workflow run ID |
| `workflow_run_url` | no | auto | GitHub workflow run URL |
| `pull_request_number` | no | auto | PR number associated with this run |
| `max_new_findings_in_comment` | no | `5` | Max new run-diff findings listed in the PR comment |

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
| `code_changes_collected` | `true` when a git change summary was PATCHed to the job |

## Permissions

Workflows need at least:

```yaml
permissions:
  contents: read
```

Add `pull-requests: write` when `comment_on_pr: true`.

Code change collection uses the [GitHub Compare API](https://docs.github.com/en/rest/commits/commits#compare-two-commits) with `github_token` (default `${{ github.token }}`). **Fork pull requests** and missing `contents: read` skip the summary with a log line; the crawl still completes.

## Code change summary

When `collect_code_changes` is `true` (default), after the crawl reaches a terminal state the action:

1. Resolves a **baseline** commit:
   - **pull_request:** `github.event.pull_request.base.sha`
   - **push / workflow_dispatch:** `GET {api_base_url}/api/ci/last-run?repository=...&sitemapUrl=...`, or `baseline_ref` when set
2. Calls GitHub Compare (`base...head`) and caps paths/commits.
3. `PATCH {api_base_url}/api/jobs/{jobId}/ci-changes` with the same CI API key as the crawl trigger.

Failures in this step are **non-fatal** (logged only).

## Fail modes

| Mode | Behaviour |
|---|---|
| `none` | Never fails the workflow based on crawl results |
| `error` | Fails if any errors are found (default) |
| `errorOrWarning` | Fails if any errors or warnings are found |

The workflow always fails if the crawl itself fails to complete.

## PR comments

When `comment_on_pr` is `true` on `pull_request` events, the action fetches the completed job (`GET` status URL), then posts a **best-effort** comment (`continue-on-error: true`). The comment includes crawl counts, a link to `/scan/{jobId}`, the workflow run link, and when available:

- **Run diff** headline and a capped list of new findings (`runDiff.newFindings`)
- **Code changes** compare link and changed-file count (`ciCodeChanges`)

Comment posting never fails the workflow.

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
      - uses: funkysi1701/signal-diff-action@v1
        with:
          api_base_url: ${{ secrets.SIGNALDIFF_API_BASE_URL }}
          api_key: ${{ secrets.SIGNALDIFF_CI_API_KEY }}
          sitemap_url: https://example.com/sitemap.xml
          fail_mode: error
          comment_on_pr: ${{ github.event_name == 'pull_request' }}
          collect_code_changes: true
          github_token: ${{ github.token }}
```

Note: no `actions/checkout` step is needed — this action is referenced by name, not local path.

## Setup

### 1. Add secrets to your repository

Go to **Settings → Secrets and variables → Actions** and add:

- `SIGNALDIFF_API_BASE_URL` — your SeoChecker API host URL
- `SIGNALDIFF_CI_API_KEY` — a CI API key from your SeoChecker instance
