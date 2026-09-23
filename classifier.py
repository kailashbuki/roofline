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
from collections import namedtuple

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

# Exactly one area per article, so the briefing can be sectioned cleanly.
# Order is display order on the page.
AREAS = [
    "architecture",        # model architecture and algorithmic advances
    "new-models",          # releases, open weights, capability jumps
    "inference-methods",   # quantization, KV cache, speculative decoding, kernels
    "inference-engines",   # vLLM, SGLang, TRT-LLM, serving systems
    "silicon",             # chips, accelerators, memory, interconnect
    "training",            # pretraining, post-training, scaling
    "economics",           # cost per token, pricing, capacity and supply
    "other",
]

AREA_LABELS = {
    "architecture": "Model architecture",
    "new-models": "New models",
    "inference-methods": "Inference optimization",
    "inference-engines": "Inference engines & serving",
    "silicon": "Silicon",
    "training": "Training & post-training",
    "economics": "Cost & economics",
    "other": "Everything else",
}

SCOPE = (
    "a feed about the full AI performance stack: model architecture and "
    "algorithmic advances, training methods and scaling, post-training "
    "(fine-tuning, RLHF, distillation, quantization), inference optimization, "
    "serving systems and inference engines, distributed and systems-level "
    "improvements, AI chips and accelerators, and the ECONOMICS AND PHYSICAL "
    "CONSTRAINTS of all of it — cost per token, inference pricing, hardware and "
    "memory supply, fab and accelerator availability, and datacenter capacity, "
    "power and grid interconnect. Falling cost per token is a headline outcome of "
    "this stack, not a business-news sideshow, and power and capacity are the "
    "binding constraint on what anyone can actually run: treat both as in scope. "
    "What is NOT in scope: AI discourse, hype and opinion with no technical, cost "
    "or capacity content; product launches with no performance or price detail; "
    "AI safety and regulation debate; and applications built on top of models"
)

SCHEMA_UPPER = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "INTEGER"},
            "relevant": {"type": "BOOLEAN"},
            "area": {"type": "STRING", "enum": AREAS},
            "importance": {"type": "NUMBER"},
            "why": {"type": "STRING"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING", "enum": ALLOWED_TAGS}},
        },
        "required": ["id", "relevant", "area", "importance", "why", "tags"],
        "propertyOrdering": ["id", "relevant", "area", "importance", "why", "tags"],
    },
}

SCHEMA_LOWER = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "relevant": {"type": "boolean"},
            "area": {"type": "string", "enum": AREAS},
            "importance": {"type": "number"},
            "why": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string", "enum": ALLOWED_TAGS}},
        },
        "required": ["id", "relevant", "area", "importance", "why", "tags"],
    },
}

Verdict = namedtuple("Verdict", "score tags area importance why")

_state = {"calls": 0, "last_call": 0.0, "disabled": False}


def _fallback_one(title, summary):
    """Keyword scoring, used whenever Gemini is unavailable."""
    try:
        keywords = load_config().get("relevance", {})
    except Exception:
        keywords = {}
    return Verdict(
        score=calculate_relevance(title, summary, keywords),
        tags=extract_tags(title, summary),
        area="other",
        importance=None,     # no keyword proxy for "is this important"
        why="",
    )


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
        f"You are the editor of {SCOPE}.\n\n"
        f"Return one verdict per article, {len(items)} in total, echoing each "
        "article's id.\n"
        "- relevant: false if off-topic for that scope.\n"
        f"- area: the single best fit from {', '.join(AREAS)}.\n"
        "- importance: 0.0-1.0 — would a practitioner in this field need to know "
        "this? Judge on novelty of problem formulation or paradigm shift, "
        "creativity of methodology, surprisingness of results, potential impact "
        "on the field, and degree of departure from existing approaches. Be "
        "strict and use the full range: routine engineering, incremental "
        "benchmark gains, tutorials and marketing belong below 0.3; only a "
        "genuine shift in what is possible belongs above 0.8.\n"
        "- why: one sentence, at most 20 words. State what is NEW RELATIVE TO "
        "PRIOR WORK and what it enables. Never paraphrase or restate the title — "
        "if your sentence would still make sense as a subtitle, it is wrong. "
        "Prefer the concrete delta (a number, a mechanism, a constraint removed) "
        "over adjectives. No hype.\n"
        f"- tags: 1-4, only from {', '.join(ALLOWED_TAGS)}.\n\n"
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

        if not entry.get("relevant", entry.get("is_relevant", True)):
            # importance 0.0, NOT None. "Judged and rejected" must be
            # distinguishable from "never judged", or the row is re-sent to the
            # API on every backfill and the page reports it as unclassified
            # forever.
            results[index] = Verdict(0.0, "", "other", 0.0, "")
            continue

        importance = max(0.0, min(1.0, float(entry.get("importance", 0.5))))
        area = entry.get("area") if entry.get("area") in AREAS else "other"
        tags = ",".join(t for t in entry.get("tags", []) if t in ALLOWED_TAGS)
        results[index] = Verdict(
            score=importance,
            tags=tags,
            area=area,
            importance=importance,
            why=(entry.get("why") or "").strip()[:300],
        )

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

    out = []
    missing = 0
    for index, result in enumerate(results):
        if result is None:
            missing += 1
            out.append((_fallback_one(*items[index]), "keyword"))
        else:
            out.append((result, "gemini"))

    if missing and api_key and not _state["disabled"]:
        print(f"  ({missing} item(s) unclassified by Gemini, using keyword scoring)")
    return out


def classify_article(title, summary):
    """Single-item convenience wrapper. Prefer classify_many for whole feeds."""
    verdict, _ = classify_many([(title, summary)])[0]
    return verdict.score, verdict.tags

