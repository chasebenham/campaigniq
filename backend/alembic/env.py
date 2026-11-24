from alembic import context
from sqlalchemy import create_engine, pool

from app import ai_models, detection_models, models
from app.config import Settings

config = context.config
metadata = models.Base.metadata
url = config.attributes.get("database_url") or Settings().database_url


def run_migrations(connection=None):
    if connection is None:
        context.configure(url=url, target_metadata=metadata, literal_binds=True)
    else:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations()
elif connection := config.attributes.get("connection"):
    run_migrations(connection)
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_migrations(connection)
