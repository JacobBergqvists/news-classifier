import os
import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Performativ News Classifier")
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Sparar de senaste klassificeringarna i minnet (nollställs vid omstart)
latest_results: list[dict] = []

SYSTEM_PROMPT = """You are a news relevance classifier for Performativ — a B2B SaaS platform for wealth managers.

Performativ serves: private banks, family offices, asset managers, RIAs, and advisory platforms.
Its product covers: portfolio management, compliance, reporting, data integration, and AI-enabled operations.

Classify news articles as exactly one of:
- GOOD_NEWS: relevant to Performativ's business AND net positive (e.g. growing demand for wealth tech, positive regulation, competitor struggles)
- BAD_NEWS: relevant to Performativ's business AND net negative (e.g. adverse regulation, market contraction, security breaches in fintech)
- UNRELATED: not materially relevant to Performativ's business

Relevant themes: wealth management software, portfolio management systems, private banking, family offices, RIAs,
regulation (DORA, MiFID II, FiDA), compliance reporting, AI in regulated finance, enterprise data integration,
legacy modernization, custodian connectivity.

Irrelevant themes: general consumer tech, unrelated macro news, local news, entertainment, sports, lifestyle.

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{
  "label": "GOOD_NEWS" | "BAD_NEWS" | "UNRELATED",
  "confidence": 0.0-1.0,
  "reasoning": "1-2 sentence explanation",
  "relevance_topics": ["topic1", "topic2"]
}"""


def fetch_article_text(url: str) -> str:
    """Hämtar artikeltext via Jina Reader (hanterar paywalls och blockering)."""
    jina_url = f"https://r.jina.ai/{url}"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; NewsClassifier/1.0)",
            "Accept": "text/plain",
        }
        response = httpx.get(jina_url, headers=headers, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return response.text[:8000]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Kunde inte hämta artikeln: {str(e)}")


def classify_with_claude(url: str, article_text: str) -> dict:
    """Skickar artikeltext till Claude för klassificering."""
    user_message = f"URL: {url}\n\nArticle content:\n{article_text}"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Om Claude av någon anledning svarar med markdown-block, rensa det
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned)

    return result


# --- API-endpoints ---


class ClassifyRequest(BaseModel):
    url: str

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.cnbc.com/2026/04/10/alibaba-cloud-invests-world-model-ai-shengshu-vidu.html"
            }
        }


@app.get("/", response_class=HTMLResponse)
def homepage():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Performativ News Classifier</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .container { max-width: 720px; margin: 0 auto; padding: 48px 24px; }
  h1 { font-size: 28px; font-weight: 600; margin-bottom: 4px; }
  .subtitle { color: #94a3b8; margin-bottom: 36px; font-size: 15px; }
  .input-group { display: flex; gap: 12px; margin-bottom: 32px; }
  input[type="url"] { flex: 1; padding: 14px 16px; border-radius: 10px; border: 1px solid #334155; background: #1e293b; color: #e2e8f0; font-size: 15px; outline: none; transition: border-color 0.2s; }
  input[type="url"]:focus { border-color: #6366f1; }
  input[type="url"]::placeholder { color: #64748b; }
  button { padding: 14px 28px; border-radius: 10px; border: none; background: #6366f1; color: white; font-size: 15px; font-weight: 500; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
  button:hover { background: #4f46e5; }
  button:disabled { background: #334155; cursor: not-allowed; }
  .result { background: #1e293b; border-radius: 12px; padding: 24px; display: none; }
  .label-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; font-weight: 600; font-size: 14px; margin-bottom: 16px; }
  .GOOD_NEWS { background: #065f46; color: #6ee7b7; }
  .BAD_NEWS { background: #7f1d1d; color: #fca5a5; }
  .UNRELATED { background: #334155; color: #94a3b8; }
  .reasoning { font-size: 15px; line-height: 1.6; color: #cbd5e1; margin-bottom: 16px; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .topic-tag { background: #334155; color: #94a3b8; padding: 4px 12px; border-radius: 6px; font-size: 13px; }
  .confidence { color: #64748b; font-size: 13px; }
  .error { background: #7f1d1d; color: #fca5a5; border-radius: 12px; padding: 16px; display: none; }
  .spinner { display: none; text-align: center; padding: 32px; color: #94a3b8; }
  .history { margin-top: 40px; }
  .history h2 { font-size: 18px; margin-bottom: 16px; color: #94a3b8; }
  .history-item { background: #1e293b; border-radius: 10px; padding: 16px; margin-bottom: 8px; cursor: pointer; transition: background 0.2s; }
  .history-item:hover { background: #253043; }
  .history-item .hi-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .history-item .hi-url { font-size: 13px; color: #64748b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
</head>
<body>
<div class="container">
  <h1>News Classifier</h1>
  <p class="subtitle">AI-powered relevance classifier for Performativ</p>
  <div class="input-group">
    <input type="url" id="url" placeholder="Paste a news article URL..." />
    <button id="btn" onclick="classify()">Classify</button>
  </div>
  <div class="spinner" id="spinner">Analyzing article...</div>
  <div class="error" id="error"></div>
  <div class="result" id="result">
    <span class="label-badge" id="label"></span>
    <p class="reasoning" id="reasoning"></p>
    <div class="meta" id="topics"></div>
    <p class="confidence" id="confidence"></p>
  </div>
  <div class="history" id="history-section" style="display:none">
    <h2>Recent classifications</h2>
    <div id="history"></div>
  </div>
</div>
<script>
async function classify() {
  const url = document.getElementById('url').value.trim();
  if (!url) return;
  const btn = document.getElementById('btn');
  btn.disabled = true; btn.textContent = 'Analyzing...';
  document.getElementById('spinner').style.display = 'block';
  document.getElementById('result').style.display = 'none';
  document.getElementById('error').style.display = 'none';
  try {
    const res = await fetch('/classify', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url}) });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Request failed'); }
    const data = await res.json();
    showResult(data);
    loadHistory();
  } catch(e) {
    document.getElementById('error').textContent = e.message;
    document.getElementById('error').style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = 'Classify';
    document.getElementById('spinner').style.display = 'none';
  }
}
function showResult(d) {
  document.getElementById('label').textContent = d.label;
  document.getElementById('label').className = 'label-badge ' + d.label;
  document.getElementById('reasoning').textContent = d.reasoning;
  document.getElementById('topics').innerHTML = (d.relevance_topics||[]).map(t => '<span class="topic-tag">'+t+'</span>').join('');
  document.getElementById('confidence').textContent = 'Confidence: ' + (d.confidence * 100).toFixed(0) + '%';
  document.getElementById('result').style.display = 'block';
}
async function loadHistory() {
  try {
    const res = await fetch('/latest?limit=5');
    const data = await res.json();
    if (data.length === 0) return;
    document.getElementById('history-section').style.display = 'block';
    document.getElementById('history').innerHTML = data.map(d =>
      '<div class="history-item" onclick=\\'showResult('+JSON.stringify(d).replace(/'/g,"&#39;")+')\\'>' +
      '<div class="hi-top"><span class="label-badge '+d.label+'" style="margin:0;font-size:12px;padding:3px 10px">'+d.label+'</span>' +
      '<span class="confidence">'+((d.confidence*100).toFixed(0))+'%</span></div>' +
      '<div class="hi-url">'+d.url+'</div></div>'
    ).join('');
  } catch(e) {}
}
document.getElementById('url').addEventListener('keydown', e => { if(e.key==='Enter') classify(); });
loadHistory();
</script>
</body>
</html>"""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify")
def classify(request: ClassifyRequest):
    url = request.url

    # 1. Hämta artikeln
    article_text = fetch_article_text(url)

    # 2. Klassificera med Claude
    classification = classify_with_claude(url, article_text)

    # 3. Bygg svaret
    result = {
        "url": url,
        "label": classification["label"],
        "confidence": classification["confidence"],
        "reasoning": classification["reasoning"],
        "relevance_topics": classification.get("relevance_topics", []),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Spara i minnet (max 20 senaste)
    latest_results.insert(0, result)
    if len(latest_results) > 20:
        latest_results.pop()

    return result


@app.get("/latest")
def latest(limit: int = 10):
    return latest_results[:limit]
