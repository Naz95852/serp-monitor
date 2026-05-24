import os
import csv
import json
import time
import requests
from datetime import datetime
from collections import Counter, defaultdict

# ── Config (set these as GitHub Secrets) ─────────────────────────────────────
SERPAPI_KEY    = os.environ["SERPAPI_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_KEY"]
GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID       = os.environ["GOOGLE_SHEET_ID"]
YOUR_DOMAIN    = os.environ.get("YOUR_DOMAIN", "example.com")
KEYWORDS_FILE  = "keywords.csv"
# ─────────────────────────────────────────────────────────────────────────────

TYPES_ORDER = ["Own", "Article", "YouTube", "Reddit", "Social"]


# ── Google Sheets auth via Service Account ────────────────────────────────────
def get_google_token(sa_info: dict) -> str:
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend

    now = int(time.time())
    header  = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss":   sa_info["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud":   "https://oauth2.googleapis.com/token",
        "iat":   now,
        "exp":   now + 3600,
    }).encode()).rstrip(b"=")

    signing_input = header + b"." + payload
    private_key = serialization.load_pem_private_key(
        sa_info["private_key"].encode(), password=None, backend=default_backend()
    )
    signature = base64.urlsafe_b64encode(
        private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    ).rstrip(b"=")

    jwt = (signing_input + b"." + signature).decode()
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":  jwt,
    })
    return resp.json()["access_token"]


# ── Classify each SERP result by content type ─────────────────────────────────
def classify_url(url: str) -> str:
    u = url.lower()
    if YOUR_DOMAIN.lower() in u:                                               return "Own"
    if "youtube.com" in u or "youtu.be" in u:                                 return "YouTube"
    if "reddit.com" in u:                                                      return "Reddit"
    if any(s in u for s in ["facebook.com", "twitter.com", "x.com",
                             "instagram.com", "linkedin.com", "tiktok.com"]): return "Social"
    return "Article"


# ── Fetch top-10 organic results from SerpAPI ─────────────────────────────────
def fetch_serp(keyword: str) -> list:
    resp = requests.get("https://serpapi.com/search", params={
        "api_key": SERPAPI_KEY,
        "q":       keyword,
        "num":     10,
        "gl":      "us",
        "hl":      "en",
    })
    return [
        {"position": r.get("position"), "url": r.get("link", ""), "title": r.get("title", "")}
        for r in resp.json().get("organic_results", [])
    ]


# ── Ask Claude for a cluster-level recommendation ─────────────────────────────
def analyze_cluster(cluster_name: str, kw_data: list) -> str:
    lines = [
        f'- "{d["keyword"]}": {", ".join(r["type"] for r in d["results"])}'
        for d in kw_data
    ]
    prompt = f"""You are an SEO strategist. Cluster: "{cluster_name}".

{chr(10).join(lines)}

Return exactly 3 lines:
1. Pattern: what content type dominates and what it signals
2. Action: one clear content recommendation
3. Priority: High / Medium / Low"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        json={
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages":   [{"role": "user", "content": prompt}],
        },
    )
    resp_json = resp.json()
    if "content" not in resp_json:
        print(f"Anthropic API error: {resp_json}")
        return "Analysis unavailable"
    return resp_json["content"][0]["text"]


# ── Sheets helpers ────────────────────────────────────────────────────────────
def get_sheet_numeric_id(token: str, title: str) -> int | None:
    resp = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    for s in resp.json().get("sheets", []):
        if s["properties"]["title"] == title:
            return s["properties"]["sheetId"]
    return None


def delete_charts_on_sheet(token: str, numeric_id: int):
    resp = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    chart_ids = []
    for s in resp.json().get("sheets", []):
        if s["properties"]["sheetId"] == numeric_id:
            chart_ids = [c["chartId"] for c in s.get("charts", [])]
    if chart_ids:
        requests.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}:batchUpdate",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"requests": [{"deleteEmbeddedObject": {"objectId": cid}} for cid in chart_ids]},
        )


def write_to_sheets(token: str, sheet_name: str, rows: list):
    url     = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    requests.post(f"{url}:batchUpdate", headers=headers, json={
        "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
    })
    requests.post(f"{url}/values/{sheet_name}!A1:Z10000:clear", headers=headers)
    requests.put(
        f"{url}/values/{sheet_name}!A1?valueInputOption=RAW",
        headers=headers,
        json={"values": rows},
    )


# ── Dashboard with charts ─────────────────────────────────────────────────────
CHART_ROW = 41  # row where chart data block starts (0-indexed)
CHART_COL = 5   # column F (0-indexed)

def build_dashboard(token: str, kw_data_all: list, summaries: dict, sheet_name: str):
    DASH    = "DASHBOARD"
    url     = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    requests.post(f"{url}:batchUpdate", headers=headers, json={
        "requests": [{"addSheet": {"properties": {"title": DASH}}}]
    })
    requests.post(f"{url}/values/{DASH}!A1:Z1000:clear", headers=headers)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # Compute stats
    total_keywords = len(kw_data_all)
    type_counter   = Counter()
    kw_type_hits   = defaultdict(set)
    own_in_top10   = 0
    opportunities  = []

    for item in kw_data_all:
        types_in_kw = set()
        for r in item["results"]:
            type_counter[r["type"]] += 1
            types_in_kw.add(r["type"])
        for t in types_in_kw:
            kw_type_hits[t].add(item["keyword"])
        if "Own" in types_in_kw:
            own_in_top10 += 1
        else:
            opportunities.append(item)

    total_urls = sum(type_counter.values())
    own_pct    = round(own_in_top10 / total_keywords * 100) if total_keywords else 0

    def parse_priority(text: str) -> str:
        t = text.upper()
        if "HIGH" in t:   return "🔴 High"
        if "MEDIUM" in t: return "🟡 Medium"
        if "LOW" in t:    return "🟢 Low"
        return "—"

    # Build rows
    rows = []
    rows.append([f"📊 SERP DASHBOARD — {now_str}"])
    rows.append([f"Source: {sheet_name}"])
    rows.append([])
    rows.append(["── KPI ──────────────────────────────"])
    rows.append(["Metric", "Value"])
    rows.append(["Total keywords", total_keywords])
    rows.append(["Own domain in top-10", f"{own_in_top10} / {total_keywords}  ({own_pct}%)"])
    rows.append(["Opportunities (not in top-10)", len(opportunities)])
    rows.append([])
    rows.append(["── SERP TYPE DISTRIBUTION ───────────"])
    rows.append(["Type", "URLs", "%"])
    for t in TYPES_ORDER:
        cnt = type_counter.get(t, 0)
        pct = round(cnt / total_urls * 100, 1) if total_urls else 0
        rows.append([t, cnt, f"{pct}%"])
    rows.append([])
    rows.append(["── CLUSTER ANALYSIS ─────────────────"])
    rows.append(["Cluster", "Priority", "Analysis"])
    for cluster, analysis in summaries.items():
        rows.append([cluster, parse_priority(analysis), analysis.replace("\n", " | ")])
    rows.append([])
    rows.append(["── OPPORTUNITIES (not in top-10) ────"])
    rows.append(["#", "Cluster", "Keyword"])
    for i, item in enumerate(opportunities[:30], 1):
        rows.append([i, item["cluster"], item["keyword"]])
    if not opportunities:
        rows.append(["", "✅ Own domain present for all keywords"])

    # Chart data block at col F
    while len(rows) < CHART_ROW:
        rows.append([])

    chart_data = [["Type", "Total URLs", "Keyword count"]]
    for t in TYPES_ORDER:
        chart_data.append([t, type_counter.get(t, 0), len(kw_type_hits.get(t, set()))])

    for i, cd in enumerate(chart_data):
        target = CHART_ROW + i
        while len(rows) <= target:
            rows.append([])
        while len(rows[target]) < CHART_COL + 3:
            rows[target].append("")
        rows[target][CHART_COL]     = cd[0]
        rows[target][CHART_COL + 1] = cd[1]
        rows[target][CHART_COL + 2] = cd[2]

    requests.put(
        f"{url}/values/{DASH}!A1?valueInputOption=RAW",
        headers=headers,
        json={"values": rows},
    )

    # Charts
    sid = get_sheet_numeric_id(token, DASH)
    if sid is None:
        print("⚠️  Could not get DASHBOARD sheet ID — skipping charts")
        return

    delete_charts_on_sheet(token, sid)

    label_range    = {"sheetId": sid, "startRowIndex": CHART_ROW + 1, "endRowIndex": CHART_ROW + 6,
                      "startColumnIndex": CHART_COL,     "endColumnIndex": CHART_COL + 1}
    url_range      = {"sheetId": sid, "startRowIndex": CHART_ROW + 1, "endRowIndex": CHART_ROW + 6,
                      "startColumnIndex": CHART_COL + 1, "endColumnIndex": CHART_COL + 2}
    kw_count_range = {"sheetId": sid, "startRowIndex": CHART_ROW + 1, "endRowIndex": CHART_ROW + 6,
                      "startColumnIndex": CHART_COL + 2, "endColumnIndex": CHART_COL + 3}

    resp = requests.post(f"{url}:batchUpdate", headers=headers, json={"requests": [
        # Title formatting
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 13},
                "backgroundColor": {"red": 0.1, "green": 0.62, "blue": 0.43},
            }},
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 220}, "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 550}, "fields": "pixelSize",
        }},
        # Pie chart
        {"addChart": {"chart": {
            "spec": {
                "title": "SERP Positions by Category",
                "pieChart": {
                    "legendPosition": "RIGHT_LEGEND",
                    "domain": {"sourceRange": {"sources": [label_range]}},
                    "series": {"sourceRange": {"sources": [url_range]}},
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": sid, "rowIndex": 3, "columnIndex": 4},
                "widthPixels": 460, "heightPixels": 300,
            }},
        }}},
        # Bar chart
        {"addChart": {"chart": {
            "spec": {
                "title": "Content Types in SERP (keyword count)",
                "basicChart": {
                    "chartType": "BAR",
                    "legendPosition": "NO_LEGEND",
                    "axis": [
                        {"position": "BOTTOM_AXIS", "title": "Keywords"},
                        {"position": "LEFT_AXIS",   "title": "Content Type"},
                    ],
                    "domains": [{"domain": {"sourceRange": {"sources": [label_range]}}}],
                    "series": [{"series": {"sourceRange": {"sources": [kw_count_range]}},
                                "targetAxis": "BOTTOM_AXIS"}],
                    "headerCount": 0,
                },
            },
            "position": {"overlayPosition": {
                "anchorCell": {"sheetId": sid, "rowIndex": 17, "columnIndex": 4},
                "widthPixels": 460, "heightPixels": 300,
            }},
        }}},
    ]})

    if resp.status_code == 200:
        print("📊 Dashboard + charts updated → DASHBOARD tab")
    else:
        print(f"⚠️  Chart error {resp.status_code}: {resp.text[:300]}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    sa_info = json.loads(GOOGLE_SA_JSON)
    token   = get_google_token(sa_info)

    # Load keywords.csv (columns: keyword, cluster)
    clusters = {}
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clusters.setdefault(row.get("cluster", "General"), []).append(row["keyword"])

    all_rows    = [["Cluster", "Keyword", "Position", "Type", "URL", "Title"]]
    summaries   = {}
    kw_data_all = []

    for cluster, keywords in clusters.items():
        kw_data = []
        for kw in keywords:
            results = [{"type": classify_url(r["url"]), **r} for r in fetch_serp(kw)]
            kw_data.append({"keyword": kw, "results": results})
            kw_data_all.append({"cluster": cluster, "keyword": kw, "results": results})
            all_rows += [[cluster, kw, r["position"], r["type"], r["url"], r["title"]]
                         for r in results]
            time.sleep(1)
        summaries[cluster] = analyze_cluster(cluster, kw_data)

    all_rows += [[]] + [["=== CLUSTER ANALYSIS ==="]] + \
                [[c, s] for c, s in summaries.items()]

    sheet_name = "SERP-" + datetime.now().strftime("%Y-W%V")
    write_to_sheets(token, sheet_name, all_rows)
    print(f"✅ Data written → {sheet_name}")

    build_dashboard(token, kw_data_all, summaries, sheet_name)
    print(f"🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
