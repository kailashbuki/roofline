"""Union two generated data files into one.

A run rewrites data/articles.json wholesale, so git can never rebase it — every
concurrent push produces a conflict on the entire file. Instead of rebasing, the
workflow unions its freshly generated data with whatever is already on the remote
tip. Nothing collected by either side is lost.

    python merge_data.py ours.json theirs.json out.json
    python merge_data.py --rejected ours.json theirs.json out.json
"""
import argparse
import json
import os
import sys


def load(path, key):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"merge_data: ignoring {path} ({exc})", file=sys.stderr)
        return None
    return payload if isinstance(payload.get(key), list) else None


def merge_articles(ours, theirs):
    merged = {}
    # Iterate theirs first so ours wins on identical urls (it is the fresher run).
    for payload in (theirs, ours):
        if not payload:
            continue
        for article in payload["articles"]:
            url = article.get("url")
            if not url:
                continue
            prior = merged.get(url)
            if prior is None:
                merged[url] = article
                continue
            # Keep the richer record; never drop tags that one side has.
            best = article if len(article.get("summary") or "") >= len(prior.get("summary") or "") else prior
            best["tags"] = best.get("tags") or prior.get("tags") or article.get("tags") or ""
            merged[url] = best

    articles = sorted(merged.values(),
                      key=lambda a: (a.get("published_date") or "", a["url"]), reverse=True)
    stamps = [p["generated_at"] for p in (ours, theirs) if p and p.get("generated_at")]
    return {
        "generated_at": max(stamps) if stamps else "",
        "count": len(articles),
        "sources": sorted({a["source"] for a in articles if a.get("source")}),
        "articles": articles,
    }


def merge_rejected(ours, theirs):
    urls = []
    for payload in (theirs, ours):
        if payload:
            urls.extend(payload["urls"])
    # dict.fromkeys preserves first-seen order, which keeps the prune-oldest-first
    # behaviour in collectors/pipeline.py meaningful.
    deduped = list(dict.fromkeys(urls))
    return {"count": len(deduped), "urls": deduped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rejected", action="store_true", help="merge a rejection ledger")
    parser.add_argument("ours")
    parser.add_argument("theirs")
    parser.add_argument("out")
    args = parser.parse_args()

    key = "urls" if args.rejected else "articles"
    ours = load(args.ours, key)
    theirs = load(args.theirs, key)

    if not ours and not theirs:
        print("merge_data: nothing to merge", file=sys.stderr)
        return

    result = merge_rejected(ours, theirs) if args.rejected else merge_articles(ours, theirs)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    print(f"merge_data: {args.out} now has {result['count']} "
          f"{'urls' if args.rejected else 'articles'}")


if __name__ == "__main__":
    main()
