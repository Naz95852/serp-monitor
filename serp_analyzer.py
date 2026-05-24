import os
import csv
import json
import time
import requests
from datetime import datetime
from collections import Counter

# ── Config ────────────────────────────────────────────────────────────────────
SERPAPI_KEY    = os.environ["SERPAPI_KEY"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_KEY"]
GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID       = os.environ["GOOGLE_SHEET_ID"]
YOUR_DOMAIN    = os.environ.get("YOUR_DOMAIN", "example.com")
KEYWORDS_FILE  = "keywords.csv"
# ─────────────────────────────────────────────────────────────────────────────


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
        "assertion":  jwt
    })
    return resp.json()["access_token"]


def classify_url(url: str) -> str:
    u = url.lower()
    if YOUR_DOMAIN.lower() in u:                                               return "Own"
    if "youtube.com" in u or "youtu.be" in u:                                 return "YouTube"
    if "reddit.com" in u:                                                      return "Reddit"
    if any(s in u for s in ["facebook.com","twitter.com","x.com",
                             "instagram.com","linkedin.com","tiktok.com"]):    return "Social"
    return "Article"


def fetch_serp(keyword: str) -> list:
    resp = requests.get("https://serpapi.com/search", params={
        "api_key": SERPAPI_KEY,
        "q":       keyword,
        "num":     10,
        "gl":      "us",
        "hl":      "en",
    })
    return [
        {"position": r.get("position"), "url": r.get("link",""), "title": r.get("title","")}
        for r in resp.json().get("organic_results", [])
    ]


def analyze_cluster(cluster_name: str, kw_data: list) -> str:
    lines = [
        f'- "{d["keyword"]}": {", ".join(r["type"] for r in d["results"])}'
        for d in kw_data
    ]
    prompt = f"""SEO strategist. Cluster: "{cluster_name}".

{chr(10).join(lines)}

Return 3 lines:
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


def get_or_create_sheet_id(token: str, sheet_title: str) -> int | None:
    """Return numeric sheetId for a given tab title, or None if not found."""
    url     = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    headers = {"Authorization": f"Bearer {token}"}
    resp    = requests.get(url, headers=headers)
    for s in resp.json().get("sheets", []):
        if s["properties"]["title"] == sheet_title:
            return s["properties"]["sheetId"]
    return None


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


def build_dashboard(token: str, kw_data_all: list, summaries: dict, sheet_name: str):
    """
    kw_data_all — list of {cluster, keyword, results: [{type, position, url, title}]}
    summaries   — {cluster: analysis_text}
    """
    DASH = "DASHBOARD"
    url     = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Create tab if needed ──────────────────────────────────────────────────
    requests.post(f"{url}:batchUpdate", headers=headers, json={
        "requests": [{"addSheet": {"properties": {"title": DASH}}}]
    })
    requests.post(f"{url}/values/{DASH}!A1:Z1000:clear", headers=headers)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    # ── Compute KPIs ──────────────────────────────────────────────────────────
    total_keywords  = len(kw_data_all)
    type_counter    = Counter()
    own_in_top10    = 0
    opportunities   = []   # keywords where Own not found

    for item in kw_data_all:
        has_own = False
        for r in item["results"]:
            type_counter[r["type"]] += 1
            if r["type"] == "Own":
                has_own = True
        if has_own:
            own_in_top10 += 1
        else:
            opportunities.append({
                "cluster": item["cluster"],
                "keyword": item["keyword"],
            })

    total_results   = sum(type_counter.values())
    own_pct         = round(own_in_top10 / total_keywords * 100) if total_keywords else 0

    # ── Priority parsing ──────────────────────────────────────────────────────
    def parse_priority(text: str) -> str:
        t = text.upper()
        if "HIGH" in t:   return "🔴 High"
        if "MEDIUM" in t: return "🟡 Medium"
        if "LOW" in t:    return "🟢 Low"
        return "—"

    # ── Build rows ────────────────────────────────────────────────────────────
    rows = []

    # Header
    rows.append([f"📊 SERP DASHBOARD — {now_str}"])
    rows.append([f"Source sheet: {sheet_name}"])
    rows.append([])

    # KPI block
    rows.append(["── KPI ──────────────────────────────────"])
    rows.append(["Metric", "Value"])
    rows.append(["Total keywords", total_keywords])
    rows.append(["Own domain in top-10", f"{own_in_top10} / {total_keywords}  ({own_pct}%)"])
    rows.append(["Opportunities (Own not in top-10)", len(opportunities)])
    rows.append([])

    # Content type distribution
    rows.append(["── SERP type distribution ───────────────"])
    rows.append(["Type", "Count", "% of all results"])
    for t in ["Own", "Article", "YouTube", "Reddit", "Social"]:
        cnt = type_counter.get(t, 0)
        pct = round(cnt / total_results * 100, 1) if total_results else 0
        rows.append([t, cnt, f"{pct}%"])
    rows.append([])

    # Cluster analysis
    rows.append(["── CLUSTER ANALYSIS ─────────────────────"])
    rows.append(["Cluster", "Priority", "Analysis"])
    for cluster, analysis in summaries.items():
        priority = parse_priority(analysis)
        rows.append([cluster, priority, analysis.replace("\n", " | ")])
    rows.append([])

    # Opportunities
    rows.append(["── TOP OPPORTUNITIES (Own not in top-10) ─"])
    rows.append(["#", "Cluster", "Keyword"])
    for i, opp in enumerate(opportunities[:30], 1):
        rows.append([i, opp["cluster"], opp["keyword"]])
    if not opportunities:
        rows.append(["", "✅ Own domain present in top-10 for all keywords!"])

    # ── Write to sheet ────────────────────────────────────────────────────────
    requests.put(
        f"{url}/values/{DASH}!A1?valueInputOption=RAW",
        headers=headers,
        json={"values": rows},
    )

    # ── Basic formatting ──────────────────────────────────────────────────────
    sheet_id = get_or_create_sheet_id(token, DASH)
    if sheet_id is not None:
        requests.post(f"{url}:batchUpdate", headers=headers, json={"requests": [
            # Bold row 1 (title)
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True, "fontSize": 13},
                    "backgroundColor": {"red": 0.1, "green": 0.62, "blue": 0.43}
                }},
                "fields": "userEnteredFormat(textFormat,backgroundColor)"
            }},
            # Bold all section headers (rows with ──)
            # Freeze row 1
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }},
            # Column widths
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 50}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 200}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 600}, "fields": "pixelSize"
            }},
        ]})

    print(f"📊 Dashboard updated → DASHBOARD tab")


def main():
    sa_info = json.loads(GOOGLE_SA_JSON)
    token   = get_google_token(sa_info)

    # Read keywords.csv → columns: keyword, cluster
    clusters = {}
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clusters.setdefault(row.get("cluster", "General"), []).append(row["keyword"])

    all_rows    = [["Cluster", "Keyword", "Position", "Type", "URL", "Title"]]
    summaries   = {}
    kw_data_all = []   # for dashboard

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

    # Append cluster analysis to weekly sheet
    all_rows += [[]] + [["=== CLUSTER ANALYSIS ==="]] + \
                [[c, s] for c, s in summaries.items()]

    sheet_name = "SERP-" + datetime.now().strftime("%Y-W%V")
    write_to_sheets(token, sheet_name, all_rows)
    print(f"✅ Done → https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")

    # Build / refresh dashboard
    build_dashboard(token, kw_data_all, summaries, sheet_name)


if __name__ == "__main__":
    main()
