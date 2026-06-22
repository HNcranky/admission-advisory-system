import psycopg2

from ingestion.config.settings import DB_CONFIG, DB_POOL_ENABLED


def get_db_connection():
    if DB_POOL_ENABLED:
        from services.db.pool import lease
        return lease(DB_CONFIG)
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )