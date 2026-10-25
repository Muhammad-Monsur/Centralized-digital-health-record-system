"""Backup and recovery.

A backup is one ``.tar.gz`` file in BACKUP_DIR containing:
  manifest.json   - created_at, alembic revision, per-table row counts, SHA-256 of data.json
  data.json       - every table's rows (JSON, in foreign-key dependency order)
  uploads/...     - the stored medical documents

Why a logical (JSON) backup instead of only ``mysqldump``: it works on any OS with no
MySQL client tools installed, can be verified (checksum + schema revision) before
restoring, and restores uploaded files together with the rows that reference them.
For large production databases also schedule ``mysqldump --single-transaction`` (see README).

Backups contain health data: they are written 0600, never served over HTTP, and
should be stored encrypted off-site.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Table, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine
from app.services.common import cache
from app.services.common.audit import audit
from app.services.common.kvstore import kv
from app.services.common.security import utcnow

FORMAT_VERSION = 1
_NAME_RE = re.compile(r"^cdhrs-backup-\d{8}-\d{6}(\d{3})?(-[a-z0-9-]{1,30})?\.tar\.gz$")
_UPLOAD_RE = re.compile(r"^uploads/[0-9a-f]{32}\.(pdf|png|jpg|jpeg|webp)$")
SKIP_TABLES: set[str] = set()  # every table is backed up


class BackupError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class BackupInfo:
    name: str
    size: int
    created_at: str
    revision: str
    rows: int
    files: int
    label: str


def _json_default(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()
    raise TypeError(f"Unserialisable {type(v)}")


def _tables() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]


def _revision(conn) -> str:
    return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar() or "")


def create_backup(db: Session, user_id: int | None, ip: str | None = None, label: str = "") -> BackupInfo:
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^a-z0-9-]", "", label.lower())[:30]

    def _name() -> str:
        now = utcnow()  # millisecond resolution: two backups in one second get different names
        return f"cdhrs-backup-{now:%Y%m%d-%H%M%S}{now.microsecond // 1000:03d}{'-' + label if label else ''}.tar.gz"

    data: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    # One transaction under InnoDB's default REPEATABLE READ: every table is read from the
    # same snapshot, so the backup is consistent even while the app keeps writing.
    with engine.connect() as conn:
        with conn.begin():
            revision = _revision(conn)
            for t in _tables():
                rows = [dict(r._mapping) for r in conn.execute(select(t))]
                data[t.name] = rows
                counts[t.name] = len(rows)
    payload = json.dumps(data, default=_json_default, separators=(",", ":")).encode()
    files = sorted(p for p in settings.upload_dir.glob("*") if p.is_file() and _UPLOAD_RE.match(f"uploads/{p.name}"))
    manifest = {
        "format": FORMAT_VERSION, "app": "cdhrs", "created_at": utcnow().isoformat() + "Z", "revision": revision,
        "tables": counts, "data_sha256": hashlib.sha256(payload).hexdigest(), "files": len(files), "label": label,
    }
    for _attempt in range(5):  # O_EXCL never overwrites; on the rare collision pick a new name
        name = _name()
        path = settings.backup_dir / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            import time

            time.sleep(0.002)
    else:
        raise BackupError("Couldn't create a unique backup file name. Try again.", 500)
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for arcname, blob in (("manifest.json", json.dumps(manifest, indent=2).encode()), ("data.json", payload)):
            info = tarfile.TarInfo(arcname)
            info.size = len(blob)
            info.mtime = int(utcnow().timestamp())
            tar.addfile(info, io.BytesIO(blob))
        for f in files:
            tar.add(f, arcname=f"uploads/{f.name}", recursive=False)
    audit(db, action="backup.created", entity="backup", entity_id=name[:50], user_id=user_id, ip=ip,
          details={"rows": sum(counts.values()), "files": len(files)})
    db.commit()
    return _info(path, manifest)


def _info(path: Path, manifest: dict[str, Any]) -> BackupInfo:
    return BackupInfo(name=path.name, size=path.stat().st_size, created_at=manifest.get("created_at", ""), revision=manifest.get("revision", ""),
                      rows=sum(manifest.get("tables", {}).values()), files=int(manifest.get("files", 0)), label=manifest.get("label", ""))


def _resolve(name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise BackupError("Backup not found.", 404)
    path = (settings.backup_dir / name).resolve()
    if path.parent != settings.backup_dir.resolve() or not path.is_file():
        raise BackupError("Backup not found.", 404)
    return path


def _read_manifest(path: Path) -> dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        m = tar.extractfile("manifest.json")
        if m is None:
            raise BackupError("Backup is missing its manifest.", 422)
        return json.loads(m.read(1_000_000))


def list_backups() -> list[BackupInfo]:
    if not settings.backup_dir.exists():
        return []
    out = []
    for p in sorted(settings.backup_dir.glob("cdhrs-backup-*.tar.gz"), reverse=True):
        if not _NAME_RE.match(p.name):
            continue
        try:
            out.append(_info(p, _read_manifest(p)))
        except (tarfile.TarError, KeyError, json.JSONDecodeError, BackupError, OSError):
            out.append(BackupInfo(p.name, p.stat().st_size, "", "unreadable", 0, 0, "corrupt"))
    return out


def _convert(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for col in table.columns:
        if col.name not in row:
            continue
        v = row[col.name]
        if v is not None:
            if isinstance(col.type, DateTime):
                v = datetime.fromisoformat(v)
            elif isinstance(col.type, Date):
                v = date.fromisoformat(v)
        out[col.name] = v
    return out


def restore_backup(db: Session, name: str, user_id: int | None, ip: str | None = None) -> dict[str, Any]:
    path = _resolve(name)
    with tarfile.open(path, "r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
        payload = tar.extractfile("data.json").read()  # type: ignore[union-attr]
        if manifest.get("app") != "cdhrs" or manifest.get("format") != FORMAT_VERSION:
            raise BackupError("This file isn't a CDHRS backup.", 422)
        if hashlib.sha256(payload).hexdigest() != manifest.get("data_sha256"):
            raise BackupError("Backup failed its integrity check (checksum mismatch). It was not restored.", 422)
        with engine.connect() as conn:
            current_rev = _revision(conn)
        if manifest.get("revision") != current_rev:
            raise BackupError(f"Backup schema ({manifest.get('revision')}) differs from this database ({current_rev}). Run the matching migration first.", 409)
        data: dict[str, list[dict[str, Any]]] = json.loads(payload)

        # Safety net: snapshot the current state first, so a restore can itself be undone.
        safety = create_backup(db, user_id, ip, label="pre-restore")

        tables = _tables()
        with engine.begin() as conn:  # single transaction: all or nothing
            # The audit log is append-only: a restore must not erase what happened after the
            # backup (including the restore itself). Only an EMPTY audit log (e.g. after total
            # data loss) is refilled from the backup.
            keep_audit = bool(conn.execute(text("SELECT 1 FROM audit_log LIMIT 1")).first())
            restore_tables = [t for t in tables if not (keep_audit and t.name == "audit_log")]
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
            try:
                for t in reversed(restore_tables):
                    conn.execute(t.delete())
                for t in restore_tables:
                    rows = [_convert(t, r) for r in data.get(t.name, [])]
                    for i in range(0, len(rows), 1000):
                        conn.execute(t.insert(), rows[i:i + 1000])
                if keep_audit:
                    # Kept audit rows may point at users/hospitals created after the backup.
                    conn.exec_driver_sql("UPDATE audit_log SET user_id = NULL WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT user_id FROM `user`)")
                    conn.exec_driver_sql("UPDATE audit_log SET hospital_id = NULL WHERE hospital_id IS NOT NULL AND hospital_id NOT IN (SELECT hospital_id FROM hospital)")
            finally:
                conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")

        # Files: write the backup's documents (validated names only - no path traversal).
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        restored_files = 0
        for member in tar.getmembers():
            if member.isfile() and _UPLOAD_RE.match(member.name):
                src = tar.extractfile(member)
                if src is None:
                    continue
                target = settings.upload_dir / Path(member.name).name
                with open(target, "wb") as out:
                    out.write(src.read())
                os.chmod(target, 0o640)
                restored_files += 1

    # Everyone signs in again against the restored accounts; caches are stale now.
    kv.delete_prefix("sess:")
    kv.delete_prefix("usess:")
    cache.invalidate_prefix("")
    with Session(engine) as s2:
        audit(s2, action="backup.restored", entity="backup", entity_id=name[:50], user_id=None, ip=ip,
              details={"restored_by_user_id": user_id, "rows": sum(manifest.get("tables", {}).values()), "files": restored_files, "safety_backup": safety.name})
        s2.commit()
    return {"rows": sum(manifest.get("tables", {}).values()), "files": restored_files, "safety_backup": safety.name}

