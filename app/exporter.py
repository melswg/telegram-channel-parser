"""Export comments + transcripts to JSONL and CSV."""

import csv
import json
import logging
from pathlib import Path
from typing import Optional

from .db import Database

log = logging.getLogger(__name__)


def export_jsonl(db: Database, output_path: str,
                 channel: Optional[str] = None,
                 since: Optional[str] = None,
                 until: Optional[str] = None) -> int:
    """Export comments with transcripts as JSONL (one JSON object per line)."""
    rows = db.get_comments_for_export(
        channel_username=channel,
        since=since,
        until=until,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(output, "w", encoding="utf-8") as f:
        for row in rows:
            # Remove DB-internal fields if present
            row.pop("comment_id", None)
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1

    log.info("Exported %d records to JSONL: %s", count, output)
    return count


def export_csv(db: Database, output_path: str,
               channel: Optional[str] = None,
               since: Optional[str] = None,
               until: Optional[str] = None) -> int:
    """Export comments with transcripts as CSV."""
    rows = db.get_comments_for_export(
        channel_username=channel,
        since=since,
        until=until,
    )

    if not rows:
        log.info("No data to export")
        return 0

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys())

    count = 0
    with open(output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1

    log.info("Exported %d records to CSV: %s", count, output)
    return count


def run_export(db_path: str, fmt: str, output: str,
               channel: Optional[str] = None,
               since: Optional[str] = None,
               until: Optional[str] = None) -> int:
    """Run export in given format.

    Returns number of rows exported.
    """
    db = Database(db_path)
    db.open()

    try:
        if fmt == "jsonl":
            return export_jsonl(db, output, channel=channel, since=since, until=until)
        elif fmt == "csv":
            return export_csv(db, output, channel=channel, since=since, until=until)
        else:
            raise ValueError(f"Unsupported format: {fmt}. Use 'jsonl' or 'csv'.")
    finally:
        db.close()
