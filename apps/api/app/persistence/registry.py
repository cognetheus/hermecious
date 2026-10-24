"""Imports every ORM module so `Base.metadata` is complete (Alembic env, drift test)."""


def register_models() -> None:
    import app.accounts.models  # noqa: F401
    import app.auth.models  # noqa: F401
    import app.discovery.models  # noqa: F401
    import app.jobs.models  # noqa: F401
    import app.offers.models  # noqa: F401
    import app.resolution.models  # noqa: F401
