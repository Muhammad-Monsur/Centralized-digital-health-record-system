"""Phase 7: N+1 query guard.

Counts SQL statements per page via an engine event. A page is N+1-free when adding
more rows to its list does NOT add queries. Ceilings catch regressions.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from sqlalchemy import event, select

from app.database import engine
from app.models import AccessLog, Doctor, Patient, User
from app.models.enums import AccessType, InformationType, Visibility
from app.services import records
from tests.conftest import make_client


@contextmanager
def count_queries():
    n = {"q": 0}

    def _cb(*_a, **_k):
        n["q"] += 1

    event.listen(engine, "before_cursor_execute", _cb)
    try:
        yield n
    finally:
        event.remove(engine, "before_cursor_execute", _cb)


def _queries(client, path: str) -> int:
    client.get(path)  # warm caches (settings, permissions are per request anyway)
    with count_queries() as n:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code)
    return n["q"]


def _add_records(db, username: str, k: int) -> None:
    p = db.scalar(select(Patient).join(User).where(User.username == username))
    d = db.scalar(select(Doctor).join(User).where(User.username == "dr.hasan"))
    for i in range(k):
        info = records.create(db, patient_id=p.patient_id, author_user_id=d.user_id, information_type=InformationType.LAB_REPORT,
                              title=f"Perf record {i}", details="x", information_date=date(2024, 1, 1 + i % 28),
                              visibility=Visibility.PUBLIC, doctor_id=d.doctor_id, hospital_id=d.hospital_id)
        db.add(AccessLog(user_id=d.user_id, patient_id=p.patient_id, access_type=AccessType.VIEW_PUBLIC, information_id=info.information_id))
    db.commit()


PAGES = {
    "patient": ["/patient", "/patient/records", "/patient/access-history", "/patient/consent"],
    "dr.hasan": ["/doctor", "{doctor_patient}"],
    "sysadmin": ["/admin", "/admin/users", "/admin/audit", "/admin/hospitals", "/admin/access", "/admin/emergency?tab=inter"],
}
CEILING = 25


def test_query_counts_do_not_grow_with_data(db, upis):
    clients = {u: make_client() for u in PAGES}
    for u, c in clients.items():
        c.login(u)

    def measure() -> dict[str, int]:
        out = {}
        for u, paths in PAGES.items():
            for p in paths:
                path = p.format(doctor_patient=f"/doctor/patients/{upis['patient2']}")
                out[path] = _queries(clients[u], path)
        return out

    # Populate every list first (some pages run one extra lookup only when a list is non-empty),
    # then grow the data 6x: an N+1 page would add queries proportional to the new rows.
    _add_records(db, "patient", 5)
    _add_records(db, "patient2", 5)
    before = measure()
    _add_records(db, "patient", 25)
    _add_records(db, "patient2", 25)
    after = measure()
    report = "\n".join(f"{p:<45} {before[p]:>3} -> {after[p]:>3}" for p in before)
    print("\nSQL statements per page (10 -> 60 extra records and access-log rows)\n" + report)
    for p in before:
        assert after[p] <= before[p], f"N+1 suspected on {p}: {before[p]} -> {after[p]}\n{report}"
        assert after[p] <= CEILING, f"{p} runs {after[p]} queries\n{report}"
