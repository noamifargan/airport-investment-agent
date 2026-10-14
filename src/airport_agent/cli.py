"""Command-line entry point: `uv run airport-agent <command>`."""

from __future__ import annotations

import argparse
import sys
import time

from airport_agent.config import settings


def _print_events(question: str, session) -> None:
    from airport_agent.agent.agent import ask

    start = time.time()
    for ev in ask(question, session):
        if ev["type"] in ("status", "tool"):
            print(f"  · {ev['text']}", file=sys.stderr)
        elif ev["type"] == "token":
            print(ev["text"], end="", flush=True)
        elif ev["type"] == "footer":
            print(ev["text"])
    print(f"\n  ({time.time() - start:.0f}s, model {settings.ollama_model})", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(prog="airport-agent", description="Airport Investment Intelligence Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="Show active settings")
    sub.add_parser("refresh", help="Pull every public data source now (first run takes several minutes)")
    ask_p = sub.add_parser("ask", help="Ask one question")
    ask_p.add_argument("question", nargs="+")
    sub.add_parser("chat", help="Interactive chat in the terminal")
    serve_p = sub.add_parser("serve", help="Start the web chat UI")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.command == "info":
        for key, value in vars(settings).items():
            print(f"{key:15} {value}")
    elif args.command == "refresh":
        from airport_agent.analytics.features import features
        from airport_agent.data.sources import nas_status

        df, provs = features()
        for p in (*provs, nas_status.current_events()[2]):
            print(" ", p.short())
        print(f"KPI table ready: {len(df)} commercial airports")
    elif args.command == "ask":
        from airport_agent.agent.agent import Session

        _print_events(" ".join(args.question), Session())
    elif args.command == "chat":
        from airport_agent.agent.agent import Session

        session = Session()
        print("Airport Investment Intelligence Agent — ask about US airports (Ctrl-D to quit).")
        while True:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question:
                _print_events(question, session)
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("airport_agent.web.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
