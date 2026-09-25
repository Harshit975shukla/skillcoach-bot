"""Opt-in local polling; shares services and never schedules duplicate lessons."""

from skillcoach.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["poll"]))
