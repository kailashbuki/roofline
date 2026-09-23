"""Probe which Gemini model + API surface works for your key.

The Gemini API moves: model ids retire and surfaces migrate, and free-tier model
availability varies by project. Rather than guessing, run this once:

    export GEMINI_API_KEY='...'
    python verify_gemini.py

It sends the exact BATCHED request the collectors send, then checks that every
article in the batch came back and that ids mapped correctly — a batch that
silently drops or misorders items is worse than one that fails outright.
"""
import json
import os
import sys

import requests

import classifier

CANDIDATES = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
]

# Deliberately mixed: two clearly in scope, one clearly not. A working setup must
# return three verdicts and score the third well below the others.
SAMPLE = [
    ("FlashAttention-3: Fast and Accurate Attention with Low-Precision GPU Kernels",
     "Speeds up attention on modern accelerators via better memory access "
     "patterns and FP8 arithmetic."),
    ("Blackwell Ultra: 288GB of HBM3e per package",
     "NVIDIA's latest accelerator raises memory capacity and bandwidth for "
     "large-model inference."),
    ("Best sourdough starter routine",
     "Feeding schedules and hydration ratios for a rye starter."),
]


def probe(model, api_style):
    classifier.MODEL = model
    classifier.API_STYLE = api_style
    url, body = classifier.build_request(SAMPLE)

    try:
        response = requests.post(
            url,
            headers={
                "x-goog-api-key": os.environ["GEMINI_API_KEY"],
                "Content-Type": "application/json",
            },
            json=body,
            timeout=90,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if response.status_code != 200:
        detail = response.text.replace("\n", " ").strip() or "(empty body)"
        return False, f"HTTP {response.status_code}: {detail[:150]}"

    try:
        text = classifier.extract_text(response.json())
    except Exception as exc:
        return False, f"bad response shape ({exc}): {str(response.json())[:150]}"

    try:
        verdicts = classifier.parse_verdicts(text, len(SAMPLE))
    except json.JSONDecodeError:
        return False, f"not valid JSON (structured output ignored?): {text[:150]}"

    missing = [i + 1 for i, v in enumerate(verdicts) if v is None]
    if missing:
        return False, f"batch incomplete — no verdict for id(s) {missing}"

    scores = [round(v[0], 2) for v in verdicts]
    # The third sample is off-topic. If it outscores the other two, either the
    # ids are misaligned or the prompt is being ignored.
    if scores[2] >= max(scores[0], scores[1]):
        return True, f"WARN ids may be misaligned (off-topic scored {scores[2]}): {scores}"

    return True, f"scores {scores}, tags [{verdicts[0][1] or '-'}]"


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY first: export GEMINI_API_KEY='...'")

    defaults = (classifier.API_STYLE, classifier.MODEL)
    working = []

    for api_style in ("generatecontent", "interactions"):
        print(f"\n=== {api_style} ===")
        for model in CANDIDATES:
            ok, detail = probe(model, api_style)
            print(f"  {'OK  ' if ok else 'FAIL'}  {model:24} {detail}")
            if ok and not detail.startswith("WARN"):
                working.append((api_style, model))

    print()
    if not working:
        sys.exit(
            "Nothing worked. Collection still runs using keyword scoring.\n"
            "Check the key at aistudio.google.com/apikey and that the\n"
            "Generative Language API is enabled for the project."
        )

    print("Working combination(s):")
    for style, model in working:
        print(f"  {style} + {model}")

    api_style, model = working[0]
    print("\n.github/workflows/collect.yml should set:")
    print(f"    GEMINI_MODEL: {model}")
    print(f"    GEMINI_API: {api_style}")
    print(f"\ncompiled-in defaults: {defaults[0]} + {defaults[1]}")
    if (api_style, model) != defaults:
        print("NOTE: the preferred combination differs from the defaults above.")


if __name__ == "__main__":
    main()
