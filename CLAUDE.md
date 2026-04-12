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
- No unnecessary decorations — everything has purpose

**Color Palette:**
- Background: Pure black (`#000000` or `bg-black`)
- Text primary: White (`#ffffff` or `text-white`)
- Text secondary: `text-white/30` to `text-white/40`
- Text tertiary: `text-white/15` to `text-white/20`
- Accents: Indigo/blue for highlights, emerald for success, red for warnings

**Typography:**
- Font: Inter (already loaded)
- Headings: Bold/Black weight (700-900), uppercase, tight tracking
- Body: 400-500 weight, generous line height (1.6-1.8)
- Sizes: Use `clamp()` for fluid scaling

**Animations:**
- Scroll reveals: Elements fade and slide in from different directions
- Transitions: 0.3-0.9s with cubic-bezier(0.16,1,0.3,1) easing
- Hover states: Subtle, purposeful (not flashy)
- No auto-playing animations — reveal on scroll only

## Technical Stack

**Frameworks:**
- FastAPI (Python backend)
- Tailwind CSS (no custom CSS unless essential)
- Claude AI (claude-sonnet-4-6 model)

**Tools:**
- Jina Reader for article fetching
- BeautifulSoup for HTML parsing
- Docker for deployment
- Render.com for hosting
- pytest for testing

**Frontend:**
- Vanilla JavaScript (no frameworks)
- Tailwind utilities only
- Heroicons for icons (if needed)
- IntersectionObserver for scroll animations

## Project Purpose

News relevance classifier for Performativ (wealth management SaaS).

**Three labels:**
- GOOD_NEWS: Relevant + positive
- BAD_NEWS: Relevant + negative
- UNRELATED: Not relevant

**Three endpoints:**
- GET /health
- POST /classify
- GET /latest

## Guidelines for Claude

1. **Always use Tailwind utilities** — no custom CSS except animations
2. **Design-first approach** — reference existing sites, get screenshot approval before coding
3. **Dark theme mandatory** — black backgrounds, white text
4. **No "vibe coded" feel** — if it looks AI-generated, remake it
5. **Every element must have purpose** — no decorative fluff
6. **Accessibility matters** — contrast ratios, focus states, semantic HTML
7. **Performance first** — lazy load images, minimize JavaScript
8. **Mobile responsive** — test at 375px and 1440px
9. **Security-first** — no XSS vulnerabilities, rate limit API, validate inputs
10. **Documentation** — update README when adding features

## Recent Changes

- Redesigned frontend with Tailwind CSS (studio aesthetic)
- Added rate limiting (10 req/min per IP)
- Fixed XSS vulnerability in topics rendering
- Improved confidence scoring calibration
- Deployed to Render.com with Docker

## Next Steps

- [ ] Push latest changes to GitHub
- [ ] Invite @tech-challenge-reviewer as collaborator
- [ ] Email hr@performativ.com with repo + live URL
- [ ] Consider adding dark mode toggle (if time)
- [ ] Add API rate limit headers to responses
