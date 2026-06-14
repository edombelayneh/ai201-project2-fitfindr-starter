# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**

<!-- Describe what this tool does in 1–2 sentences -->

It searches the listings dataset for items that match the description, size, and price. It scores each item by keyword overlap with the description, drops items that score 0, and returns the matches sorted with the best match first.

**Input parameters:**

<!-- List each parameter, its type, and what it represents -->

- `description` (str): Keywords describing what the user is looking for, like "vintage graphic tee".
- `size` (str): The size to filter by. Matching is case-insensitive. It can be `None` to skip size filtering.
- `max_price` (float): The maximum price, included in the match. It can be `None` to skip price filtering.

**What it returns:**

<!-- Describe the return value -->

It returns a list of matching listing dictionaries, sorted by relevance (best match first). Each listing has these fields: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand`, and `platform`.

**What happens if it fails or returns nothing:**

<!-- What should the agent do if there were no matching listings -->

If nothing matches, it returns an empty list. It does not raise an exception. The agent tells the user what to try differently and stops. It does not call `suggest_outfit` with empty input.

---

### Tool 2: suggest_outfit

**What it does:**

<!-- Describe what this tool does in 1–2 sentences -->

It takes a thrifted item and the user's wardrobe and asks the LLM to suggest 1–2 complete outfits. It pairs the new item with named pieces from the wardrobe.

**Input parameters:**

<!-- List each parameter, its type, and what it represents -->

- `new_item` (dict): A listing dictionary — the item the user is thinking about buying.
- `wardrobe` (dict): A wardrobe dictionary with an `items` key that holds a list of wardrobe item dictionaries. It may be empty.

**What it returns:**

<!-- Describe the return value -->

It returns a non-empty string with outfit suggestions.

**What happens if it fails or returns nothing:**

<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->

If the wardrobe is empty, it does not raise an exception or return an empty string. Instead, it asks the LLM for general styling advice for the item and returns that.

---

### Tool 3: create_fit_card

**What it does:**

<!-- Describe what this tool does in 1–2 sentences -->

It takes the outfit suggestion and the thrifted item and asks the LLM to write a short, shareable caption for the find. The caption sounds casual, like a real OOTD post for Instagram or TikTok.

**Input parameters:**

<!-- List each parameter, its type, and what it represents -->

- `outfit` (str): The outfit suggestion string that came from `suggest_outfit()`.
- `new_item` (dict): The listing dictionary for the thrifted item.

**What it returns:**

<!-- Describe the return value -->

It returns a 2–4 sentence string that can be used as an Instagram or TikTok caption. It mentions the item name, price, and platform once each.

**What happens if it fails or returns nothing:**

<!-- What should the agent do if the outfit data is incomplete? -->

If the outfit string is empty or only whitespace, it returns a descriptive error message string. It does not raise an exception.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

### Tool 4: diagnose_empty_search

**What it does:**

When `search_listings` returns nothing, this tool figures out _why_ by re-running the search with filters peeled off one at a time, then returns a user-facing message explaining what to try differently. The planning loop calls it only on the empty-result branch.

**Input parameters:**

- `description` (str): The same description passed to the failed search.
- `size` (str): The size filter that was applied, or `None` if none was.
- `max_price` (float): The price ceiling that was applied, or `None` if none was.

**What it returns:**

A non-empty message string for `session["error"]`. The message is case-specific:

- **Price was the blocker** (re-search with `max_price` dropped finds matches) → says the item exists but is over budget and suggests a higher max.
- **Size was the blocker** (re-search with `size` dropped finds matches) → says the item exists but not in that size and lists available sizes.
- **Item unavailable** (description alone still finds nothing) → asks the user to try different keywords.

**What happens if it fails or returns nothing:**

It always returns a non-empty string — the third (unavailable) branch is the catch-all fallback, so there is no path that returns an empty message or raises.

---

## Planning Loop

**How does your agent decide which tool to call next?**

<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

The loop runs the three tools in a fixed order, using the `session` dict as shared memory. After each tool it checks a condition before deciding whether to continue.

1. **Parse the query (LLM).** Send `session["query"]` to the LLM and ask it to pull out `description`, `size`, and `max_price` as structured fields. This handles messy free text like "vintage tee under $30, size M" cleanly. Store the result in `session["parsed"]`.

2. **Search.** Call `search_listings(description, size, max_price)` and store the list in `session["search_results"]`.
   - **If it has results:** set `session["selected_item"] = search_results[0]` (top match) and continue to step 3.
   - **If it's empty:** run quick diagnostic searches to figure out _why_, then write a case-by-case message into `session["error"]` and `return session` early (no other tools called):
     - Re-search with `max_price` removed. If matches now appear → price was the blocker. Tell the user the item exists but is over their budget, and suggest the lowest price that would match (e.g. "Found a vintage tee, but the cheapest is $28 — try raising your max to $30.").
     - Else re-search with `size` removed. If matches now appear → size was the blocker. Tell the user the item exists but not in their size, and suggest trying a different size.
     - Else (description alone finds nothing) → the item itself isn't available. Ask the user to change what they're searching for.

3. **Suggest outfit.** Call `suggest_outfit(selected_item, wardrobe)` and store the string in `session["outfit_suggestion"]`. Always returns a non-empty string (falls back to general advice for an empty wardrobe), so there is no branch here.

4. **Make the card.** Call `create_fit_card(outfit_suggestion, selected_item)` and store it in `session["fit_card"]`.

5. **Done.** Return `session`. The loop is finished when `fit_card` is set, or earlier if `error` was set in step 2.

---

## State Management

**How does information from one tool get passed to the next?**

<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

All state lives in a single `session` dict created by `_new_session()` at the start of each run. It is the one source of truth. Each tool reads what it needs from the dict and writes its result back, so the next tool can pick it up:

- `query` → read by the parse step, which writes `parsed`
- `parsed` → feeds the arguments to `search_listings`, which writes `search_results`
- `search_results[0]` → saved as `selected_item`, passed into both `suggest_outfit` and `create_fit_card`
- `wardrobe` → stored at startup, passed into `suggest_outfit`
- `outfit_suggestion` → written by `suggest_outfit`, read by `create_fit_card`, which writes `fit_card`
- `error` → stays `None` unless a step ends early; the caller checks it first

Nothing is passed through global variables — every value moves from one tool to the next through this `session` dict.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool            | Failure mode                          | Agent response                                                                                                                                                                                                                                                                                                                                  |
| --------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| search_listings | No results match the query            | Run diagnostic re-searches (drop price → drop size → description-only) to find the cause, then return early with a case-by-case message: too expensive → suggest a higher max; wrong size → suggest a different size; item unavailable → ask to change the search.                                                                              |
| suggest_outfit  | Wardrobe is empty                     | Don't error — ask the LLM for general styling advice for the item and return that string.                                                                                                                                                                                                                                                       |
| create_fit_card | Outfit input is missing or incomplete | Guard on an empty or whitespace-only `outfit` string and return a descriptive error message as the `fit_card` value (no exception); the run still completes. This branch shouldn't trigger in the normal loop since `suggest_outfit` always returns a non-empty string — it's a safety net for direct calls or a future broken upstream result. |

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->

```mermaid
flowchart TD
    User([User query]) -->|query string| Loop[Planning Loop]

    Loop -->|query| Parse[Parse query with LLM]
    Parse -->|"parsed: description, size, max_price"| Search["search_listings(description, size, max_price)"]

    Search -->|"results = [item, ...]"| Select["Session: selected_item = results[0]"]
    Search -->|"results = []"| Diag{Diagnostic re-searches}

    Diag -->|drop max_price, matches found| ErrPrice["ERROR: item exists but over budget, suggest a higher max"]
    Diag -->|drop size, matches found| ErrSize["ERROR: item exists but not in your size, suggest a different size"]
    Diag -->|description-only, still empty| ErrItem["ERROR: item unavailable, ask user to change the search"]

    ErrPrice -->|"session.error set"| ReturnErr([Return session early])
    ErrSize -->|"session.error set"| ReturnErr
    ErrItem -->|"session.error set"| ReturnErr

    Select -->|"selected_item + wardrobe"| Suggest["suggest_outfit(selected_item, wardrobe)"]
    Suggest -->|"session.outfit_suggestion"| Card["create_fit_card(outfit_suggestion, selected_item)"]
    Card -->|"session.fit_card"| ReturnOk([Return session])

    State[("Session state: query / parsed / search_results / selected_item / wardrobe / outfit_suggestion / fit_card / error")]
    Search -.->|writes search_results| State
    Select -.->|writes selected_item| State
    Suggest -.->|writes outfit_suggestion| State
    Card -.->|writes fit_card| State
    Diag -.->|writes error| State
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

**Tool:** Claude (via Claude Code in VS Code).

**Input:** The Tool 1/2/3 specs above — each tool's inputs, return value, and failure mode — plus the `load_listings()` / `get_example_wardrobe()` signatures from `utils/data_loader.py` and the listing field list. For the LLM-backed tools I also gave it the exact failure behavior (empty wardrobe → general advice; empty outfit → error string, never raise).

**What I expect it to produce:**

- `search_listings()` — load listings, filter by `max_price` and `size`, score by keyword overlap with the description, drop score-0 items, return the top 3 sorted by score.
- `diagnose_empty_search()` — re-run the search peeling off filters in order (drop price → drop size → description-only) to explain _why_ nothing matched.
- `suggest_outfit()` — branch on empty vs. populated wardrobe and build the right LLM prompt.
- `create_fit_card()` — guard empty/whitespace outfit, otherwise build a high-temperature caption prompt.

**How I'll verify before moving on:** Run `pytest tests/ -v`. The suite uses a fake Groq client so it's offline and deterministic — it asserts the branch/guard logic and the prompt text, not model wording. Checks include: search returns only relevant matches, respects price and size filters, returns `[]` (never raises) on no match; the three diagnostic branches; empty-wardrobe fallback; and the empty-outfit guard (LLM not called). All 13 tests must pass.

**Milestone 4 — Planning loop and state management:**

**Tool:** Claude (via Claude Code in VS Code).

**Input:** The Planning Loop, State Management, and Error Handling sections above, plus the Mermaid diagram and the `_new_session()` field list. I told it parsing is LLM-based (per the Planning Loop step 1) and that the empty-result branch must call `diagnose_empty_search()` and return early without calling `suggest_outfit()`.

**What I expect it to produce:**

- `_parse_query()` — an LLM call (temperature 0) that returns `{description, size, max_price}` as JSON, with a fallback to `{description: query, size: None, max_price: None}` if the call or JSON parse fails, plus `"$30"` → `30.0` coercion.
- `run_agent()` — the 7-step loop reading/writing only the `session` dict: init → parse → search → (empty → diagnose + early return) → select top result → suggest_outfit → create_fit_card → return.
- `handle_query()` in `app.py` — guard empty query, pick wardrobe from the radio choice, call `run_agent()`, show `session["error"]` in panel 1 on early exit, else format `selected_item` into a listing card alongside the outfit and fit card.

**How I'll verify before moving on:** Re-run `pytest tests/` to confirm the tools still pass (13/13). Then run the `agent.py` CLI and `handle_query()` directly across three paths — happy path (listing + outfit + card all populated), no-results path (diagnostic message in panel 1, other panels empty), and empty query (guard message, no agent call). Finally launch `python app.py` and confirm the same behavior end-to-end in the Gradio UI.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**

<!-- What does the agent do first? Which tool is called? With what input? -->

The tool takes in the input from the user query and calls the search_listings() tool.
It takes the size, max_price and the description to match the listings that are available and returns 3 best matches sorted in order.

**Step 2:**

<!-- What happens next? What was returned from step 1? What tool is called now? -->

Step 1 might return one of two things:

1. If the search_listings() tool returns matching items from the listing, suggest_outfit() tool will be called. suggest_outfit() takes the items returned and looks through the users wardrobe found in the wardrobe_utils.json, to suggest a cohesive outfit. Moves on to step 3.
2. If the search_listings() tool doesnt return matching items from the listing, then it doesnt call suggest_outfit(). In this case it tells the user to try a different thing and stops. If user responds it loops back to step 1.

**Step 3:**

<!-- Continue until the full interaction is complete -->

Based on the outfit that was generated and the new item that was found, it generates a short, shareable description, for instagram.

**Final output to user:**

<!-- What does the user actually see at the end? -->
## Happy Path
1.  happy path (parses price, finds a match, full output)
   <img width="1259" height="544" alt="Screenshot 2026-06-14 at 3 33 49 PM" src="https://github.com/user-attachments/assets/5183f734-d3ce-4156-b916-6ea16607adea" />

2.  happy path with a size filter
   <img width="1238" height="565" alt="Screenshot 2026-06-14 at 3 34 48 PM" src="https://github.com/user-attachments/assets/29421683-eddf-4a87-a6af-4eaca5a424ec" />

3.  happy path, different category
   <img width="1260" height="570" alt="Screenshot 2026-06-14 at 3 34 07 PM" src="https://github.com/user-attachments/assets/c4fe00d6-bffc-4656-be86-549022f0aec6" />

## No Results - (shows the diagnostic error)
<img width="1262" height="535" alt="Screenshot 2026-06-14 at 3 34 33 PM" src="https://github.com/user-attachments/assets/57359a64-f230-4d08-b55e-2a8f043c3347" />

