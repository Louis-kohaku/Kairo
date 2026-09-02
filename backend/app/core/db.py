from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DATABASE_URL, ensure_data_dirs

ensure_data_dirs()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so they are registered on Base.metadata before create_all.
    from app.models import (  # noqa: F401
        generation,
        job,
        media_asset,
        perf_record,
        production,
        project,
        studio,
        subtitle,
        timeline,
    )

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


# There is no Alembic in this project (create_all only creates missing
# tables, it never alters existing ones), so a new column added to a model
# after the sqlite file already exists would otherwise silently never
# appear. This adds any columns new model definitions gained, without
# touching existing data - safe because every new column here is nullable.
_NEW_COLUMNS = {
    "jobs": [("error_detail", "TEXT"), ("step", "TEXT")],
    "generations": [("error_detail", "TEXT")],
    # Short-form scene design (design doc section 20): a scene stopped
    # being "narration + a visual prompt" once the pipeline had to
    # actually produce, time and assemble it, so each of these carries one
    # decision a later stage needs to make. All nullable/defaulted, so
    # projects planned before this existed still load.
    "scenes": [
        ("purpose", "TEXT"),
        ("emotion", "TEXT"),
        ("camera", "TEXT"),
        ("subtitle_text", "TEXT"),
        ("sfx", "TEXT"),
        ("bgm_cue", "TEXT"),
        ("transition", "TEXT"),
        ("continuity", "TEXT"),
        ("asset_source", "TEXT"),
        ("user_asset_id", "TEXT"),
        ("media_asset_id", "TEXT"),
        ("narration_asset_id", "TEXT"),
        ("narration_duration", "REAL"),
        ("start_time", "REAL"),
        ("is_hook", "INTEGER"),
    ],
}


def _ensure_columns() -> None:
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, sql_type in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
