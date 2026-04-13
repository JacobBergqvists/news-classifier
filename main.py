import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings

# --- Configuration ---


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    anthropic_api_key: str
    cors_origins: list[str] = ["*"]
    rate_limit: int = 10
    rate_window: int = 60  # seconds
    log_level: str = "INFO"

    model_config = {"env_file": ".env"}


settings = Settings()

# --- Logging ---

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("news-classifier")

# --- App setup ---

app = FastAPI(
    title="Performativ News Classifier",
    description="AI-powered news relevance classifier for Performativ",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
http_client = httpx.AsyncClient(follow_redirects=True)

# In-memory store for recent classifications (resets on restart).
# A production system would use a database, but this is sufficient for a demo.
latest_results: list[dict] = []

# Simple rate limiting: max N requests per minute per IP
rate_limit_store: dict[str, list[float]] = {}

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

Relevance (how closely the article relates to Performativ's domain):
- 0.90-1.0: Directly about Performativ, its competitors, or core product category
- 0.70-0.89: Clearly about wealth management tech, portfolio systems, or specific regulation (DORA, MiFID II, FiDA)
- 0.40-0.69: Adjacent territory — fintech, compliance tech, or enterprise SaaS, but not specifically wealth management
- 0.10-0.39: Loosely connected — general finance, banking, or broad tech industry news
- 0.0-0.09: No meaningful connection to Performativ's business

Sentiment (if the article IS relevant, how positive or negative is the impact for Performativ):
- +0.7 to +1.0: Very positive — growing demand, favorable regulation, competitor weakness
- +0.3 to +0.7: Somewhat positive — market tailwinds, positive industry trends
- -0.3 to +0.3: Neutral or mixed — could go either way, or no clear positive/negative angle
- -0.3 to -0.7: Somewhat negative — headwinds, unfavorable trends, increased competition
- -0.7 to -1.0: Very negative — adverse regulation, security breaches, market contraction
For UNRELATED articles, sentiment should be 0.0.

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{
  "label": "GOOD_NEWS" | "BAD_NEWS" | "UNRELATED",
  "confidence": 0.0-1.0,
  "relevance": 0.0-1.0,
  "sentiment": -1.0 to 1.0,
  "reasoning": "1-2 sentence explanation",
  "relevance_topics": ["topic1", "topic2"]
}"""

VALID_LABELS = {"GOOD_NEWS", "BAD_NEWS", "UNRELATED"}

# Common error page patterns that indicate we didn't get real content
ERROR_PAGE_PATTERNS = [
    "404 not found", "page not found", "page cannot be found",
    "this page doesn't exist", "this page does not exist",
    "404 error", "error 404", "not found - ",
    "403 forbidden", "access denied",
    "sorry, we couldn't find", "the page you requested",
]


def detect_error_page(text: str) -> bool:
    """Check if fetched content looks like an error page rather than an article."""
    lower = text[:2000].lower()
    # Check for error page patterns
    for pattern in ERROR_PAGE_PATTERNS:
        if pattern in lower:
            return True
    # Very short content after stripping is likely an error page
    stripped = text.strip()
    if len(stripped) < 300 and any(w in lower for w in ["404", "error", "not found", "forbidden"]):
        return True
    return False


# --- Core logic ---


async def fetch_article_text(url: str) -> str:
    """Fetch article content via Jina Reader, which handles paywalls and JS-rendered pages.

    Falls back to direct HTTP fetch with BeautifulSoup if Jina fails, so we
    can still classify pages that Jina doesn't support.
    """
    # First try Jina Reader (handles most sites including paywalled ones)
    try:
        jina_url = f"https://r.jina.ai/{url}"
        headers = {"Accept": "text/plain"}
        response = await http_client.get(jina_url, headers=headers, timeout=20)
        response.raise_for_status()
        text = response.text.strip()
        if len(text) > 200:
            if detect_error_page(text):
                logger.warning("Jina Reader returned an error page for %s", url)
            else:
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
        response = await http_client.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        article = soup.find("article") or soup.find("main") or soup.body
        text = article.get_text(separator="\n", strip=True) if article else ""

        if len(text) > 200:
            if detect_error_page(text):
                logger.warning("Direct fetch returned an error page for %s", url)
            else:
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


async def classify_with_claude(url: str, article_text: str) -> dict:
    """Send article text to Claude for classification. Returns a validated result dict."""
    user_message = f"Classify this article.\n\nURL: {url}\n\nArticle content:\n{article_text}"

    try:
        message = await claude.messages.create(
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
    result.setdefault("relevance", 0.0)
    result.setdefault("sentiment", 0.0)
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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"url": "https://www.finextra.com/newsarticle/43498/eu-reaches-agreement-on-fida-open-finance-framework"}
            ]
        }
    }


class ClassifyResponse(BaseModel):
    url: str
    label: str
    confidence: float
    relevance: float
    sentiment: float
    reasoning: str
    relevance_topics: list[str]
    processed_at: str


# --- Endpoints ---


@app.get("/", response_class=HTMLResponse)
async def homepage():
    """Serve the web UI."""
    html_path = Path(__file__).parent / "static" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/health")
async def health():
    """Health check endpoint for monitoring and uptime checks."""
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest, req: Request):
    """Classify a news article by its relevance to Performativ's business.

    Fetches the article content, sends it to Claude for analysis, and returns
    a structured classification with label, confidence, reasoning, and topics.
    """
    # Rate limiting
    client_ip = req.client.host if req.client else "unknown"
    now = time.time()
    timestamps = rate_limit_store.get(client_ip, [])
    timestamps = [t for t in timestamps if now - t < settings.rate_window]
    if len(timestamps) >= settings.rate_limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 10 requests per minute.")
    timestamps.append(now)
    rate_limit_store[client_ip] = timestamps

    url = request.url
    logger.info("Classifying: %s", url)

    article_text = await fetch_article_text(url)
    classification = await classify_with_claude(url, article_text)

    result = {
        "url": url,
        "label": classification["label"],
        "confidence": classification["confidence"],
        "relevance": classification.get("relevance", 0.0),
        "sentiment": classification.get("sentiment", 0.0),
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
async def latest(limit: int = 10):
    """Return the most recent classifications. Useful for dashboards or Slack integrations."""
    return latest_results[:limit]
