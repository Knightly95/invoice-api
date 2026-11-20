"""Alembic runs migrations against DATABASE_URL, or a connection it is given
(the tests pass their own)."""

from alembic import context
from sqlalchemy import Connection, create_engine

from invoice_api.config import get_settings
from invoice_api.models import Base

target_metadata = Base.metadata


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


given = context.config.attributes.get("connection")
if given is not None:
    run(given)
else:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
