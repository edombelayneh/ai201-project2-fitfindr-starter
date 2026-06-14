"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# How many top matches search_listings returns (the agent picks the first).
_MAX_RESULTS = 3

# Tiny stop-word list so common filler words don't inflate keyword scores.
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "for", "with", "in", "of", "to",
    "some", "any", "that", "this", "my", "i", "im", "looking", "want",
    "need", "find", "something", "size", "under", "around", "about",
}


def _tokenize(text: str) -> list[str]:
    """Lower-case a string and split it into alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _searchable_text(listing: dict) -> str:
    """Flatten the fields of a listing we want to match keywords against."""
    parts = [
        listing.get("title", ""),
        listing.get("description", ""),
        listing.get("category", ""),
        listing.get("brand") or "",
        " ".join(listing.get("style_tags", [])),
        " ".join(listing.get("colors", [])),
    ]
    return " ".join(parts)


def _size_matches(query_size: str, listing_size: str) -> bool:
    """
    Case-insensitive size match on shared tokens.

    Each size string is split into alphanumeric tokens and matched on overlap,
    so "M" matches "S/M" or "M/L" and "W30" matches "W30 L30", while "L" does
    NOT match "XXL" (no shared token).
    """
    q = set(_tokenize(query_size))
    if not q:
        return True
    return bool(q & set(_tokenize(listing_size)))


# ── Groq client ───────────────────────────────────────────────────────────────

# Default chat model; override with GROQ_MODEL in .env if needed.
_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

# Search lisitings is going to take the listings.json file 
# Based on the description it gets, it is to filter and return the sorted best 3 matches 

# Example:
# returns 3 matching listings sorted by relevance. 
# FitFindr picks the top result: "Faded Band Tee — $22, Depop, Good condition."

# If search_listings returns nothing, FitFindr tells the user what to try differently and stops — 
# it does not call suggest_outfit with empty input.

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Keyword set from the description, with filler words removed.
    keywords = {tok for tok in _tokenize(description) if tok not in _STOP_WORDS}

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # Filter: price ceiling (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue
        # Filter: size, when requested.
        if size is not None and not _size_matches(size, listing["size"]):
            continue
        # Score: how many distinct query keywords appear in the listing text.
        listing_tokens = set(_tokenize(_searchable_text(listing)))
        score = len(keywords & listing_tokens)
        if score == 0:
            continue
        scored.append((score, listing))

    # Highest score first; return the listing dicts only (top matches).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _score, listing in scored[:_MAX_RESULTS]]


def diagnose_empty_search(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> str:
    """
    Explain *why* a search returned nothing by re-running it with filters peeled
    off, then return a user-facing message suggesting what to try differently.

    Called by the planning loop only when search_listings() returns []. The
    re-searches run in the order from planning.md: drop price → drop size →
    description only.

    Args:
        description: The same description passed to the failed search.
        size:        The size filter that was applied, if any.
        max_price:   The price ceiling that was applied, if any.

    Returns:
        A message string for session["error"]. Always non-empty.
    """
    # 1. Was price the blocker? Re-search keeping size but dropping the ceiling.
    if max_price is not None:
        no_price = search_listings(description, size=size, max_price=None)
        if no_price:
            cheapest = min(item["price"] for item in no_price)
            return (
                f"Found a match for \"{description}\", but the cheapest is "
                f"${cheapest:.0f} — over your ${max_price:.0f} limit. "
                f"Try raising your max to about ${cheapest:.0f}."
            )

    # 2. Was size the blocker? Re-search keeping the price ceiling but any size.
    if size is not None:
        no_size = search_listings(description, size=None, max_price=max_price)
        if no_size:
            available = sorted({item["size"] for item in no_size})
            return (
                f"Found a match for \"{description}\", but not in size "
                f"\"{size}\". Available sizes: {', '.join(available)}. "
                f"Try a different size."
            )

    # 3. The item itself isn't available — ask the user to change the search.
    return (
        f"Couldn't find anything matching \"{description}\". "
        f"Try different keywords or a broader description."
    )


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

# Suggest outfit is going to take the item that search listings returns 
# It should also take the user's wardrobe from wardrobe_schema.json 
# Based on the item and the wardrobe it should suggest an outfit 

# Example:
# "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. 
# Roll the sleeves once and tuck the front corner slightly for shape."

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    client = _get_groq_client()

    item_line = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", [])
    if not items:
        # No wardrobe to pull from — ask for general styling advice instead.
        prompt = (
            f"A thrifter is considering buying: {item_line}.\n\n"
            "They haven't told you what's in their wardrobe. Give general "
            "styling advice for this piece: what kinds of items pair well with "
            "it, what vibe it suits, and one or two specific outfit ideas. "
            "Keep it to 3-4 sentences, warm and concrete."
        )
    else:
        # Format named wardrobe pieces so the LLM can reference them directly.
        wardrobe_lines = "\n".join(
            f"- {w.get('name', 'item')} "
            f"({w.get('category', 'unknown')}; "
            f"{', '.join(w.get('colors', [])) or 'n/a'})"
            for w in items
        )
        prompt = (
            f"A thrifter is considering buying: {item_line}.\n\n"
            f"Here is their existing wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with specific, "
            "named pieces from their wardrobe above. Reference the pieces by "
            "name. Keep it to 3-4 sentences, warm and concrete."
        )

    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

# 
# Example:
# "thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories"

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no usable outfit text → return a descriptive error, never raise.
    if not outfit or not outfit.strip():
        return "Can't write a caption without an outfit suggestion."

    client = _get_groq_client()

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        "Write a short, casual outfit caption for a thrifted find, like a real "
        "OOTD post on Instagram or TikTok (not a product description).\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Rules: 2-4 sentences. Mention the item name, price, and platform "
        "naturally, once each. Capture the outfit's vibe in specific terms. "
        "Sound authentic and a little excited. Emoji are fine but optional."
    )

    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        # Higher temperature so captions vary across runs/inputs.
        temperature=1.0,
    )
    return response.choices[0].message.content.strip()
