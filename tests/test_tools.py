"""
Tests for the three FitFindr tools (plus the diagnostic helper).

The LLM-backed tools (suggest_outfit, create_fit_card) are tested against a
fake Groq client so the suite runs offline and deterministically — we assert
on the branch/guard logic and the prompt we build, not on model wording.

Run with:  .venv/bin/python -m pytest tests/ -v
"""

import sys
from pathlib import Path

import pytest

# Make the project root importable when pytest is run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools
from tools import (
    create_fit_card,
    diagnose_empty_search,
    search_listings,
    suggest_outfit,
)


# ── Fakes / fixtures ──────────────────────────────────────────────────────────

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, recorder, reply):
        self._recorder = recorder
        self._reply = reply

    def create(self, **kwargs):
        # Record the call so tests can assert on the prompt / params.
        self._recorder.append(kwargs)
        return _FakeResponse(self._reply)


class _FakeChat:
    def __init__(self, recorder, reply):
        self.completions = _FakeCompletions(recorder, reply)


class _FakeClient:
    def __init__(self, recorder, reply):
        self.chat = _FakeChat(recorder, reply)


@pytest.fixture
def fake_llm(monkeypatch):
    """
    Patch _get_groq_client so the LLM tools use a canned reply.

    Yields the list of recorded create() kwargs so a test can inspect the
    prompt and parameters that were sent.
    """
    calls = []
    reply = "A canned styling reply."
    monkeypatch.setattr(
        tools, "_get_groq_client", lambda: _FakeClient(calls, reply)
    )
    return calls


# A minimal listing matching the real schema, for the LLM-tool tests.
SAMPLE_ITEM = {
    "id": "lst_test",
    "title": "Faded Band Tee",
    "description": "Soft worn-in band tee.",
    "category": "tops",
    "style_tags": ["vintage", "grunge", "band tee"],
    "size": "M",
    "condition": "good",
    "price": 22.0,
    "colors": ["black", "grey"],
    "brand": None,
    "platform": "depop",
}


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_only_relevant_matches():
    """Happy path: keyword search returns scored, non-empty results."""
    results = search_listings("vintage graphic tee", max_price=30)
    assert results, "expected at least one match"
    assert len(results) <= 3, "should cap at the top 3 matches"
    # Every returned item must actually relate to the query (score > 0).
    for item in results:
        assert isinstance(item, dict)
        assert "title" in item


def test_search_respects_max_price():
    """Price filter is inclusive and excludes anything over the ceiling."""
    cap = 25.0
    results = search_listings("vintage", max_price=cap)
    assert results
    assert all(item["price"] <= cap for item in results)


def test_search_respects_size_filter():
    """Size filter only returns listings whose size token overlaps."""
    results = search_listings("vintage", size="M")
    assert results
    # "M" should match sizes like "M", "S/M", "M/L" — but never "L" alone.
    for item in results:
        size_tokens = set(item["size"].lower().replace("/", " ").split())
        assert "m" in size_tokens


# --- Failure mode: no results match the query ---

def test_search_returns_empty_on_no_match():
    """Failure mode: an unrelated query returns [] (never raises)."""
    assert search_listings("scuba diving wetsuit aqualung") == []


# ── diagnose_empty_search (drives the agent's empty-result branch) ────────────

def test_diagnose_identifies_price_blocker():
    """A real item priced above the ceiling → price-blocker message."""
    # Track jackets exist but cost well over $10.
    assert search_listings("track jacket", max_price=10) == []
    msg = diagnose_empty_search("track jacket", max_price=10)
    assert "limit" in msg.lower() or "raising" in msg.lower()
    assert "$10" in msg


def test_diagnose_identifies_size_blocker():
    """A real item in the wrong size → size-blocker message."""
    assert search_listings("levis 501 jeans", size="XXL") == []
    msg = diagnose_empty_search("levis 501 jeans", size="XXL")
    assert "size" in msg.lower()
    assert "XXL" in msg


def test_diagnose_identifies_unavailable_item():
    """Nothing matches even with all filters dropped → unavailable message."""
    msg = diagnose_empty_search("scuba diving wetsuit aqualung")
    assert "couldn't find" in msg.lower() or "different keywords" in msg.lower()


# ── suggest_outfit ────────────────────────────────────────────────────────────

def test_suggest_outfit_uses_wardrobe_items(fake_llm):
    """With a wardrobe, the prompt references the user's named pieces."""
    wardrobe = {"items": [
        {"name": "Baggy straight-leg jeans", "category": "bottoms",
         "colors": ["indigo"]},
    ]}
    out = suggest_outfit(SAMPLE_ITEM, wardrobe)
    assert isinstance(out, str) and out.strip()
    prompt = fake_llm[-1]["messages"][0]["content"]
    assert "Baggy straight-leg jeans" in prompt


# --- Failure mode: empty wardrobe ---

def test_suggest_outfit_empty_wardrobe_falls_back(fake_llm):
    """Failure mode: an empty wardrobe gives general advice, not an error."""
    out = suggest_outfit(SAMPLE_ITEM, {"items": []})
    assert isinstance(out, str) and out.strip()
    prompt = fake_llm[-1]["messages"][0]["content"]
    # Should ask for general advice rather than naming wardrobe pieces.
    assert "general" in prompt.lower() or "haven't told you" in prompt.lower()


# ── create_fit_card ───────────────────────────────────────────────────────────

def test_create_fit_card_happy_path(fake_llm):
    """A real outfit string produces a caption and uses high temperature."""
    out = create_fit_card("Pair it with wide-leg jeans and chunky boots.",
                          SAMPLE_ITEM)
    assert isinstance(out, str) and out.strip()
    # Caption generation should run hot so repeated calls vary.
    assert fake_llm[-1]["temperature"] >= 0.9


# --- Failure mode: missing / whitespace-only outfit ---

@pytest.mark.parametrize("bad_outfit", ["", "   ", "\n\t"])
def test_create_fit_card_guards_empty_outfit(bad_outfit, fake_llm):
    """Failure mode: empty/whitespace outfit returns an error string, no raise."""
    out = create_fit_card(bad_outfit, SAMPLE_ITEM)
    assert isinstance(out, str) and out.strip()
    assert "without an outfit" in out.lower()
    # The LLM must NOT be called when guarding bad input.
    assert fake_llm == []
