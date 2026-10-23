"""The single SQLAlchemy declarative base. Alembic migrations, never ORM table creation, own the schema."""

from sqlalchemy import MetaData
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names so migrations can reference and drop them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def sqlalchemy_url(database_url: str) -> URL:
    """Map the shared `postgresql://` DATABASE_URL onto the psycopg 3 driver."""
    return make_url(database_url).set(drivername="postgresql+psycopg")
