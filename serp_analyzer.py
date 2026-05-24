import os
import csv
import json
import time
import requests
from datetime import datetime

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
    if YOUR_DOMAIN.lower() in u:                                      return "Own"
    if "youtube.com" in u or "youtu.be" in u:                        return "YouTube"
    if "reddit.com" in u:                                             return "Reddit"
    if any(s in u for s in ["facebook.com","twitter.com","x.com",
                             "instagram.com","linkedin.com","tiktok.com"]): return "Social"
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


def write_to_sheets(token: str, sheet_name: str, rows: list):
    url     = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Створити аркуш якщо не існує
    requests.post(f"{url}:batchUpdate", headers=headers, json={
        "requests": [{"addSheet": {"properties": {"title": sheet_name}}}]
    })

    # Очистити аркуш перед записом
    requests.post(
        f"{url}/values/{sheet_name}!A1:Z10000:clear",
        headers=headers
    )

    # Записати нові дані
    requests.put(
        f"{url}/values/{sheet_name}!A1?valueInputOption=RAW",
        headers=headers,
        json={"values": rows},
    )


def main():
    sa_info = json.loads(GOOGLE_SA_JSON)
    token   = get_google_token(sa_info)

    # Read keywords.csv  →  columns: keyword, cluster
    clusters = {}
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clusters.setdefault(row.get("cluster", "General"), []).append(row["keyword"])

    all_rows       = [["Cluster", "Keyword", "Position", "Type", "URL", "Title"]]
    summaries      = {}

    for cluster, keywords in clusters.items():
        kw_data = []
        for kw in keywords:
            results = [{"type": classify_url(r["url"]), **r} for r in fetch_serp(kw)]
            kw_data.append({"keyword": kw, "results": results})
            all_rows += [[cluster, kw, r["position"], r["type"], r["url"], r["title"]]
                         for r in results]
            time.sleep(1)

        summaries[cluster] = analyze_cluster(cluster, kw_data)

    # Append cluster analysis
    all_rows += [[]] + [["=== CLUSTER ANALYSIS ==="]] + \
                [[c, s] for c, s in summaries.items()]

    sheet_name = "SERP-" + datetime.now().strftime("%Y-W%V")
    write_to_sheets(token, sheet_name, all_rows)
    print(f"✅ Done → https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
