"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import re

from tools import (
    _GROQ_MODEL,
    _get_groq_client,
    diagnose_empty_search,
    search_listings,
    suggest_outfit,
    create_fit_card,
)


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract structured search parameters from a free-text user query.

    Asks the LLM to pull out three fields and return them as JSON:
        description (str)        — keywords describing the item
        size        (str|None)  — requested size, or null if unstated
        max_price   (float|None)— price ceiling, or null if unstated

    Always returns a dict with those three keys. If the LLM call or JSON
    parsing fails for any reason, falls back to using the raw query as the
    description with no size/price filters, so the loop can still proceed.
    """
    fallback = {"description": query, "size": None, "max_price": None}

    prompt = (
        "Extract structured search parameters from a secondhand-shopping "
        "request. Return ONLY a JSON object with exactly these keys:\n"
        '  "description": a short keyword phrase for the item (string)\n'
        '  "size": the requested size, or null if not mentioned (string|null)\n'
        '  "max_price": the price ceiling as a number, or null if not '
        "mentioned (number|null)\n\n"
        "Do not include the size or price words in the description.\n\n"
        f'Request: "{query}"\n\n'
        "JSON:"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        # Strip ```json ... ``` fences the model sometimes adds.
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        # Grab the first {...} block in case of stray prose.
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
    except Exception:
        return fallback

    description = data.get("description") or query
    size = data.get("size") or None

    max_price = data.get("max_price")
    if isinstance(max_price, str):
        # "$30" / "30.00" → 30.0; anything unparseable → no ceiling.
        cleaned = re.sub(r"[^0-9.]", "", max_price)
        max_price = float(cleaned) if cleaned else None
    elif not isinstance(max_price, (int, float)):
        max_price = None

    return {
        "description": str(description),
        "size": str(size) if size is not None else None,
        "max_price": float(max_price) if max_price is not None else None,
    }


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this run.
    session = _new_session(query, wardrobe)

    # Step 2: parse the free-text query into structured search parameters.
    session["parsed"] = _parse_query(query)
    description = session["parsed"]["description"]
    size = session["parsed"]["size"]
    max_price = session["parsed"]["max_price"]

    # Step 3: search the listings with the parsed parameters.
    session["search_results"] = search_listings(description, size, max_price)
    if not session["search_results"]:
        # No matches — diagnose why and stop here. Never call suggest_outfit
        # with empty input.
        session["error"] = diagnose_empty_search(description, size, max_price)
        return session

    # Step 4: select the top (most relevant) match.
    session["selected_item"] = session["search_results"][0]

    # Step 5: suggest an outfit pairing the find with the user's wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], wardrobe
    )

    # Step 6: turn the outfit into a shareable caption.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
