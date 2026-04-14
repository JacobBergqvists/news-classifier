# Performativ News Classifier

A lightweight AI agent that classifies news articles by their relevance to [Performativ](https://www.performativ.com/) — a B2B SaaS platform for wealth managers.

Given a news article URL, the agent fetches the content, analyzes it using Claude, and returns a structured classification: **GOOD_NEWS**, **BAD_NEWS**, or **UNRELATED**.

**Live demo:** https://news-classifier-245a.onrender.com

## How it works

```
URL  →  Fetch article  →  Claude scores  →  Label derived  →  JSON response
         (Jina Reader      (relevance +     (from scores,      (label, relevance,
          + fallback)        sentiment)       deterministic)     sentiment, topics)
```

1. **Article fetching** — Uses [Jina Reader](https://r.jina.ai/) as the primary fetcher, which handles paywalled, JS-rendered, and bot-blocked pages. Falls back to direct HTTP + BeautifulSoup if Jina fails.

2. **Classification** — Sends extracted text to Claude (Sonnet) with a domain-specific system prompt that encodes Performativ's business context, relevant themes (wealth tech, regulation, compliance), and irrelevant themes.

3. **Label derivation** — Claude returns numeric scores (relevance + sentiment). The label is derived deterministically: relevance < 0.3 → UNRELATED, else sentiment >= 0 → GOOD_NEWS, else BAD_NEWS. This keeps the classification auditable and consistent.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI for interactive testing |
| `GET` | `/health` | Health check |
| `POST` | `/classify` | Classify an article URL |
| `GET` | `/latest` | Recent classification history |
| `GET` | `/docs` | Swagger API documentation |

### Example request

```bash
curl -X POST https://news-classifier-245a.onrender.com/classify \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.finextra.com/newsarticle/43498/eu-reaches-agreement-on-fida-open-finance-framework"}'
```

### Example response

```json
{
  "url": "https://www.finextra.com/newsarticle/43498/...",
  "label": "GOOD_NEWS",
  "confidence": 0.72,
  "relevance": 0.82,
  "relevance_confidence": 0.90,
  "sentiment": 0.55,
  "sentiment_confidence": 0.75,
  "reasoning": "FiDA creates new regulatory requirements driving demand for wealth tech compliance solutions like Performativ.",
  "relevance_topics": ["FiDA", "open finance", "EU regulation", "data integration", "wealth management compliance"],
  "processed_at": "2026-04-13T12:37:04.327352+00:00"
}
```

## Design decisions

- **Jina Reader + fallback** — Many news sites block scrapers. Jina handles most edge cases (paywalls, cookie walls, JS rendering). The direct HTTP fallback ensures we degrade gracefully rather than failing outright.

- **Two-dimensional scoring** — Rather than asking the LLM for a single label, Claude scores articles on two independent axes: *relevance* (how close to Performativ's domain) and *sentiment* (positive or negative business impact). The label is then derived deterministically. This makes classifications more consistent and auditable than asking for a label directly.

- **Hybrid confidence calculation** — Confidence combines two independent signals via geometric mean: (1) Claude's self-reported certainty on each score, and (2) distance from decision boundaries. This is more honest than distance alone — an article with scores far from boundaries but where Claude was guessing correctly yields lower confidence. Both signals must be strong for high confidence.

- **Claude Sonnet over Opus** — Sonnet provides sufficient reasoning quality for classification at lower cost and latency. For a service that could process hundreds of articles, this matters.

- **Domain-encoded system prompt** — Rather than relying on Claude's general knowledge, the system prompt explicitly encodes Performativ's business context, relevant themes (DORA, MiFID II, FiDA, wealth tech), and irrelevant themes. This makes the classifier focused and repeatable.

- **In-memory storage** — The `/latest` endpoint stores results in memory. This is intentional for a demo — a production system would use a database.

- **Error page detection** — Before sending content to Claude, the fetcher checks for 404/403 error pages. This avoids wasting an API call on content that isn't actually an article.

## Error handling

- **Paywalled/blocked sites** — Jina Reader as primary fetcher, BeautifulSoup fallback
- **Timeouts** — Separate timeouts for fetching (20s) and classification, with descriptive error messages
- **Invalid URLs** — Input validation rejects malformed URLs before processing
- **Unparseable responses** — Handles markdown-wrapped JSON and validates the response structure
- **API failures** — Claude API errors return 502 with a user-friendly message
- **Rate limiting** — 10 requests/min per IP with `X-RateLimit-*` headers

## Running locally

```bash
git clone https://github.com/JacobBergqvists/news-classifier.git
cd news-classifier
pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=your-key-here' > .env

# Start the server
python -m uvicorn main:app --reload

# Run tests (41 tests)
python -m pytest test_main.py -v
```

## Tech stack

- **Python 3.9+** with FastAPI
- **Claude Sonnet** (Anthropic API) for classification
- **Jina Reader** for article extraction
- **BeautifulSoup** as fallback parser
- **Tailwind CSS** (CDN) + **GSAP** for the web UI
- **Docker** for deployment
- **Render.com** for hosting

## Classification quality

Tested across diverse article categories:

| Article | Label | Relevance | Confidence |
|---------|-------|-----------|------------|
| EU FiDA open finance framework (Finextra) | GOOD_NEWS | 0.82 | 0.69 |
| Consumer tech news (CNN /tech) | UNRELATED | 0.04 | 0.96 |

The classifier correctly identifies regulation/wealth tech news as relevant with positive sentiment, and general consumer tech as unrelated with high confidence.
