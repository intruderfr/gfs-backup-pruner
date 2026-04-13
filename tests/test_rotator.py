"""Tests for gfs_backup_pruner.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gfs_backup_pruner import (  # noqa: E402
    Backup,
    RetentionPolicy,
    classify_gfs,
    discover_backups,
    plan_prune,
)


def make_backup(date_str: str) -> Backup:
    ts = dt.datetime.strptime(date_str, "%Y-%m-%d")
    return Backup(path=Path(f"/tmp/backup-{date_str}.tar.gz"), timestamp=ts)


class GFSClassificationTests(unittest.TestCase):
    def test_recent_daily_backups_are_all_kept(self) -> None:
        backups = [make_backup(f"2026-04-{d:02d}") for d in range(1, 11)]
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        policy = RetentionPolicy(daily=7, weekly=0, monthly=0, yearly=0)
        kept, buckets = classify_gfs(backups, policy)
        self.assertEqual(len(kept), 7)
        self.assertEqual(len(buckets["daily"]), 7)
        # The 7 most-recent backups should have been kept.
        expected = {b.path for b in backups[:7]}
        self.assertEqual(kept, expected)

    def test_weekly_bucket_picks_one_per_iso_week(self) -> None:
        # Five full weeks of daily backups, week keep=3 only.
        start = dt.date(2026, 1, 5)  # Monday, ISO week 2
        backups = []
        for w in range(5):
            for d in range(7):
                backups.append(make_backup((start + dt.timedelta(weeks=w, days=d)).isoformat()))
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        policy = RetentionPolicy(daily=0, weekly=3, monthly=0, yearly=0)
        _, buckets = classify_gfs(backups, policy)
        self.assertEqual(len(buckets["weekly"]), 3)
        weeks_kept = {b.timestamp.date().isocalendar()[:2] for b in buckets["weekly"]}
        self.assertEqual(len(weeks_kept), 3)

    def test_monthly_and_yearly_do_not_double_count(self) -> None:
        # One backup per month over three years.
        backups = []
        for year in range(2023, 2026):
            for month in range(1, 13):
                backups.append(make_backup(f"{year}-{month:02d}-15"))
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        policy = RetentionPolicy(daily=0, weekly=0, monthly=6, yearly=2)
        kept, buckets = classify_gfs(backups, policy)
        self.assertEqual(len(buckets["monthly"]), 6)
        self.assertEqual(len(buckets["yearly"]), 2)
        # The most recent backup satisfies both the monthly and yearly bucket
        # for its year; it should still only appear once in the kept set.
        self.assertLessEqual(len(kept), 6 + 2)

    def test_plan_prune_splits_kept_and_deleted(self) -> None:
        backups = [make_backup(f"2026-03-{d:02d}") for d in range(1, 16)]
        backups.sort(key=lambda b: b.timestamp, reverse=True)
        policy = RetentionPolicy(daily=5, weekly=0, monthly=0, yearly=0)
        kept, to_delete, _ = plan_prune(backups, policy)
        self.assertEqual(len(kept), 5)
        self.assertEqual(len(to_delete), 10)
        # No overlap between kept and deleted.
        self.assertTrue({b.path for b in kept}.isdisjoint({b.path for b in to_delete}))


class DiscoveryTests(unittest.TestCase):
    def test_discover_skips_files_without_date_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            good = tmp_path / "db-2026-03-12.sql.gz"
            bad = tmp_path / "README.md"
            good.write_text("ok")
            bad.write_text("ok")

            pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
            results = discover_backups(tmp_path, pattern, "%Y-%m-%d")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path.name, "db-2026-03-12.sql.gz")

    def test_discover_parses_custom_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "dump_20260101.tar").write_text("")
            (tmp_path / "dump_20260215.tar").write_text("")
            pattern = re.compile(r"(\d{8})")
            results = discover_backups(tmp_path, pattern, "%Y%m%d")
            self.assertEqual(len(results), 2)
            dates = sorted(b.timestamp.date().isoformat() for b in results)
            self.assertEqual(dates, ["2026-01-01", "2026-02-15"])

    def test_discover_recursive_walks_subdirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sub = tmp_path / "nested" / "daily"
            sub.mkdir(parents=True)
            (sub / "snap-2025-12-30.tar").write_text("")
            (tmp_path / "snap-2026-01-01.tar").write_text("")
            pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
            flat = discover_backups(tmp_path, pattern, "%Y-%m-%d", recursive=False)
            recursive = discover_backups(tmp_path, pattern, "%Y-%m-%d", recursive=True)
            self.assertEqual(len(flat), 1)
            self.assertEqual(len(recursive), 2)

    def test_discover_raises_for_missing_directory(self) -> None:
        with self.assertRaises(FileNotFoundError):
            discover_backups(
                Path("/tmp/this-dir-should-not-exist-xyz"),
                re.compile(r"(\d{4}-\d{2}-\d{2})"),
                "%Y-%m-%d",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
