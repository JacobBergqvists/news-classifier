# Performativ News Classifier

A lightweight AI agent that classifies news articles by their relevance to [Performativ](https://www.performativ.com/) : a B2B SaaS platform for wealth managers.

Given a news article URL, the agent fetches the content, analyzes it using Claude, and returns a structured classification: **GOOD_NEWS**, **BAD_NEWS**, or **UNRELATED**.

**Live demo:** https://news-classifier-245a.onrender.com

## How it works

```
URL  →  Fetch article  →  Claude classifies  →  Structured JSON response
         (Jina Reader      (relevance +          (label, confidence,
          + fallback)        sentiment)            reasoning, topics)
```

1. **Article fetching** — Uses [Jina Reader](https://r.jina.ai/) as the primary fetcher, which handles paywalled, JS-rendered, and bot-blocked pages. Falls back to direct HTTP + BeautifulSoup if Jina fails.

2. **Classification** — Sends extracted text to Claude (Sonnet) with a domain-specific system prompt that encodes Performativ's business context, relevant themes (wealth tech, regulation, compliance), and irrelevant themes.

3. **Structured output** — Claude returns JSON with label, confidence score, reasoning, and topic tags. The response is validated before being returned.

## API Endpoints

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
  "confidence": 0.82,
  "relevance": 0.92,
  "sentiment": 0.65,
  "reasoning": "FiDA creates new regulatory requirements driving demand for wealth tech compliance solutions like Performativ.",
  "relevance_topics": ["FiDA", "EU regulation", "compliance", "data integration"],
  "processed_at": "2026-04-10T09:04:52.037063+00:00"
}
```

## Design decisions

- **Jina Reader + fallback** — Many news sites block scrapers. Jina handles most edge cases (paywalls, cookie walls, JS rendering). The direct HTTP fallback ensures we degrade gracefully rather than failing outright.

- **Claude Sonnet over Opus** — Sonnet provides sufficient reasoning quality for classification at ~5x lower cost. For a service that could process hundreds of articles, this matters.

- **In-memory storage** — The `/latest` endpoint stores results in memory. This is intentional for a demo — a production system would use a database. The trade-off is simplicity vs. persistence.

- **Structured prompt with domain encoding** — Rather than relying on Claude's general knowledge, the system prompt explicitly encodes Performativ's business context, relevant themes (DORA, MiFID II, FiDA, wealth tech), and irrelevant themes. This makes classifications more consistent and auditable.

- **Validation layer** — The API validates both input (URL format) and output (label must be one of three valid values). This prevents garbage-in-garbage-out issues.

## Error handling

The service handles common failure modes:

- **Paywalled/blocked sites** — Jina Reader as primary fetcher, BeautifulSoup fallback
- **Timeouts** — Separate timeouts for fetching (20s) and classification, with descriptive error messages
- **Invalid URLs** — Input validation rejects malformed URLs before processing
- **Unparseable responses** — Handles markdown-wrapped JSON and validates the label field
- **API failures** — Claude API errors return 502 with a user-friendly message

## Running locally

### Backend only (FastAPI)

```bash
# Clone and install
git clone https://github.com/JacobBergqvists/news-classifier.git
cd news-classifier
pip install -r requirements.txt

# Set your API key
echo 'ANTHROPIC_API_KEY=your-key-here' > .env

# Start the server
python -m uvicorn main:app --reload

# Run tests
python -m pytest test_main.py -v
```

### With React frontend (full stack)

```bash
# Terminal 1: Backend
pip install -r requirements.txt
echo 'ANTHROPIC_API_KEY=your-key-here' > .env
python -m uvicorn main:app --reload

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`.

## Tech stack

**Backend:**
- **Python 3.9+** with FastAPI
- **Claude Sonnet** (Anthropic API) for classification
- **Jina Reader** for article extraction
- **BeautifulSoup** as fallback parser
- **AsyncAnthropic + httpx** for concurrent I/O
- **Pydantic** for validation and settings management

**Frontend:**
- **Next.js 16** with TypeScript
- **Tailwind CSS** for styling
- **shadcn/ui** for component library
- **Three.js** for shader animations

**Deployment:**
- **Docker** with multi-stage build (Node + Python)
- **Render** for hosting
