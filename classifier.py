"""Relevance classification via the Gemini API, with keyword fallback.

Drop-in replacement for the old bedrock_classifier: same classify_article()
signature, so collectors need no changes beyond the import.

Reads GEMINI_API_KEY from the environment. If the key is missing, the quota is
exhausted, or anything else goes wrong, this degrades to the keyword scorer
rather than failing the collection run.

Two request shapes are supported, because the Gemini API is mid-migration:

  generatecontent POST /v1beta/models/{model}:generateContent  (default)
                  Older surface, documented as "remains fully supported".
                  Verified working with gemini-3.5-flash-lite, which is also the
                  least likely to return 503 "high demand".
  interactions    POST /v1beta/interactions
                  Verified working with gemini-3.6-flash and gemini-3.8-flash.
                  The migration guide's /v1beta2/interactions path is wrong:
                  it 404s with an empty body on every model.

Select with GEMINI_API. Run verify_gemini.py to see which your key supports.
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

# Free-tier limits are per-project and no longer published per model (check
# aistudio.google.com/rate-limit), so default to something conservative.
MIN_INTERVAL_SECONDS = float(os.environ.get("GEMINI_MIN_INTERVAL", "4.5"))
# Hard ceiling per run so a large backfill cannot burn the daily quota.
MAX_CALLS_PER_RUN = int(os.environ.get("GEMINI_MAX_CALLS", "400"))
# Gemini 3 models think by default and thought tokens count against this, so it
# needs real headroom — a small value truncates the JSON mid-object.
MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "2048"))
# 503 "high demand" is transient and worth retrying.
RETRY_ON = (503, 500, 502, 504)
MAX_ATTEMPTS = 3

ALLOWED_TAGS = [
    "quantization", "inference", "optimization", "attention",
    "compression", "hardware", "multimodal", "llm",
]

# generateContent's schema dialect uses upper-case type names.
SCHEMA_UPPER = {
    "type": "OBJECT",
    "properties": {
        "relevant": {"type": "BOOLEAN"},
        "score": {"type": "NUMBER"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": ALLOWED_TAGS}},
    },
    "required": ["relevant", "score", "tags"],
    "propertyOrdering": ["relevant", "score", "tags"],
}

# The Interactions API uses standard JSON Schema lower-case types.
SCHEMA_LOWER = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "score": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string", "enum": ALLOWED_TAGS}},
    },
    "required": ["relevant", "score", "tags"],
}

_state = {"calls": 0, "last_call": 0.0, "disabled": False}
_cache = {}


def _fallback(title, summary):
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


def build_prompt(title, summary):
    return (
        "Is this article about inference optimization of foundation models on "
        "AI accelerators?\n\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        "Score 0.0-1.0 for how relevant it is to that topic. Set relevant to "
        "false if it is off-topic. "
        f"Choose tags only from: {', '.join(ALLOWED_TAGS)}"
    )


def build_request(prompt):
    """Return (url, body) for the configured API style."""
    if API_STYLE in INTERACTIONS_URLS:
        return INTERACTIONS_URLS[API_STYLE], {
            "model": MODEL,
            "input": prompt,
            "generation_config": {"thinking_level": "low"},
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
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
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
        raise ValueError("response truncated by maxOutputTokens (raise GEMINI_MAX_OUTPUT_TOKENS)")
    parts = candidate.get("content", {}).get("parts", [])
    return "".join(p["text"] for p in parts if "text" in p)


def parse_result(text):
    """Turn the model's JSON into (score, tags), tolerating key drift."""
    data = json.loads(text)

    relevant = data.get("relevant", data.get("is_relevant", True))
    if not relevant:
        return 0.0, ""

    score = max(0.0, min(1.0, float(data.get("score", 0.5))))
    tags = ",".join(t for t in data.get("tags", []) if t in ALLOWED_TAGS)
    return score, tags


def classify_article(title, summary):
    """Return (relevance_score, comma-separated tags)."""
    cache_key = (title or "")[:300]
    if cache_key in _cache:
        return _cache[cache_key]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or _state["disabled"]:
        return _fallback(title, summary)

    if _state["calls"] >= MAX_CALLS_PER_RUN:
        print("Gemini: per-run call cap reached, using keyword scoring")
        _state["disabled"] = True
        return _fallback(title, summary)

    url, body = build_request(build_prompt(title, summary))
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _throttle()
            _state["calls"] += 1
            response = requests.post(url, headers=headers, json=body, timeout=45)

            if response.status_code == 429:
                print("Gemini: rate limited, keyword scoring for the rest of this run")
                _state["disabled"] = True
                return _fallback(title, summary)

            if response.status_code in RETRY_ON and attempt < MAX_ATTEMPTS:
                wait = 2 ** attempt
                print(f"Gemini: {response.status_code} (transient), retrying in {wait}s")
                time.sleep(wait)
                continue

            if response.status_code in (400, 404):
                # Wrong model id or a surface that moved again. Stop retrying
                # this for every remaining article.
                print(f"Gemini: {response.status_code} {response.text[:200]}")
                print("Gemini: disabling for this run; run verify_gemini.py to recheck")
                _state["disabled"] = True
                return _fallback(title, summary)

            response.raise_for_status()
            result = parse_result(extract_text(response.json()))
            _cache[cache_key] = result
            return result

        except Exception as exc:
            if attempt >= MAX_ATTEMPTS:
                print(f"Gemini error ({type(exc).__name__}: {exc}), using keyword scoring")
                result = _fallback(title, summary)
                _cache[cache_key] = result
                return result
            time.sleep(2 ** attempt)

    result = _fallback(title, summary)
    _cache[cache_key] = result
    return result
