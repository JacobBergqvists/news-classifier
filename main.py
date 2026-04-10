import os
import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
        model="claude-opus-4-6",
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
