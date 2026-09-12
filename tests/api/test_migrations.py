"""Guard against the classic drift: models changed, migration forgotten."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.db.base import Base

#: SQLite and PostgreSQL legitimately disagree about index and type details;
#: a missing or extra table or column never is a legitimate difference.
STRUCTURAL = {"add_table", "remove_table", "add_column", "remove_column"}


@pytest.fixture
def migrated_sqlite(tmp_path):
    db = tmp_path / "migrations.db"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.attributes["sqlalchemy_url"] = f"sqlite+aiosqlite:///{db}"
    command.upgrade(config, "head")
    return f"sqlite:///{db}"


def test_migrations_reproduce_the_model_metadata(migrated_sqlite):
    engine = create_engine(migrated_sqlite)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    structural = [d for d in diff if isinstance(d, tuple) and d[0] in STRUCTURAL]
    assert structural == [], f"models and migrations disagree: {structural}"


def test_downgrade_to_base_is_possible(tmp_path):
    """A migration you cannot roll back is a migration you cannot deploy safely."""
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.attributes["sqlalchemy_url"] = f"sqlite+aiosqlite:///{tmp_path / 'down.db'}"
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{tmp_path / 'down.db'}")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    # Everything the models define is now "missing" from the empty database.
    dropped = {d[1].name for d in diff if isinstance(d, tuple) and d[0] == "add_table"}
    assert dropped == set(Base.metadata.tables)
