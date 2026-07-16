import pytest
from sqlalchemy import text

from server.infrastructure.database import Database


def test_database_probe_and_transaction_commit() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    try:
        assert database.probe()
        with database.session() as session:
            session.execute(text("CREATE TABLE records (value INTEGER NOT NULL)"))
            session.execute(text("INSERT INTO records (value) VALUES (7)"))
        with database.session() as session:
            assert session.execute(text("SELECT value FROM records")).scalar_one() == 7
    finally:
        database.close()


def test_database_session_rolls_back_on_error() -> None:
    database = Database("sqlite+pysqlite:///:memory:")
    try:
        with database.session() as session:
            session.execute(text("CREATE TABLE records (value INTEGER NOT NULL)"))
        with pytest.raises(RuntimeError):
            with database.session() as session:
                session.execute(text("INSERT INTO records (value) VALUES (8)"))
                raise RuntimeError("abort")
        with database.session() as session:
            assert session.execute(text("SELECT COUNT(*) FROM records")).scalar_one() == 0
    finally:
        database.close()
