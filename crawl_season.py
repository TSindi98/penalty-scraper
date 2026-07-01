"""Crawlt alle Match Reports der Saison, rate-limited. Idempotent: gecachte Spiele werden geskippt."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from scrape_match import parse_match, extract_match_id, DATA_DIR
from fbref_client import get, CloudflareBlocked

SCHEDULE_FILE = Path(__file__).parent / "data" / "raw" / "schedule.json"
SLEEP_BETWEEN = 4.0  # ~4s zwischen Requests → 380 Spiele in ~25 Min


def main() -> int:
    schedule = json.loads(SCHEDULE_FILE.read_text())
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    total = len(schedule)
    done = 0
    cached = 0
    errors = 0

    for i, match in enumerate(schedule, 1):
        match_id = extract_match_id(match["match_report_url"])
        out_file = DATA_DIR / f"{match_id}.json"
        if out_file.exists():
            cached += 1
            done += 1
            continue

        try:
            html = get(match["match_report_url"])
        except CloudflareBlocked as e:
            print(
                f"\n[{i}/{total}] CLOUDFLARE BLOCK — Cookies neu holen und "
                f"Skript nochmal starten. Bereits {cached} Spiele gecacht.",
                flush=True,
            )
            return 2
        except Exception as e:
            errors += 1
            print(f"[{i}/{total}] ERROR {match['match_report_url']}: {e}", flush=True)
            time.sleep(SLEEP_BETWEEN)
            continue

        try:
            data = parse_match(html)
            data["match_id"] = match_id
            data["url"] = match["match_report_url"]
            data["schedule_meta"] = match
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            done += 1
            pen_count = sum(1 for e in data["events"] if e["is_penalty"])
            print(
                f"[{i}/{total}] {match['date']} {match['home_team']} vs "
                f"{match['away_team']}: {len(data['events'])} events, "
                f"{pen_count} penalties",
                flush=True,
            )
        except Exception as e:
            errors += 1
            print(f"[{i}/{total}] PARSE ERROR {match_id}: {e}", flush=True)

        time.sleep(SLEEP_BETWEEN)

    print(f"\nDone. {done}/{total} matches processed ({cached} cached, {errors} errors)")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
