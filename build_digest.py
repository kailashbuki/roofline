"""Per-area state of play, for catching up across several fronts at once.

Reading three headlines per area and assembling the picture yourself is the slow
path. This writes data/digest.json: one or two sentences per area covering the
recent window, synthesised from that area's highest-importance items.

Costs one request per active area (so ~6) per run, and degrades to no digest at
all rather than a fabricated one.

    python build_digest.py [--days 7]
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

import classifier
from classifier import AREAS, AREA_LABELS
from store import DATA_PATH

DIGEST_PATH = os.path.join("data", "digest.json")
MAX_ITEMS = 10


def synthesise(label, items):
    """One or two sentences on what happened in this area. None on any failure."""
    listing = "\n".join(
        f"- {a['title']}" + (f" — {a['why']}" if a.get("why") else "")
        for a in items
    )
    prompt = (
        f"These are the most notable {label} items published recently:\n\n"
        f"{listing}\n\n"
        "Write 1-2 sentences (maximum 45 words) telling a busy practitioner what "
        "is going on in this area right now. Name the specific themes or systems "
        "that recur. Do not list the items, do not say 'several papers' or "
        "'researchers are exploring', and do not hedge. If the items share no "
        "theme, say what the one or two most consequential ones are instead."
    )

    url, body = classifier.build_request([("", "")])  # reuse the configured surface
    if "contents" in body:
        body["contents"] = [{"parts": [{"text": prompt}]}]
        body["generationConfig"].pop("responseSchema", None)
        body["generationConfig"].pop("responseMimeType", None)
        body["generationConfig"]["maxOutputTokens"] = 2048
    else:
        body["input"] = prompt
        body.pop("response_format", None)

    import requests
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        classifier._throttle()
        classifier._state["calls"] += 1
        response = requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=90,
        )
        if response.status_code != 200:
            print(f"  {label}: HTTP {response.status_code}")
            return None
        return " ".join(classifier.extract_text(response.json()).split()) or None
    except Exception as exc:
        print(f"  {label}: {type(exc).__name__}: {exc}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    if not os.path.exists(DATA_PATH):
        return
    articles = json.load(open(DATA_PATH, encoding="utf-8"))["articles"]

    cutoff = (datetime.utcnow() - timedelta(days=args.days)).isoformat(timespec="seconds")
    by_area = defaultdict(list)
    for a in articles:
        if (a.get("published_date") or "") < cutoff:
            continue
        if not isinstance(a.get("importance"), (int, float)):
            continue
        by_area[a.get("area") or "other"].append(a)

    digest = {}
    for area in AREAS:
        if area == "other":
            continue
        items = sorted(by_area.get(area, []), key=lambda a: -a["importance"])[:MAX_ITEMS]
        if len(items) < 2:
            continue
        text = synthesise(AREA_LABELS[area], items)
        if text:
            digest[area] = {"text": text, "items": len(by_area[area])}
            print(f"  {area}: {text[:80]}...")

    if not digest:
        print("no digest produced (no key, or nothing to summarise)")
        return

    os.makedirs(os.path.dirname(DIGEST_PATH) or ".", exist_ok=True)
    with open(DIGEST_PATH, "w", encoding="utf-8") as handle:
        json.dump({
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "days": args.days,
            "areas": digest,
        }, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {DIGEST_PATH} ({len(digest)} areas)")


if __name__ == "__main__":
    main()
