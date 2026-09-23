"""Probe which Gemini model + API surface works for your key.

The Gemini API is mid-migration and free-tier model availability varies by
project, so rather than guessing, run this once:

    export GEMINI_API_KEY='...'
    python verify_gemini.py

It sends the exact request classifier.py sends, for each candidate model on
each API surface, and prints what to put in the workflow.
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

SAMPLE = (
    "FlashAttention-3: Fast and Accurate Attention with Low-Precision GPU Kernels",
    "We present a method that speeds up attention on modern accelerators by "
    "improving memory access patterns and using FP8 arithmetic.",
)


def probe(model, api_style):
    classifier.MODEL = model
    classifier.API_STYLE = api_style
    url, body = classifier.build_request(classifier.build_prompt(*SAMPLE))

    try:
        response = requests.post(
            url,
            headers={
                "x-goog-api-key": os.environ["GEMINI_API_KEY"],
                "Content-Type": "application/json",
            },
            json=body,
            timeout=45,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if response.status_code != 200:
        detail = response.text.replace("\n", " ").strip() or "(empty body)"
        return False, f"HTTP {response.status_code}: {detail[:160]}"

    try:
        text = classifier.extract_text(response.json())
    except Exception as exc:
        return False, f"unexpected response shape ({exc}): {str(response.json())[:160]}"

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False, f"not valid JSON (structured output ignored?): {text[:160]}"

    missing = [k for k in ("relevant", "score", "tags") if k not in parsed]
    if missing:
        # Schema was ignored rather than enforced; usable but worth flagging.
        return True, f"WARN schema not enforced (missing {missing}): {parsed}"

    return True, f"relevant={parsed['relevant']} score={parsed['score']} tags={parsed['tags']}"


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY first: export GEMINI_API_KEY='...'")

    working = []
    for api_style in ("generatecontent", "interactions"):
        print(f"\n=== {api_style} ===")
        for model in CANDIDATES:
            ok, detail = probe(model, api_style)
            print(f"  {'OK  ' if ok else 'FAIL'}  {model:24} {detail}")
            if ok:
                working.append((api_style, model))

    print()
    if not working:
        sys.exit(
            "Nothing worked. Collection still runs using keyword scoring.\n"
            "Check the key at aistudio.google.com/apikey and that the\n"
            "Generative Language API is enabled for the project."
        )

    api_style, model = working[0]
    print(f"Use these. In .github/workflows/collect.yml add to the collect step's env:")
    print(f"    GEMINI_MODEL: {model}")
    print(f"    GEMINI_API: {api_style}")
    print(f"\n({len(working)} working combination(s); the first is preferred.)")


if __name__ == "__main__":
    main()
