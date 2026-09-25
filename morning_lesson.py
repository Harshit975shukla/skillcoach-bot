"""Weekdays 09:00 Asia/Kolkata: full lesson and animated Ken Burns media.

The original 25-second zoom, fade and caption implementation lives in
skillcoach.media; static media remains an optional preference/failure fallback.
"""

from skillcoach.cli import legacy_schedule

if __name__ == "__main__":
    raise SystemExit(legacy_schedule("lesson"))
