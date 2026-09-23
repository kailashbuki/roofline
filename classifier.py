"""Relevance classification and tagging via the Gemini API.

Articles are classified in BATCHES: one request carries up to BATCH_SIZE items
and gets back one verdict each. That is what makes it affordable to send every
candidate to the model instead of keyword-filtering first — a run that would
need ~330 single calls needs ~17 batched ones.

Reads GEMINI_API_KEY from the environment. If the key is missing, the quota is
exhausted, or anything else goes wrong, this degrades to the keyword scorer in
relevance_scorer.py rather than failing the collection run.

Two request shapes are supported, because the Gemini API is mid-migration:

  generatecontent POST /v1beta/models/{model}:generateContent  (default)
                  Verified working with gemini-3.5-flash-lite, which is also the
                  least likely to return 503 "high demand".
  interactions    POST /v1beta/interactions
                  Verified working with gemini-3.6-flash and gemini-3.8-flash.
                  The migration guide's /v1beta2/interactions path is wrong:
                  it 404s with an empty body on every model.

Select with GEMINI_API. Run verify_gemini.py to see what your key supports.
"""
import json
import os
import time

import requests

from relevance_scorer import calculate_relevance, extract_tags
from database import load_config

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_STYLE = os.environ.get("GEMINI_API", "generatecontent").lower()

GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
INTERACTIONS_URLS = {
    "interactions": "https://generativelanguage.googleapis.com/v1beta/interactions",
}

BATCH_SIZE = int(os.environ.get("GEMINI_BATCH_SIZE", "20"))
# Batching keeps request counts low, so the throttle can be modest. Free-tier
# limits are per-project (see aistudio.google.com/rate-limit).
MIN_INTERVAL_SECONDS = float(os.environ.get("GEMINI_MIN_INTERVAL", "2.0"))
# Ceiling on REQUESTS (not articles) per run.
MAX_CALLS_PER_RUN = int(os.environ.get("GEMINI_MAX_CALLS", "60"))
# Gemini 3 thinks by default and thought tokens count against the output cap,
# so scale it with batch size and leave headroom for reasoning.
BASE_OUTPUT_TOKENS = int(os.environ.get("GEMINI_BASE_OUTPUT_TOKENS", "2048"))
PER_ITEM_OUTPUT_TOKENS = 120
# Summaries are truncated before sending; full text adds cost without accuracy.
SUMMARY_CHARS = int(os.environ.get("GEMINI_SUMMARY_CHARS", "400"))

RETRY_ON = (500, 502, 503, 504)
MAX_ATTEMPTS = 3

# Spans the whole stack this feed covers, from algorithms down to silicon.
ALLOWED_TAGS = [
    "architecture", "training", "post-training", "inference", "serving",
    "systems", "hardware", "quantization", "attention", "compression",
    "optimization", "multimodal", "benchmarks", "llm",
]

SCOPE = (
    "a feed about the full AI performance stack: model architecture and "
    "algorithmic advances, training methods and scaling, post-training "
    "(fine-tuning, RLHF, distillation, quantization), inference optimization, "
    "serving systems and inference engines, distributed and systems-level "
    "improvements, and AI chips and accelerators"
)

_ITEM_PROPS = {
    "id": {"type": "INTEGER"},
    "relevant": {"type": "BOOLEAN"},
    "score": {"type": "NUMBER"},
    "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": ALLOWED_TAGS}},
}

SCHEMA_UPPER = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": _ITEM_PROPS,
        "required": ["id", "relevant", "score", "tags"],
        "propertyOrdering": ["id", "relevant", "score", "tags"],
    },
}

SCHEMA_LOWER = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "relevant": {"type": "boolean"},
            "score": {"type": "number"},
            "tags": {"type": "array", "items": {"type": "string", "enum": ALLOWED_TAGS}},
        },
        "required": ["id", "relevant", "score", "tags"],
    },
}

_state = {"calls": 0, "last_call": 0.0, "disabled": False}


def _fallback_one(title, summary):
    """Keyword scoring, used whenever Gemini is unavailable."""
    try:
        keywords = load_config().get("relevance", {})
    except Exception:
        keywords = {}
    return calculate_relevance(title, summary, keywords), extract_tags(title, summary)


def _throttle():
    elapsed = time.time() - _state["last_call"]
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _state["last_call"] = time.time()


def build_prompt(items):
    """items: list of (title, summary). Ids are 1-based and echoed back."""
    listing = []
    for index, (title, summary) in enumerate(items, start=1):
        clean = " ".join((summary or "").split())[:SUMMARY_CHARS]
        listing.append(f"[{index}] TITLE: {title}\n    SUMMARY: {clean}")

    return (
        f"You are triaging articles for {SCOPE}.\n\n"
        f"Return one verdict per article, {len(items)} in total, echoing each "
        "article's id.\n"
        "- relevant: false if the article is off-topic for that scope.\n"
        "- score: 0.0-1.0, how central it is to the scope.\n"
        f"- tags: choose only from {', '.join(ALLOWED_TAGS)}. Use 1-4 tags.\n\n"
        "Articles:\n" + "\n".join(listing)
    )


def build_request(items):
    """Return (url, body) for the configured API style."""
    prompt = build_prompt(items)
    max_tokens = BASE_OUTPUT_TOKENS + PER_ITEM_OUTPUT_TOKENS * len(items)

    if API_STYLE in INTERACTIONS_URLS:
        return INTERACTIONS_URLS[API_STYLE], {
            "model": MODEL,
            "input": prompt,
            "generation_config": {
                "thinking_level": "low",
                "max_output_tokens": max_tokens,
            },
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": SCHEMA_LOWER,
            },
        }

    return GENERATE_URL.format(model=MODEL), {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA_UPPER,
        },
    }


def extract_text(payload):
    """Pull the model's text out of whichever response shape came back."""
    if "steps" in payload:
        chunks = []
        for step in payload["steps"]:
            if step.get("type") != "model_output":
                continue
            for item in step.get("content", []):
                if item.get("type") == "text" and item.get("text"):
                    chunks.append(item["text"])
        return "".join(chunks)

    candidate = payload["candidates"][0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise ValueError(
            "response truncated by maxOutputTokens "
            "(lower GEMINI_BATCH_SIZE or raise GEMINI_BASE_OUTPUT_TOKENS)"
        )
    parts = candidate.get("content", {}).get("parts", [])
    return "".join(p["text"] for p in parts if "text" in p)


def parse_verdicts(text, count):
    """Map the model's array back onto the batch, keyed by echoed id.

    Anything the model failed to return is left as None so the caller can fall
    back for just those items rather than discarding the whole batch.
    """
    data = json.loads(text)
    if isinstance(data, dict):
        # Some responses wrap the array; accept the first list-valued field.
        data = next((v for v in data.values() if isinstance(v, list)), [])

    results = [None] * count
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("id", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= index < count:
            continue

        relevant = entry.get("relevant", entry.get("is_relevant", True))
        if not relevant:
            results[index] = (0.0, "")
            continue

        score = max(0.0, min(1.0, float(entry.get("score", 0.5))))
        tags = ",".join(t for t in entry.get("tags", []) if t in ALLOWED_TAGS)
        results[index] = (score, tags)

    return results


def _request_batch(items, api_key):
    """One batched call. Returns a list of verdicts, with None for gaps."""
    url, body = build_request(items)
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _throttle()
            _state["calls"] += 1
            response = requests.post(url, headers=headers, json=body, timeout=120)

            if response.status_code == 429:
                print("Gemini: rate limited, keyword scoring for the rest of this run")
                _state["disabled"] = True
                return [None] * len(items)

            if response.status_code in RETRY_ON and attempt < MAX_ATTEMPTS:
                wait = 2 ** attempt
                print(f"Gemini: {response.status_code} (transient), retrying in {wait}s")
                time.sleep(wait)
                continue

            if response.status_code in (400, 404):
                print(f"Gemini: {response.status_code} {response.text[:200]}")
                print("Gemini: disabling for this run; run verify_gemini.py to recheck")
                _state["disabled"] = True
                return [None] * len(items)

            response.raise_for_status()
            return parse_verdicts(extract_text(response.json()), len(items))

        except Exception as exc:
            if attempt >= MAX_ATTEMPTS:
                print(f"Gemini error ({type(exc).__name__}: {exc})")
                return [None] * len(items)
            time.sleep(2 ** attempt)

    return [None] * len(items)


def classify_many(items):
    """Classify (title, summary) pairs.

    Returns [(score, tags, judged_by), ...] aligned with the input, where
    judged_by is "gemini" or "keyword". Callers must not treat a "keyword"
    rejection as final — it is a low-confidence guess made because the model was
    unavailable, so recording it would permanently prevent a real verdict later.
    """
    if not items:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    results = [None] * len(items)

    if api_key and not _state["disabled"]:
        for start in range(0, len(items), BATCH_SIZE):
            if _state["disabled"]:
                break
            if _state["calls"] >= MAX_CALLS_PER_RUN:
                print("Gemini: per-run request cap reached, keyword scoring the rest")
                break

            chunk = items[start:start + BATCH_SIZE]
            verdicts = _request_batch(chunk, api_key)
            results[start:start + len(chunk)] = verdicts

    missing = sum(1 for r in results if r is None)
    if missing:
        if api_key and not _state["disabled"]:
            print(f"  ({missing} item(s) unclassified by Gemini, using keyword scoring)")
        for index, result in enumerate(results):
            if result is None:
                score, tags = _fallback_one(*items[index])
                results[index] = (score, tags, "keyword")

    return [r if len(r) == 3 else (r[0], r[1], "gemini") for r in results]


def classify_article(title, summary):
    """Single-item convenience wrapper. Prefer classify_many for whole feeds."""
    score, tags, _ = classify_many([(title, summary)])[0]
    return score, tags
