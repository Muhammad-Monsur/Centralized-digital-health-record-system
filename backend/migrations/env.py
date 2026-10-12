from alembic import context

from backend import models  # loads every table so Alembic can see them
from backend.database import Base, engine

target_metadata = Base.metadata


def run_migrations_online():
    with engine.connect() as connection:
        # render_as_batch lets SQLite handle ALTER TABLE changes too
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
