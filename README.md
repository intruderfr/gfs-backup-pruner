# gfs-backup-pruner

A small, dependency-free Python CLI that prunes backup files using a
**Grandfather-Father-Son (GFS)** retention policy.

If you dump databases, rsync snapshots, or tarballs into a directory
with a date in the filename (`db-2026-04-13.sql.gz`, `snap_20260413.tar`,
…) this tool will tell you which ones to keep and which ones to delete.

Dry-run is the default. Nothing is deleted unless you pass `--apply`.

## What is Grandfather-Father-Son?

GFS is a classic backup retention scheme:

| Bucket   | Kept by default | Meaning                          |
|----------|-----------------|----------------------------------|
| daily    | 7               | one per calendar day             |
| weekly   | 4               | one per ISO week                 |
| monthly  | 12              | one per calendar month           |
| yearly   | 3               | one per calendar year            |

A single backup can satisfy several buckets at once (the newest daily
is usually also the newest weekly, monthly and yearly), so the total
number of files retained is at most the sum of the caps but often fewer.

## Install

Clone and run. No third-party dependencies — requires only Python 3.9+.

```bash
git clone https://github.com/intruderfr/gfs-backup-pruner.git
cd gfs-backup-pruner
python3 gfs_backup_pruner.py --help
```

Or drop `gfs_backup_pruner.py` anywhere in your `$PATH`:

```bash
chmod +x gfs_backup_pruner.py
sudo cp gfs_backup_pruner.py /usr/local/bin/gfs-backup-pruner
```

## Usage

### Dry-run (default)

```bash
python3 gfs_backup_pruner.py /var/backups/postgres
```

Example output:

```
GFS Backup Pruner - Plan
========================================
Keeping: 18 backups
  yearly  : 2
  monthly : 6
  weekly  : 4
  daily   : 7
Delete : 82 backups (14.3 GB)

(dry-run: no files were deleted. Re-run with --apply to delete.)
```

### Customize retention

```bash
python3 gfs_backup_pruner.py /var/backups/postgres \
  --daily 14 --weekly 8 --monthly 24 --yearly 5 \
  --verbose
```

### Custom filename pattern

By default the tool matches `YYYY-MM-DD` anywhere in the filename.
Use `--pattern` and `--date-format` to support other schemes:

```bash
# dump_20260413.tar
python3 gfs_backup_pruner.py /backups \
  --pattern '(\d{8})' --date-format '%Y%m%d'

# backup.2026-04-13T02-00.tar.gz
python3 gfs_backup_pruner.py /backups \
  --pattern '(\d{4}-\d{2}-\d{2}T\d{2}-\d{2})' \
  --date-format '%Y-%m-%dT%H-%M'
```

### Actually delete files

Review the dry-run first, then re-run with `--apply`:

```bash
python3 gfs_backup_pruner.py /var/backups/postgres --apply
```

### Recursive scan

```bash
python3 gfs_backup_pruner.py /var/backups --recursive
```

## Typical cron schedule

```cron
# Prune Postgres dumps every day at 03:30
30 3 * * *  /usr/local/bin/gfs-backup-pruner /var/backups/postgres --apply >> /var/log/gfs-prune.log 2>&1
```

## How classification works

The tool sorts backups newest-first and walks the list once, filling
four buckets (yearly, monthly, weekly, daily). Each bucket keeps one
backup per time-period (year / calendar month / ISO week / calendar
day) until its cap is reached. Anything that didn't get claimed by at
least one bucket is deleted.

ISO weeks mean the "weekly" bucket naturally matches how most backup
schedules talk about weeks (Monday-start, cross-year safe).

## Development

```bash
python3 -m unittest discover -s tests -v
```

The test suite covers bucket classification, the plan/prune split,
filename discovery, custom date formats and recursive directory walks.

## License

MIT. See [LICENSE](LICENSE).

## Author

**Aslam Ahamed** — Head of IT @ Prestige One Developments, Dubai
[linkedin.com/in/aslam-ahamed](https://www.linkedin.com/in/aslam-ahamed/)
