"""session-bound consent and emergency access

Revision ID: cd852ea33dbc
Revises: 90e55e85df81
Create Date: 2026-10-21 13:51:08.472385

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd852ea33dbc'
down_revision: Union[str, Sequence[str], None] = '90e55e85df81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Consent and emergency access last only for the doctor's sign-in session.

    Rows created before this revision have no session reference and are ended,
    because there is no session they could belong to."""
    for table in ("access_request", "consent", "emergency_access"):
        op.add_column(table, sa.Column("session_ref", sa.String(length=64), nullable=True))
    op.alter_column("consent", "status", existing_nullable=False,
                    type_=sa.Enum("pending_otp", "active", "revoked", "expired", "ended", name="consent_status"),
                    existing_type=sa.Enum("pending_otp", "active", "revoked", "expired", name="consent_status"))
    op.execute("UPDATE consent SET status = 'ended', revoked_at = UTC_TIMESTAMP() WHERE status IN ('active', 'pending_otp')")
    op.execute("UPDATE access_request SET status = 'cancelled' WHERE status = 'pending'")
    op.execute("UPDATE emergency_access SET ended_at = UTC_TIMESTAMP() WHERE ended_at IS NULL AND expires_at > UTC_TIMESTAMP()")


def downgrade() -> None:
    op.execute("UPDATE consent SET status = 'revoked' WHERE status = 'ended'")
    op.alter_column("consent", "status", existing_nullable=False,
                    type_=sa.Enum("pending_otp", "active", "revoked", "expired", name="consent_status"),
                    existing_type=sa.Enum("pending_otp", "active", "revoked", "expired", "ended", name="consent_status"))
    for table in ("emergency_access", "consent", "access_request"):
        op.drop_column(table, "session_ref")
