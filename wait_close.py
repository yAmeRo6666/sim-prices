"""Gate for the prices workflow: fetch now, wait for today's close, or skip (added 2026-11-03).

GitHub starts scheduled runs late (4-7 hours in Oct-Nov 2026), so the daily close was often published only in the
evening and the 14:40 PT paper-portfolio report found yesterday's data. The workflow therefore also has EARLY
schedules: an early run that starts on a trading day before 16:25 New York time sleeps until then (at most
MAX_WAIT, under the 6-hour job limit) and then fetches, so the day's final data is out by about 16:30 ET whatever
the delay. An early run that would have to wait longer than MAX_WAIT skips (a later early schedule takes over),
and one that starts after today's final data is already published skips too. Every other event (the post-close
schedules, workflow_dispatch, push) fetches immediately, exactly as before.

Prints "run" or "skip: <reason>" and writes action=run|skip to $GITHUB_OUTPUT when it is set.
Env: EVENT = github.event_name, SCHEDULE = github.event.schedule (the cron string of a scheduled run).
"""
import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo

import fetch_prices as fp

NY = ZoneInfo("America/New_York")
TARGET = dt.time(16, 25)          # fetch_prices treats a day as final from 16:20 ET
MAX_WAIT = 320 * 60               # seconds; job timeout is 350 minutes
EARLY = {"7 11 * * 1-5", "7 13 * * 1-5", "7 15 * * 1-5", "7 17 * * 1-5", "7 19 * * 1-5"}


def decide(now_utc, event, schedule, published_final):
    """("run", 0) | ("wait", seconds) | ("skip", reason) for a run starting at now_utc (aware datetime)."""
    if event != "schedule" or (schedule or "").strip() not in EARLY:
        return ("run", 0)
    now = now_utc.astimezone(NY)
    d = now.date()
    if not fp.is_trading(d):
        return ("skip", f"{d} is not a trading day")
    if published_final == d.isoformat():
        return ("skip", f"final data for {d} is already published")
    wait = (dt.datetime.combine(d, TARGET, tzinfo=NY) - now).total_seconds()
    if wait <= 0:
        return ("run", 0)
    if wait > MAX_WAIT:
        return ("skip", f"too early ({wait / 3600:.1f} h before 16:25 ET); a later early schedule will fetch")
    return ("wait", int(wait) + 1)


def main():
    try:
        with open("latest.json", encoding="utf-8") as f:
            published = json.load(f).get("final_through")
    except (OSError, ValueError):
        published = None
    action, arg = decide(dt.datetime.now(dt.timezone.utc), os.environ.get("EVENT", ""), os.environ.get("SCHEDULE", ""), published)
    if action == "wait":
        print(f"waiting {arg} s until 16:25 New York time", flush=True)
        time.sleep(arg)
        action = "run"
    print("run" if action == "run" else f"skip: {arg}", flush=True)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"action={action}\n")


if __name__ == "__main__":
    main()
