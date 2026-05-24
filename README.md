# SERP Monitor

Automated SERP analysis for 350+ keywords. Runs every Monday, zero manual work.

Built by [Nazar Nosanenko](https://www.linkedin.com/in/YOUR_LINKEDIN/) — SEO Team Lead at Stripo.email.

## What it does

- Fetches top-10 Google results for every keyword via SerpAPI
- Classifies each URL: YouTube / Reddit / Social / Own / Article
- Sends the pattern to Claude (Anthropic API) → gets a strategic recommendation per cluster
- Writes everything to a new Google Sheets tab every week

## Stack

| Tool | Role |
|------|------|
| SerpAPI | SERP data |
| Anthropic API (Claude Haiku) | Cluster analysis |
| GitHub Actions | Weekly scheduler |
| Google Sheets | Output |

**Infrastructure cost: $0**

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/serp-monitor.git
```

### 2. Prepare keywords.csv
Two columns: `keyword` and `cluster`

keyword,cluster
email template builder,Email Builders
drag and drop email editor,Email Builders


### 3. Set up Google Sheets
- Create a new Google Sheet
- Create a Service Account in Google Cloud Console
- Share the sheet with the Service Account email (Editor role)
- Download the Service Account JSON

### 4. Add GitHub Secrets
Go to **Settings → Secrets → Actions** and add:

| Secret | Value |
|--------|-------|
| `SERPAPI_KEY` | Your SerpAPI key |
| `ANTHROPIC_KEY` | Your Anthropic API key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON content of Service Account |
| `GOOGLE_SHEET_ID` | ID from the Google Sheet URL |
| `YOUR_DOMAIN` | Your domain, e.g. `example.com` |

### 5. Run
Triggers automatically every Monday at 07:00 UTC.
Or run manually: **Actions → Weekly SERP Analysis → Run workflow**

## Output

Each week creates a new sheet tab `SERP-2026-W21` with:
- All top-10 URLs per keyword with type classification
- AI-generated strategic summary per cluster

## License
MIT
