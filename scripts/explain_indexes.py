"""Show which index MySQL uses for each hot query (index justification).

    python -m scripts.explain_indexes

Each query below is the one a real page runs; the "key" column must name an index,
never NULL (= full table scan). Tables are padded with ~1,000 synthetic rows first so the
optimizer behaves as it would with real data; the padding is deleted afterwards by ID
range (ANALYZE TABLE commits implicitly, so a rollback alone would not remove it).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from app.database import engine

QUERIES: list[tuple[str, str]] = [
    ("Doctor looks up patient by UPI", "SELECT patient_id FROM patient WHERE UPI = 'CDH-0000-0000-0000'"),
    ("Sign-in by username / email", "SELECT user_id FROM `user` WHERE email = 'x@example.com'"),
    ("Patient's record list (visibility filter)",
     "SELECT information_id FROM medical_information WHERE patient_id = 1 AND visibility = 'public' AND status = 'active' ORDER BY information_date DESC LIMIT 10"),
    ("Patient's records by date", "SELECT information_id FROM medical_information WHERE patient_id = 1 ORDER BY information_date DESC LIMIT 10"),
    ("Is consent active? (every private read)",
     "SELECT consent_id FROM consent WHERE patient_id = 1 AND doctor_id = 1 AND status = 'active' AND expires_at > NOW()"),
    ("Is emergency access active?",
     "SELECT emergency_access_id FROM emergency_access WHERE doctor_id = 1 AND patient_id = 1 AND expires_at > NOW() AND ended_at IS NULL"),
    ("Patient's pending requests", "SELECT request_id FROM access_request WHERE patient_id = 1 AND status = 'pending'"),
    ("Patient's access history (newest first)", "SELECT access_log_id FROM access_log WHERE patient_id = 1 ORDER BY accessed_at DESC LIMIT 15"),
    ("Doctor's recent patients", "SELECT patient_id, MAX(accessed_at) FROM access_log WHERE user_id = 1 GROUP BY patient_id"),
    ("Audit log by action prefix, newest first", "SELECT audit_id FROM audit_log WHERE action LIKE 'auth.%' ORDER BY `timestamp` DESC LIMIT 25"),
    ("Audit log for one user", "SELECT audit_id FROM audit_log WHERE user_id = 1 ORDER BY `timestamp` DESC LIMIT 25"),
    ("Audit log for one entity", "SELECT audit_id FROM audit_log WHERE entity = 'consent' AND entity_id = '5'"),
    ("Unread notifications badge", "SELECT COUNT(*) FROM notification WHERE user_id = 1 AND is_read = 0"),
    ("Record update history", "SELECT history_id FROM medical_information_history WHERE information_id = 1 ORDER BY changed_at DESC"),
    ("Hospital admin's doctors", "SELECT doctor_id FROM doctor WHERE hospital_id = 1 AND verification_status = 'pending'"),
]


def _pad(conn) -> None:
    """Add synthetic rows so tables aren't trivially small."""
    conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
    today = date.today()
    conn.execute(text("""INSERT INTO access_log (user_id, patient_id, access_type, accessed_at)
                         SELECT 1 + (n % 7), 1 + (n % 3), 'view_public', NOW() - INTERVAL n MINUTE
                         FROM (SELECT a.N + b.N * 10 + c.N * 100 AS n FROM
                              (SELECT 0 N UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) a,
                              (SELECT 0 N UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) b,
                              (SELECT 0 N UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) c) t"""))
    conn.execute(text("INSERT INTO audit_log (user_id, action, entity, entity_id, `timestamp`) SELECT user_id, 'auth.login', 'user', user_id, accessed_at FROM access_log"))
    conn.execute(text("""INSERT INTO medical_information (patient_id, information_type, title, details, information_date, visibility, status, created_by_user_id, created_at, updated_at)
                         SELECT patient_id, 'note', 'Padding', '', :d - INTERVAL access_log_id DAY, IF(access_log_id % 2, 'public', 'private'), 'active', 1, NOW(), NOW()
                         FROM access_log LIMIT 1000""".replace("'note'", "'clinical_note'")), {"d": today - timedelta(days=1)})
    conn.execute(text("ANALYZE TABLE access_log, audit_log, medical_information"))


PADDED = ("access_log", "audit_log", "medical_information")
PK = {"access_log": "access_log_id", "audit_log": "audit_id", "medical_information": "information_id"}


def main() -> int:
    with engine.connect() as conn:
        marks = {t: conn.execute(text(f"SELECT COALESCE(MAX({PK[t]}), 0) FROM {t}")).scalar() for t in PADDED}
        try:
            _pad(conn)
            conn.commit()
            print(f"{'Query':<45} {'table':<28} {'type':<7} {'key used':<40} rows")
            print("-" * 130)
            bad = 0
            for label, sql in QUERIES:
                row = conn.execute(text("EXPLAIN " + sql)).mappings().first()
                if row["table"] is None:  # e.g. unique-index miss: resolved before reading any table
                    print(f"{label[:44]:<45} {'(const)':<28} {'const':<7} {(row['Extra'] or '')[:40]:<40} 0")
                    continue
                key = row["key"] or "NONE (full scan!)"
                bad += row["key"] is None
                print(f"{label[:44]:<45} {row['table']:<28} {row['type'] or '':<7} {key:<40} {row['rows']}")
            print("-" * 130)
            print("All hot queries use an index." if not bad else f"{bad} queries without an index!")
        finally:
            conn.rollback()
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for t in PADDED:
                conn.execute(text(f"DELETE FROM {t} WHERE {PK[t]} > :m"), {"m": marks[t]})
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
