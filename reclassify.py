"""Re-score and re-tag articles already in the store.

Classification normally runs only on new URLs, so rows scored during a run where
Gemini was unavailable keep their keyword-era tags forever. This re-judges them.

    export GEMINI_API_KEY='...'
    python reclassify.py              # only rows that look keyword-scored
    python reclassify.py --all        # every row
    python reclassify.py --dry-run    # show what would change, write nothing

Batched like the collectors, so the whole back catalogue costs roughly
len(articles)/GEMINI_BATCH_SIZE requests.
"""
import argparse
import os
import sys

from classifier import classify_many, ALLOWED_TAGS
from store import read_json, DATA_PATH
import json

# Tags from the pre-rebrand taxonomy: their presence means the row predates the
# current classifier, or was scored by the keyword fallback.
LEGACY_TAGS = {"ai", "llm_inference", "accelerator"}


def looks_keyword_scored(article):
    """True when the row has never been seen by the model.

    The briefing needs area, importance and why on every row; their absence is
    the definitive signal, so it is checked first.
    """
    if not isinstance(article.get("importance"), (int, float)):
        return True
    if not article.get("area") or article["area"] == "other":
        return True
    tags = {t for t in (article.get("tags") or "").split(",") if t}
    if not tags or tags & LEGACY_TAGS:
        return True
    return bool(tags - set(ALLOWED_TAGS))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="re-judge every article")
    parser.add_argument("--rejected", action="store_true",
                        help="re-judge rows scored 0.0, e.g. after widening the scope")
    parser.add_argument("--dry-run", action="store_true", help="report only")
    parser.add_argument("--limit", type=int, default=0, help="cap how many to re-judge")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set — this would just rewrite keyword scores.")

    payload = json.load(open(DATA_PATH, encoding="utf-8"))
    articles = payload["articles"]

    if args.rejected:
        targets = [a for a in articles if a.get("importance") == 0.0 or looks_keyword_scored(a)]
    else:
        targets = [a for a in articles if args.all or looks_keyword_scored(a)]
    if args.limit:
        targets = targets[:args.limit]

    print(f"{len(articles)} articles in store, {len(targets)} to re-judge")
    if not targets:
        return

    verdicts = classify_many([(a["title"], a.get("summary", "")) for a in targets])

    changed = 0
    by_model = 0
    for article, (verdict, judged_by) in zip(targets, verdicts):
        if judged_by != "gemini":
            continue
        by_model += 1
        changed += 1
        if args.dry_run:
            print(f"  {verdict.importance:.2f} [{verdict.area}] {article['title'][:52]}")
            print(f"        {verdict.why}")
        else:
            article["relevance_score"] = round(verdict.score, 3)
            article["tags"] = verdict.tags
            article["area"] = verdict.area
            # 0.0 is a verdict; None would mean "ask again next time".
            article["importance"] = round(verdict.importance, 3) if verdict.importance is not None else 0.0
            article["why"] = verdict.why

    print(f"\nre-judged by model: {by_model}/{len(targets)}")
    print(f"rows that would change: {changed}" if args.dry_run else f"rows changed: {changed}")

    if args.dry_run or not changed:
        return

    payload["count"] = len(articles)
    payload["sources"] = sorted({a["source"] for a in articles})
    with open(DATA_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
