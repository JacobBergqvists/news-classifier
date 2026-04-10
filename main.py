import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

load_dotenv()

# --- Logging ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("news-classifier")

# --- App setup ---

app = FastAPI(
    title="Performativ News Classifier",
    description="AI-powered news relevance classifier for Performativ",
    version="1.0.0",
)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# In-memory store for recent classifications (resets on restart).
# A production system would use a database, but this is sufficient for a demo.
latest_results: list[dict] = []

# --- Classification prompt ---

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

Confidence scoring guidelines (be precise, do NOT default to 0.72 or other round numbers):
- 0.90-0.99: Article directly mentions Performativ, its competitors, or core product categories by name
- 0.75-0.89: Article clearly covers a relevant theme (wealth tech, specific regulation, portfolio systems)
- 0.55-0.74: Article is tangentially related — touches on financial services but not wealth management specifically
- 0.30-0.54: Weak connection — general fintech or broad industry news
- 0.10-0.29: Very unlikely to be relevant
Use the FULL range. Vary your scores — 0.63, 0.78, 0.41, 0.87 are all valid. Never round to the nearest 5 or 10.

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{
  "label": "GOOD_NEWS" | "BAD_NEWS" | "UNRELATED",
  "confidence": 0.0-1.0,
  "reasoning": "1-2 sentence explanation",
  "relevance_topics": ["topic1", "topic2"]
}"""

VALID_LABELS = {"GOOD_NEWS", "BAD_NEWS", "UNRELATED"}

# --- Core logic ---


def fetch_article_text(url: str) -> str:
    """Fetch article content via Jina Reader, which handles paywalls and JS-rendered pages.

    Falls back to direct HTTP fetch with BeautifulSoup if Jina fails, so we
    can still classify pages that Jina doesn't support.
    """
    # First try Jina Reader (handles most sites including paywalled ones)
    try:
        jina_url = f"https://r.jina.ai/{url}"
        headers = {"Accept": "text/plain"}
        response = httpx.get(jina_url, headers=headers, timeout=20, follow_redirects=True)
        response.raise_for_status()
        text = response.text.strip()
        if len(text) > 200:
            logger.info("Fetched article via Jina Reader (%d chars)", len(text))
            return text[:8000]
    except httpx.TimeoutException:
        logger.warning("Jina Reader timed out for %s, trying direct fetch", url)
    except httpx.HTTPStatusError as e:
        logger.warning("Jina Reader returned %d for %s, trying direct fetch", e.response.status_code, url)
    except Exception as e:
        logger.warning("Jina Reader failed for %s: %s, trying direct fetch", url, e)

    # Fallback: direct HTTP fetch + BeautifulSoup
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsClassifier/1.0)"}
        response = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        article = soup.find("article") or soup.find("main") or soup.body
        text = article.get_text(separator="\n", strip=True) if article else ""

        if len(text) > 200:
            logger.info("Fetched article via direct HTTP (%d chars)", len(text))
            return text[:8000]
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Article fetch timed out. The site may be slow or unreachable.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch article: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch article: {str(e)}")

    raise HTTPException(
        status_code=422,
        detail="Could not extract enough text from this URL. The page may be paywalled, empty, or not a news article.",
    )


def classify_with_claude(url: str, article_text: str) -> dict:
    """Send article text to Claude for classification. Returns a validated result dict."""
    user_message = f"Classify this article.\n\nURL: {url}\n\nArticle content:\n{article_text}"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APITimeoutError:
        raise HTTPException(status_code=504, detail="Classification timed out. Please try again.")
    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        raise HTTPException(status_code=502, detail="Classification service temporarily unavailable.")

    raw = message.content[0].text.strip()
    logger.info("Claude raw response: %s", raw[:200])

    # Parse response — handle both clean JSON and markdown-wrapped JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Could not parse Claude response: %s", raw)
            raise HTTPException(status_code=500, detail="Could not parse classification response.")

    # Validate required fields and values
    if result.get("label") not in VALID_LABELS:
        logger.error("Invalid label in response: %s", result.get("label"))
        raise HTTPException(status_code=500, detail="Classification returned an invalid label.")

    result.setdefault("confidence", 0.5)
    result.setdefault("reasoning", "No reasoning provided.")
    result.setdefault("relevance_topics", [])

    return result


# --- Request/Response models ---


class ClassifyRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must start with http:// or https://")
        if not parsed.netloc or "." not in parsed.netloc:
            raise ValueError("URL must contain a valid domain")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://www.finextra.com/newsarticle/43498/eu-reaches-agreement-on-fida-open-finance-framework"
            }
        }


class ClassifyResponse(BaseModel):
    url: str
    label: str
    confidence: float
    reasoning: str
    relevance_topics: list[str]
    processed_at: str


# --- Endpoints ---


@app.get("/", response_class=HTMLResponse)
def homepage():
    """Serve the web UI."""
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/health")
def health():
    """Health check endpoint for monitoring and uptime checks."""
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest):
    """Classify a news article by its relevance to Performativ's business.

    Fetches the article content, sends it to Claude for analysis, and returns
    a structured classification with label, confidence, reasoning, and topics.
    """
    url = request.url
    logger.info("Classifying: %s", url)

    article_text = fetch_article_text(url)
    classification = classify_with_claude(url, article_text)

    result = {
        "url": url,
        "label": classification["label"],
        "confidence": classification["confidence"],
        "reasoning": classification["reasoning"],
        "relevance_topics": classification.get("relevance_topics", []),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store in memory (most recent first, capped at 20)
    latest_results.insert(0, result)
    if len(latest_results) > 20:
        latest_results.pop()

    logger.info("Result: %s (confidence: %.2f)", result["label"], result["confidence"])
    return result


@app.get("/latest")
def latest(limit: int = 10):
    """Return the most recent classifications. Useful for dashboards or Slack integrations."""
    return latest_results[:limit]
