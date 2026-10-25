"""Seed the database.

    python -m scripts.seed            # roles, permissions, settings (safe everywhere)
    python -m scripts.seed --demo     # + fictional demo hospitals, users and records (dev only)
"""
from __future__ import annotations

import argparse
import sys

from app.config import settings
from app.database import SessionLocal
from app.services.common.seed import DEMO_PASSWORD, seed_demo, seed_rbac, seed_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="also create demo data")
    args = parser.parse_args()

    if args.demo and settings.is_production:
        print("Refusing to create demo accounts with APP_ENV=production.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        seed_rbac(db)
        seed_settings(db)
        print("RBAC roles/permissions and system settings: OK")
        if args.demo:
            summary = seed_demo(db)
            print(f"Demo users created: {', '.join(summary.created) or 'none (already present)'}")
            print(f"Demo password for every demo account: {DEMO_PASSWORD}")
            for user, upi in summary.upis.items():
                print(f"  {user:<10} UPI {upi}")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
