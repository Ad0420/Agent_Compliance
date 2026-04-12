#!/bin/sh
# Run alembic migrations.
# On first Railway deploy the tables were created by SQLAlchemy's create_all,
# not by alembic, so alembic_version is empty and the initial migration fails
# ("table already exists"). In that case we stamp the DB with the last known
# good revision and re-run so only the new migrations are applied.
if ! alembic upgrade head; then
    echo "Alembic upgrade failed — stamping existing schema and retrying"
    alembic stamp b2c3d4e5f6a7
    alembic upgrade head
fi
python setup_local.py
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
