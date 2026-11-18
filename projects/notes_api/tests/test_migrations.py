"""The Alembic migrations run up and down on SQLite, and 0002 copies the tag data."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_DIR = Path(__file__).resolve().parent.parent


def alembic_config(database_file: Path) -> Config:
    """alembic.ini with the URL of a test database."""
    config = Config(PROJECT_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_file}")
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_downgrade_round_trip(tmp_path: Path) -> None:
    """head creates every table; base removes them again."""
    database_file = tmp_path / "migrations.db"
    config = alembic_config(database_file)
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    assert set(sa.inspect(engine).get_table_names()) == {
        "alembic_version",
        "notes",
        "tags",
        "note_tags",
        "users",
        "refresh_tokens",
        "api_keys",
        "outbox_events",
    }
    command.downgrade(config, "base")
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_data_migration_moves_tags_and_back(tmp_path: Path) -> None:
    """0002 turns 'shop,food' text into rows; downgrading writes the text back."""
    database_file = tmp_path / "data.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0001")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Tea', 'shop,food')"))
        connection.execute(sa.text("INSERT INTO notes (title, tags) VALUES ('Rice', 'shop')"))
    command.upgrade(config, "0002")
    with engine.connect() as connection:
        links = connection.execute(
            sa.text(
                "SELECT notes.title, tags.name FROM note_tags JOIN notes ON notes.id = note_id"
                " JOIN tags ON tags.id = tag_id ORDER BY notes.title, tags.name"
            )
        ).all()
    assert [tuple(row) for row in links] == [("Rice", "shop"), ("Tea", "food"), ("Tea", "shop")]
    command.downgrade(config, "0001")
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT title, tags FROM notes ORDER BY id")).all()
    assert [tuple(row) for row in rows] == [("Tea", "food,shop"), ("Rice", "shop")]
    engine.dispose()


def test_existing_notes_get_a_disabled_legacy_owner(tmp_path: Path) -> None:
    """0004 gives notes written before accounts existed to an owner that cannot log in."""
    database_file = tmp_path / "owners.db"
    config = alembic_config(database_file)
    command.upgrade(config, "0003")
    engine = sa.create_engine(f"sqlite:///{database_file}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO notes (title) VALUES ('Old note')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        owner = connection.execute(
            sa.text(
                "SELECT users.email, users.is_active, users.password_hash FROM notes"
                " JOIN users ON users.id = notes.owner_id"
            )
        ).one()
    assert tuple(owner) == ("legacy-owner@notes.invalid", 0, None)
    engine.dispose()
