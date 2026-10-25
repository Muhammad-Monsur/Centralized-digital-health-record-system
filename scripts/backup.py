"""Backup CLI (for cron / Task Scheduler).

    python -m scripts.backup create [--label nightly]
    python -m scripts.backup list
    python -m scripts.backup restore cdhrs-backup-20261021-120000.tar.gz --yes
"""
from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.services import backup


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--label", default="cli")
    sub.add_parser("list")
    r = sub.add_parser("restore")
    r.add_argument("name")
    r.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    args = ap.parse_args()

    with SessionLocal() as db:
        if args.cmd == "create":
            info = backup.create_backup(db, None, "cli", label=args.label)
            print(f"Created {info.name}: {info.rows} rows, {info.files} files, {info.size / 1024:.1f} KB")
        elif args.cmd == "list":
            for b in backup.list_backups():
                print(f"{b.name:<55} {b.created_at[:19]}  rows={b.rows:<7} files={b.files:<5} {b.size / 1024:.1f} KB")
        else:
            if not args.yes and input(f"Restore {args.name}? Current data will be replaced. Type RESTORE: ").strip() != "RESTORE":
                print("Cancelled.")
                return 1
            try:
                res = backup.restore_backup(db, args.name, None, "cli")
            except backup.BackupError as e:
                print(f"Error: {e.message}", file=sys.stderr)
                return 2
            print(f"Restored {res['rows']} rows and {res['files']} files. Safety backup: {res['safety_backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
