"""
gfs-backup-pruner
=================

Prune backup files using a Grandfather-Father-Son (GFS) retention policy.

The tool scans a directory for backup files whose names contain a date
(extracted via a configurable regex + strptime pattern), classifies each
backup as daily / weekly / monthly / yearly, and keeps the most recent
N of each bucket. Everything else is eligible for pruning.

By default the tool runs in dry-run mode and only reports what *would*
happen; pass --apply to actually delete files.

Author: Aslam Ahamed <aslamahamed47@gmail.com>
License: MIT
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Backup:
    """A single backup file plus the date parsed from its name."""

    path: Path
    timestamp: dt.datetime

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


@dataclasses.dataclass
class RetentionPolicy:
    """Grandfather-Father-Son retention counts."""

    daily: int = 7
    weekly: int = 4
    monthly: int = 12
    yearly: int = 3

    def total_capacity(self) -> int:
        return self.daily + self.weekly + self.monthly + self.yearly


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_backups(
    directory: Path,
    name_pattern: re.Pattern[str],
    date_format: str,
    recursive: bool = False,
) -> list[Backup]:
    """Find backup files in *directory* whose names match *name_pattern*.

    The first regex capture group must contain the date string that can
    be parsed by ``datetime.strptime(s, date_format)``.
    """
    if not directory.exists():
        raise FileNotFoundError(directory)
    if not directory.is_dir():
        raise NotADirectoryError(directory)

    iterator: Iterable[Path]
    if recursive:
        iterator = (p for p in directory.rglob("*") if p.is_file())
    else:
        iterator = (p for p in directory.iterdir() if p.is_file())

    backups: list[Backup] = []
    for path in iterator:
        match = name_pattern.search(path.name)
        if not match or not match.groups():
            continue
        try:
            ts = dt.datetime.strptime(match.group(1), date_format)
        except ValueError:
            continue
        backups.append(Backup(path=path, timestamp=ts))

    backups.sort(key=lambda b: b.timestamp, reverse=True)
    return backups


# ---------------------------------------------------------------------------
# GFS classification
# ---------------------------------------------------------------------------


def _iso_week_key(d: dt.date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def classify_gfs(
    backups: list[Backup],
    policy: RetentionPolicy,
    today: dt.date | None = None,
) -> tuple[set[Path], dict[str, list[Backup]]]:
    """Return (keep_set, bucket_map) for a list of backups.

    The algorithm walks backups newest-first and fills yearly/monthly/
    weekly/daily buckets. Each bucket keeps one backup per time-period
    (year, month, ISO week, day) and only until the policy cap is hit.
    A single backup can satisfy several buckets but is counted once.
    """
    keep: set[Path] = set()
    buckets: dict[str, list[Backup]] = {
        "daily": [],
        "weekly": [],
        "monthly": [],
        "yearly": [],
    }
    seen_day: set[dt.date] = set()
    seen_week: set[tuple[int, int]] = set()
    seen_month: set[tuple[int, int]] = set()
    seen_year: set[int] = set()

    for backup in backups:  # already newest-first
        d = backup.timestamp.date()
        claimed = False

        if (
            len(buckets["daily"]) < policy.daily
            and d not in seen_day
        ):
            buckets["daily"].append(backup)
            seen_day.add(d)
            claimed = True

        wk = _iso_week_key(d)
        if (
            len(buckets["weekly"]) < policy.weekly
            and wk not in seen_week
        ):
            buckets["weekly"].append(backup)
            seen_week.add(wk)
            claimed = True

        mk = (d.year, d.month)
        if (
            len(buckets["monthly"]) < policy.monthly
            and mk not in seen_month
        ):
            buckets["monthly"].append(backup)
            seen_month.add(mk)
            claimed = True

        if (
            len(buckets["yearly"]) < policy.yearly
            and d.year not in seen_year
        ):
            buckets["yearly"].append(backup)
            seen_year.add(d.year)
            claimed = True

        if claimed:
            keep.add(backup.path)

    return keep, buckets


def plan_prune(
    backups: list[Backup], policy: RetentionPolicy
) -> tuple[list[Backup], list[Backup], dict[str, list[Backup]]]:
    """Return (kept, to_delete, buckets)."""
    keep_set, buckets = classify_gfs(backups, policy)
    kept = [b for b in backups if b.path in keep_set]
    to_delete = [b for b in backups if b.path not in keep_set]
    return kept, to_delete, buckets


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def delete_backups(backups: list[Backup]) -> tuple[int, list[tuple[Path, str]]]:
    """Delete the given backups. Returns (deleted_count, errors)."""
    deleted = 0
    errors: list[tuple[Path, str]] = []
    for b in backups:
        try:
            os.remove(b.path)
            deleted += 1
        except OSError as e:
            errors.append((b.path, str(e)))
    return deleted, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


DEFAULT_PATTERN = r"(\d{4}-\d{2}-\d{2})"
DEFAULT_FORMAT = "%Y-%m-%d"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gfs-backup-pruner",
        description=(
            "Prune backup files using Grandfather-Father-Son retention. "
            "Dry-run by default; pass --apply to delete."
        ),
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing backup files to scan.",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=(
            "Regex with one capture group that extracts the date string "
            f"from each filename (default: {DEFAULT_PATTERN!r})."
        ),
    )
    parser.add_argument(
        "--date-format",
        default=DEFAULT_FORMAT,
        help=(
            "strptime format for the captured date string "
            f"(default: {DEFAULT_FORMAT!r})."
        ),
    )
    parser.add_argument("--daily", type=int, default=7, help="Daily backups to keep (default 7).")
    parser.add_argument("--weekly", type=int, default=4, help="Weekly backups to keep (default 4).")
    parser.add_argument("--monthly", type=int, default=12, help="Monthly backups to keep (default 12).")
    parser.add_argument("--yearly", type=int, default=3, help="Yearly backups to keep (default 3).")
    parser.add_argument("--recursive", action="store_true", help="Scan the directory recursively.")
    parser.add_argument("--apply", action="store_true", help="Actually delete files. Without this, dry-run only.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print every backup with its classification.")
    return parser


def format_report(
    kept: list[Backup],
    to_delete: list[Backup],
    buckets: dict[str, list[Backup]],
    verbose: bool,
) -> str:
    lines = []
    lines.append("GFS Backup Pruner - Plan")
    lines.append("=" * 40)
    lines.append(f"Keeping: {len(kept)} backups")
    for bucket_name in ["yearly", "monthly", "weekly", "daily"]:
        lines.append(f"  {bucket_name:<8}: {len(buckets[bucket_name])}")
    total_delete_size = sum(b.size_bytes for b in to_delete)
    lines.append(
        f"Delete : {len(to_delete)} backups ({human_size(total_delete_size)})"
    )
    lines.append("")
    if verbose:
        lines.append("Kept files:")
        for b in kept:
            lines.append(f"  KEEP    {b.timestamp.date()}  {b.path.name}")
        lines.append("")
        lines.append("Files to prune:")
        for b in to_delete:
            lines.append(f"  DELETE  {b.timestamp.date()}  {b.path.name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        compiled = re.compile(args.pattern)
    except re.error as e:
        print(f"error: invalid --pattern regex: {e}", file=sys.stderr)
        return 2

    if compiled.groups < 1:
        print(
            "error: --pattern must contain at least one capture group for the date",
            file=sys.stderr,
        )
        return 2

    policy = RetentionPolicy(
        daily=args.daily,
        weekly=args.weekly,
        monthly=args.monthly,
        yearly=args.yearly,
    )

    try:
        backups = discover_backups(
            directory=args.directory,
            name_pattern=compiled,
            date_format=args.date_format,
            recursive=args.recursive,
        )
    except FileNotFoundError:
        print(f"error: directory not found: {args.directory}", file=sys.stderr)
        return 2
    except NotADirectoryError:
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 2

    if not backups:
        print(
            f"No backup files matched pattern {args.pattern!r} in {args.directory}",
            file=sys.stderr,
        )
        return 1

    kept, to_delete, buckets = plan_prune(backups, policy)
    print(format_report(kept, to_delete, buckets, verbose=args.verbose))

    if not args.apply:
        print("\n(dry-run: no files were deleted. Re-run with --apply to delete.)")
        return 0

    if not to_delete:
        print("\nNothing to delete.")
        return 0

    deleted, errors = delete_backups(to_delete)
    print(f"\nDeleted {deleted} file(s).")
    if errors:
        print(f"Failed to delete {len(errors)} file(s):", file=sys.stderr)
        for path, reason in errors:
            print(f"  {path}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
