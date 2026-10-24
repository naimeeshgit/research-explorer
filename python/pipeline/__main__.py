"""CLI: python -m pipeline <step>"""
import argparse
import sys

from pipeline import db

STEPS = ["faculty", "works", "fulltext", "cards", "profiles", "index", "refresh", "costs", "institutions"]
NOT_BUILT = {"profiles": 5, "index": 6, "refresh": 9}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    parser.add_argument("step", choices=STEPS)
    parser.add_argument("--no-cache", action="store_true", help="bypass the OpenAlex response cache")
    parser.add_argument("--query", default="Indian School of Business", help="institutions: search text")
    parser.add_argument("--report-only", action="store_true", help="works/fulltext: print the report without fetching")
    parser.add_argument("--spot-check", nargs="+", metavar="NAME",
                        help="works --report-only: professor names to spot-check (default: 3 at random)")
    parser.add_argument("--use-openalex-content", action="store_true",
                        help="fulltext: also use OpenAlex's paid PDF endpoint ($0.01/PDF) for papers still missing text")
    parser.add_argument("--retry-failed", action="store_true",
                        help="fulltext: retry recent download failures instead of waiting FULLTEXT_RETRY_DAYS")
    parser.add_argument("--limit", type=int, help="fulltext/cards: process at most N papers this run")
    parser.add_argument("--show", metavar="ID", help="fulltext: print one paper's text (paper id, W id, or 'random')")
    parser.add_argument("--yes", action="store_true", help="confirm a paid action")
    parser.add_argument("--sample", type=int, default=5, help="cards --compare: number of papers")
    parser.add_argument("--compare", action="store_true", help="cards: compare CARD_MODEL_CANDIDATES on --sample papers, nothing saved")
    parser.add_argument("--review", type=int, metavar="N", help="cards: print N random cards next to their sources")
    parser.add_argument("--seed", type=int, help="random seed for --compare / --review")
    args = parser.parse_args(argv)
    use_cache = not args.no_cache

    if args.step == "institutions":
        from pipeline import faculty
        faculty.list_institutions(args.query)
    elif args.step == "faculty":
        from pipeline import faculty
        faculty.run(use_cache=use_cache)
    elif args.step == "works":
        from pipeline import works
        if args.report_only:
            works.report(db.connect(), spot_check=args.spot_check)
        else:
            works.run(use_cache=use_cache)
    elif args.step == "fulltext":
        from pipeline import fulltext
        if args.show:
            fulltext.show(db.connect(), args.show)
        elif args.report_only:
            fulltext.report(db.connect())
        else:
            fulltext.run(use_openalex_content=args.use_openalex_content, retry_failed=args.retry_failed,
                         yes=args.yes, limit=args.limit)
    elif args.step == "cards":
        from pipeline import cards
        if args.compare:
            cards.compare(n=args.sample, seed=args.seed)
        elif args.review:
            cards.review(n=args.review, seed=args.seed)
        elif args.report_only:
            cards.report(db.connect())
        else:
            cards.run(yes=args.yes, limit=args.limit)
    elif args.step == "costs":
        from pipeline import costs
        costs.run()
    else:
        print(f"'{args.step}' is not built yet (Part {NOT_BUILT[args.step]}).")
        sys.exit(2)


if __name__ == "__main__":
    main()
