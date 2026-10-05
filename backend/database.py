import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads a .env file at the project root, if present
except ImportError:
    pass  # python-dotenv not installed yet -> env vars can still be set manually

BASE_DIR = Path(__file__).resolve().parent.parent  # project root (one above /backend)

DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()  # "mysql" for now "sqlite"

if DB_ENGINE == "mysql":
    DB_USER = os.environ.get("DB_USER", "cdhrs_user")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_NAME = os.environ.get("DB_NAME", "cdhrs")
    # PyMySQL is a pure-Python MySQL driver -> no extra system libraries needed on any OS.
    SQLALCHEMY_DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=280)
else:
    # Dev fallback only - used automatically when DB_ENGINE is not set to "mysql".
    # Lives next to this backend/ folder (not the project root) so it's easy
    # to find and clean up: backend/cdhrs.db
    sqlite_path = Path(__file__).resolve().parent / "cdhrs.db"
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{sqlite_path}"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    # Create every table defined in models.py if it does not already exist.
    # Safe to call every time the app starts - it will not touch existing data.
    from . import models  # noqa: F401  (import so Base knows about every model)
    Base.metadata.create_all(bind=engine)
