"""remove unused allow_doctor_registration setting

Revision ID: 509aa794a811
Revises: cd852ea33dbc
Create Date: 2026-10-26 22:55:40.143430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '509aa794a811'
down_revision: Union[str, Sequence[str], None] = 'cd852ea33dbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Doctors never register themselves (hospital admins create their accounts), so this
    switch had no effect and only misled administrators on the System & settings page."""
    op.execute("DELETE FROM system_setting WHERE setting_key = 'allow_doctor_registration'")


def downgrade() -> None:
    op.execute("INSERT IGNORE INTO system_setting (setting_key, setting_value, description) "
                "VALUES ('allow_doctor_registration', 'true', 'Allow new doctors to register')")
