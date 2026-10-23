"""Alembic environment. Online migrations only, against the validated DATABASE_URL."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.settings import SettingsError, load_settings
from app.persistence.base import Base, sqlalchemy_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if context.is_offline_mode():
    raise SystemExit("alembic: offline (--sql) mode is not supported")

try:
    settings = load_settings()
except SettingsError as exc:
    # No fallback URL: a missing or invalid setting stops the migration.
    raise SystemExit(f"alembic: refusing to run: {exc}") from None

engine = create_engine(
    sqlalchemy_url(str(settings.database_url)),
    poolclass=pool.NullPool,
    connect_args={"connect_timeout": 5},
)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
