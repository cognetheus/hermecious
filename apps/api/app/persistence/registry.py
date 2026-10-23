"""Imports every ORM module so `Base.metadata` is complete (Alembic env, drift test)."""


def register_models() -> None:
    import app.accounts.models  # noqa: F401
    import app.auth.models  # noqa: F401
