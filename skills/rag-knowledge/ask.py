"""
Manual CLI for exercising rag-knowledge without wrestling with shell quoting
in a `python -c` one-liner -- same purpose as property-search/chat.py.

Usage:
    python skills/rag-knowledge/ask.py --build [city ...]
    python skills/rag-knowledge/ask.py --retrieve <question>
    python skills/rag-knowledge/ask.py <question>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from rag import build_index, retrieve, rag_answer, format_rag_answer


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    if args[0] == "--build":
        cities = args[1:] or None
        n = build_index(market_cities=cities)
        extra = f" (incl. live reports for {', '.join(cities)})" if cities else ""
        print(f"Indexed {n} chunks{extra}")
        return

    if args[0] == "--retrieve":
        query = " ".join(args[1:])
        for hit in retrieve(query, top_k=5):
            print(f"{hit['score']:.3f}  [{hit['source']}]  {hit['chunk'][:80]!r}")
        return

    query = " ".join(args)
    result = rag_answer(query)
    print(format_rag_answer(result))
    print(f"[backend: {result['backend']}]")


if __name__ == "__main__":
    main()
