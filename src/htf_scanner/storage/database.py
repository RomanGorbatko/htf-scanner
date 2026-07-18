from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect

from htf_scanner.storage.models import Base


def create_database_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        _migrate_sqlite(engine)
    return engine


def _migrate_sqlite(engine: Engine) -> None:
    """Apply additive operational migrations to databases created by earlier releases."""
    tables = set(inspect(engine).get_table_names())
    if "alert_deliveries" not in tables:
        return
    columns = {item["name"] for item in inspect(engine).get_columns("alert_deliveries")}
    additions = {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "next_retry_at": "DATETIME",
        "permanently_failed_at": "DATETIME",
    }
    with engine.begin() as connection:
        for name, declaration in additions.items():
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE alert_deliveries ADD COLUMN {name} {declaration}"
                )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_alert_delivery_status_retry "
            "ON alert_deliveries (status, next_retry_at, attempts)"
        )
