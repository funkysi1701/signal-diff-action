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
| `execution_mode` | no | `cloud` | Crawl route: `cloud` (hosted) or `agent` (customer agent pool) |
| `agent_pool_id` | no | | Agent pool when `execution_mode` is `agent` (omit for default pool) |
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
| `risk_score_enabled` | no | `true` | Include rule-based risk score in the PR comment summary |

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

## Customer agent routing

Set `execution_mode: agent` to queue the crawl for a **customer agent** instead of Signal Diff cloud execution. The action sends `executionMode` and optional `agentPoolId` on `POST {api_base_url}/api/trigger/ci` (same fields as the API’s CI trigger body).

Requirements:

1. **API:** Agent routing enabled (`Features:EnableAgentRouting=true` on the Signal Diff API).
2. **Agent:** An enrolled agent process running with `AgentPoolId` matching `agent_pool_id` (empty string matches the default pool).
3. **Tenant:** The CI API key’s user must own the job; agents only claim jobs for their tenant.

Agent jobs stay `pending` until an agent claims them, then move to `running` and finally `complete` or `failed`. The action polls for up to **30 minutes**; keep an agent online for CI or the workflow may time out.

```yaml
- uses: funkysi1701/signal-diff-action@v1.6
  with:
    api_base_url: ${{ secrets.SIGNALDIFF_API_BASE_URL }}
    api_key: ${{ secrets.SIGNALDIFF_CI_API_KEY }}
    sitemap_url: https://example.com/sitemap.xml
    execution_mode: agent
    agent_pool_id: production
```

## PR comments

When `comment_on_pr` is `true` on `pull_request` events, the action fetches the completed job (`GET` status URL), then posts a **best-effort** comment (`continue-on-error: true`). The comment is a decision-focused **Signal Diff Report**:

1. **Verdict** — pass/fail for your `fail_mode` plus severity (`Critical` / `Warning` / `Info` / `Improved` / `Compared`)
2. **Summary table** — rule-based risk score (0–10, Low/Medium/High), SEO errors/warnings, new vs resolved findings, files changed, pages crawled
3. **Files requiring review** — top high-attention changed paths with human-readable reasons (auth, payment, migrations, production config, etc.)
4. **SEO findings (vs baseline)** — headline, impact summary, grouped new findings, optional field-level example, baseline before/after counts
5. **Repository changes** — GitHub compare link (separate from SEO findings)
6. **Links** — Signal Diff scan URL and workflow run

The same report is appended to the GitHub Actions step summary. Comment posting never fails the workflow.

### Risk score

When `risk_score_enabled` is `true` (default), the summary table includes a **rule-based PR risk score** (no AI). The score combines:

- **Code-change signals** — keyword weights on changed paths (`auth`, `payment`, `migration`, `appsettings`, etc.) and directory/file pattern boosts (migrations, auth/payment folders, production config).
- **SEO signals** — new run-diff findings (higher weight for new errors than warnings), current crawl error/warning counts, and whether your `fail_mode` would fail the workflow.

Scores are normalized to **0–10** with labels **Low** (🟢), **Medium** (🟡), and **High** (🔴). Docs-only or test-only PRs score lower than changes touching production code or config. Set `risk_score_enabled: false` to omit the row; the score never fails the workflow (use `fail_mode` for that).

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
      - uses: funkysi1701/signal-diff-action@v1.6
        with:
          api_base_url: ${{ secrets.SIGNALDIFF_API_BASE_URL }}
          api_key: ${{ secrets.SIGNALDIFF_CI_API_KEY }}
          sitemap_url: https://example.com/sitemap.xml
          fail_mode: error
          # execution_mode: agent
          # agent_pool_id: production
          comment_on_pr: ${{ github.event_name == 'pull_request' }}
          collect_code_changes: true
          github_token: ${{ github.token }}
```

Note: no `actions/checkout` step is needed — this action is referenced by name, not local path.

## Releases

| Tag | Notes |
| --- | --- |
| `v1.8` | Rule-based PR risk score in the summary table (`risk_score_enabled`, default `true`). Combines changed-path signals (auth, payment, migration, production config, etc.) with SEO run-diff and crawl counts. Also adds file change categorization (code/tests/config/…) and GitHub Compare line stats in PR comments and `ci-changes` payloads. |
| `v1.7` | PR comment redesign: decision-focused **Signal Diff Report** with pass/fail verdict, severity label, summary metrics table, baseline before/after comparison, capped new findings, and separate SEO vs repository-change sections. Same report is appended to the GitHub Actions step summary. |
| `v1.6` | `execution_mode` and `agent_pool_id` inputs route CI crawls to customer agent pools (`executionMode` / `agentPoolId` on `POST /api/trigger/ci`). Requires Signal Diff API with agent routing enabled. |
| `v1.5` | GitHub Compare: literal `...` / `..` separators, two-dot fallback, and `github.event.before` retry when last-run baseline is not comparable (e.g. workflow re-run). |
| `v1.4` | Passes `excludeJobId` to `GET /api/ci/last-run` so the crawl that just finished is not used as its own baseline. Requires API support for `excludeJobId` (deploy latest Signal Diff API). |
| `v1.3` | Python HTTP scripts send `User-Agent: signal-diff-action/1.3` so edge WAFs (e.g. Cloudflare) do not block `GET /api/ci/last-run` and job fetches that used the default `Python-urllib` signature. |
| `v1.2` | CI code change collection and enriched PR comments. |

## Setup

### 1. Add secrets to your repository

Go to **Settings → Secrets and variables → Actions** and add:

- `SIGNALDIFF_API_BASE_URL` — your SeoChecker API host URL
- `SIGNALDIFF_CI_API_KEY` — a CI API key from your SeoChecker instance
