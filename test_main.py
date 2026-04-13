"""Tests for the news classifier API.

Run with: python -m pytest test_main.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app, derive_label, detect_error_page, latest_results, rate_limit_store, settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_state():
    """Reset shared state between tests."""
    rate_limit_store.clear()
    latest_results.clear()
    yield


# --- Health & UI ---


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_homepage_returns_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "News Classifier" in response.text
    assert "text/html" in response.headers["content-type"]


# --- CORS ---


def test_cors_headers_present():
    response = client.options(
        "/classify",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" in response.headers


# --- Input validation ---


def test_classify_rejects_missing_url():
    response = client.post("/classify", json={})
    assert response.status_code == 422


def test_classify_rejects_invalid_url():
    response = client.post("/classify", json={"url": "not-a-url"})
    assert response.status_code == 422


def test_classify_rejects_empty_url():
    response = client.post("/classify", json={"url": ""})
    assert response.status_code == 422


def test_classify_rejects_ftp_url():
    response = client.post("/classify", json={"url": "ftp://example.com/file"})
    assert response.status_code == 422


# --- Error page detection ---


def test_detect_error_page_404():
    assert detect_error_page("404 Not Found - The page you requested does not exist") is True


def test_detect_error_page_403():
    assert detect_error_page("403 Forbidden - Access Denied") is True


def test_detect_error_page_normal_article():
    assert detect_error_page("EU regulators announced new guidelines for wealth management firms today...") is False


def test_detect_error_page_short_with_error():
    assert detect_error_page("Error 404") is True


def test_detect_error_page_long_valid():
    assert detect_error_page("A" * 500 + " This is a long article about something.") is False


# --- Label derivation ---


def test_derive_label_positive():
    assert derive_label(0.85, 0.65) == "POSITIVE"


def test_derive_label_negative():
    assert derive_label(0.80, -0.55) == "NEGATIVE"


def test_derive_label_neutral():
    assert derive_label(0.70, 0.10) == "NEUTRAL"


def test_derive_label_unrelated():
    assert derive_label(0.15, 0.0) == "UNRELATED"


def test_derive_label_boundary_relevance():
    """Relevance exactly at 0.3 should be NEUTRAL (not UNRELATED)."""
    assert derive_label(0.30, 0.0) == "NEUTRAL"


def test_derive_label_boundary_sentiment():
    """Sentiment exactly at 0.3 should be NEUTRAL (not POSITIVE)."""
    assert derive_label(0.80, 0.30) == "NEUTRAL"


# --- Rate limiting ---


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_rate_limiting_blocks_after_limit(mock_fetch, mock_classify):
    mock_fetch.return_value = "Some article text."
    mock_classify.return_value = {
        "relevance": 0.05,
        "sentiment": 0.0,
        "reasoning": "Test.",
        "relevance_topics": [],
    }

    for i in range(settings.rate_limit):
        resp = client.post("/classify", json={"url": f"https://example.com/{i}"})
        assert resp.status_code == 200

    resp = client.post("/classify", json={"url": "https://example.com/blocked"})
    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["detail"]


# --- Classification with mocked dependencies ---


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_classify_positive(mock_fetch, mock_classify):
    mock_fetch.return_value = "Vanguard launches AI tool for wealth management portfolios."
    mock_classify.return_value = {
        "relevance": 0.88,
        "sentiment": 0.65,
        "reasoning": "AI adoption in wealth management validates Performativ's market.",
        "relevance_topics": ["AI in wealth management", "portfolio management"],
    }

    response = client.post("/classify", json={"url": "https://example.com/article"})
    assert response.status_code == 200

    data = response.json()
    assert data["label"] == "POSITIVE"
    assert data["relevance"] == 0.88
    assert data["sentiment"] == 0.65
    assert "url" in data
    assert "processed_at" in data
    assert len(data["relevance_topics"]) > 0


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_classify_unrelated(mock_fetch, mock_classify):
    mock_fetch.return_value = "Taylor Swift announces new world tour dates for 2026."
    mock_classify.return_value = {
        "relevance": 0.03,
        "sentiment": 0.0,
        "reasoning": "Entertainment news with no connection to wealth management or fintech.",
        "relevance_topics": [],
    }

    response = client.post("/classify", json={"url": "https://example.com/entertainment"})
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "UNRELATED"
    assert data["relevance"] == 0.03
    assert data["sentiment"] == 0.0


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_classify_negative(mock_fetch, mock_classify):
    mock_fetch.return_value = "EU introduces strict regulations on wealth management AI tools."
    mock_classify.return_value = {
        "relevance": 0.85,
        "sentiment": -0.65,
        "reasoning": "New regulation could increase compliance burden for wealth tech platforms.",
        "relevance_topics": ["regulation", "compliance"],
    }

    response = client.post("/classify", json={"url": "https://example.com/regulation"})
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "NEGATIVE"
    assert data["relevance"] == 0.85
    assert data["sentiment"] == -0.65
    assert 0 <= data["relevance"] <= 1
    assert -1 <= data["sentiment"] <= 1


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_classify_neutral(mock_fetch, mock_classify):
    """Article that is relevant but neither positive nor negative."""
    mock_fetch.return_value = "UK wealth management firms ranked by assets under management."
    mock_classify.return_value = {
        "relevance": 0.74,
        "sentiment": 0.12,
        "reasoning": "Industry overview relevant to Performativ's market but with no clear positive or negative impact.",
        "relevance_topics": ["wealth management"],
    }

    response = client.post("/classify", json={"url": "https://example.com/overview"})
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "NEUTRAL"
    assert 0 <= data["relevance"] <= 1
    assert -1 <= data["sentiment"] <= 1


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_response_has_no_confidence(mock_fetch, mock_classify):
    """Verify confidence field is not in the response (removed by design)."""
    mock_fetch.return_value = "Some article text."
    mock_classify.return_value = {
        "relevance": 0.50,
        "sentiment": 0.40,
        "reasoning": "Relevant article.",
        "relevance_topics": ["wealth tech"],
    }

    response = client.post("/classify", json={"url": "https://example.com/test"})
    data = response.json()
    assert "confidence" not in data
    assert "relevance" in data
    assert "sentiment" in data


# --- Latest endpoint ---


@patch("main.classify_with_claude", new_callable=AsyncMock)
@patch("main.fetch_article_text", new_callable=AsyncMock)
def test_latest_returns_recent_results(mock_fetch, mock_classify):
    mock_fetch.return_value = "Some article text."
    mock_classify.return_value = {
        "relevance": 0.80,
        "sentiment": -0.5,
        "reasoning": "Negative regulation impact.",
        "relevance_topics": ["regulation"],
    }

    client.post("/classify", json={"url": "https://example.com/a"})
    client.post("/classify", json={"url": "https://example.com/b"})

    response = client.get("/latest?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["url"] == "https://example.com/b"


def test_latest_empty():
    response = client.get("/latest")
    assert response.status_code == 200
    assert response.json() == []
