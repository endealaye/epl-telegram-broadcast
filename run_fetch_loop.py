#!/usr/bin/env python3
"""
Run fetch agents (news, fixtures, scores) in a continuous loop.

Usage:
    python run_fetch_loop.py [--iterations N | --forever] [--sleep SECONDS]

Defaults:
    - iterations: 3
    - sleep between cycles: 300 seconds (5 minutes)
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from service_models import ServiceResult
from worker_services import (
    fetch_news_service,
    process_live_window_service,
    sync_fixtures_service,
)


def run_news():
    try:
        result = fetch_news_service()
        return result.to_dict() if hasattr(result, "to_dict") else result.__dict__
    except Exception as exc:
        return {"action": "news_fetch", "success": False, "message": str(exc)}


def run_fixtures():
    try:
        result = sync_fixtures_service()
        return result.to_dict() if hasattr(result, "to_dict") else result.__dict__
    except Exception as exc:
        return {"action": "refresh", "success": False, "message": str(exc)}


def run_scores():
    try:
        result = process_live_window_service()
        return result.to_dict() if hasattr(result, "to_dict") else result.__dict__
    except Exception as exc:
        return {"action": "live", "success": False, "message": str(exc)}


def run_cycle():
    print(f"[cycle] Starting cycle at {datetime.now(timezone.utc).isoformat()}")
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_news): "news",
            executor.submit(run_fixtures): "fixtures",
            executor.submit(run_scores): "scores",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                results[key] = {"success": False, "message": str(exc)}

    for key, data in results.items():
        success = data.get("success")
        message = data.get("message", "")
        skipped = data.get("skipped", False)
        status = "skipped" if skipped else "ok" if success else "failed"
        print(f"[{key}] {status}: {message}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run fetch agents in a loop.")
    parser.add_argument("--iterations", type=int, default=3, help="Number of loop iterations (default: 3)")
    parser.add_argument("--forever", action="store_true", help="Run indefinitely")
    parser.add_argument("--sleep", type=int, default=300, help="Sleep seconds between cycles (default: 300)")
    return parser.parse_args()


def main():
    args = parse_args()
    iterations = args.iterations if not args.forever else float("inf")
    count = 0
    while count < iterations:
        run_cycle()
        count += 1
        if count < iterations:
            print(f"[cycle] Sleeping {args.sleep}s before next cycle...")
            time.sleep(args.sleep)
    print(f"[cycle] Completed after {count} cycle(s).")


if __name__ == "__main__":
    main()
