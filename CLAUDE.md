# Claude Project Guide

## Design Philosophy

**Aesthetic:** Dark, bold, minimalist. Inspired by Lisa Studios and modern SaaS platforms (Vercel, Linear, Stripe).

**Core principles:**
- Massive, uppercase typography with tight letter spacing
- Full-width sections that dominate the viewport
- High contrast (pure black backgrounds, white text)
- Smooth scroll reveal animations
- Bordered buttons (outlined, not filled)
- Generous whitespace between sections

**Color Palette:**
- Background: Pure black (`#000000`)
- Text primary: White (`#ffffff`)
- Text secondary: `text-white/30` to `text-white/40`
- Accents: Indigo/blue for highlights, emerald for success, red for warnings

## Technical Stack

- FastAPI (Python backend)
- Tailwind CSS (CDN) + GSAP (animations)
- Claude Sonnet (classification)
- Jina Reader (article fetching)
- BeautifulSoup (fallback parser)
- Docker + Render.com (deployment)
- pytest (testing)

## Project Purpose

News relevance classifier for Performativ (wealth management SaaS).

**Three labels** (derived deterministically from relevance + sentiment scores):
- GOOD_NEWS: Relevant + positive/neutral sentiment (sentiment >= 0)
- BAD_NEWS: Relevant + negative sentiment (sentiment < 0)
- UNRELATED: Not relevant (relevance < 0.3)

**Three endpoints:**
- GET /health
- POST /classify
- GET /latest

## Guidelines for Claude

1. **Dark theme mandatory** — black backgrounds, white text
2. **Every element must have purpose** — no decorative fluff
3. **Accessibility matters** — contrast ratios, focus states, semantic HTML
4. **Security-first** — no XSS vulnerabilities, rate limit API, validate inputs
5. **Update README when adding features**
