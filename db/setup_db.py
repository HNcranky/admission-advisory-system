import sys
import os
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode the emoji used in the
# progress output below. Force UTF-8 so `python -m db.setup_db` works out of the box.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from ingestion.config.settings import DB_CONFIG


def create_database():
    """Create the admission database if it doesn't exist."""
                                                
    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database="postgres",
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

                              
    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (DB_CONFIG["database"],)
    )
    exists = cur.fetchone()

    if not exists:
        cur.execute(f'CREATE DATABASE {DB_CONFIG["database"]}')
        print(f"✅ Database '{DB_CONFIG['database']}' created")
    else:
        print(f"✅ Database '{DB_CONFIG['database']}' already exists")

    cur.close()
    conn.close()


def run_migrations():
    """Run all SQL migration files in order."""
    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()

    migrations_dir = Path(__file__).parent / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration_file in migration_files:
        print(f"  Running {migration_file.name}...")
        sql = migration_file.read_text(encoding="utf-8")
        try:
            cur.execute(sql)
            conn.commit()
            print(f"  ✅ {migration_file.name} applied")
        except Exception as e:
            conn.rollback()
            print(f"  ⚠️  {migration_file.name} error: {e}")

    cur.close()
    conn.close()


def verify_tables():
    """Verify all tables were created."""
    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]

    print(f"\n📋 Tables in '{DB_CONFIG['database']}':")
    
    expected = [
    "source_registry",
    "discovered_resources",
    "raw_documents",
    "extracted_facts",
    "canonical_admission_records",
    "advisory_runs",
    "chat_sessions",
    "chat_messages",
    "chat_advisory_runs",
    "knowledge_documents",
    "knowledge_chunks",
    "program_catalog_embeddings",
]
    for table in expected:
        status = "✅" if table in tables else "❌"
        print(f"  {status} {table}")

    cur.close()
    conn.close()
    return all(t in tables for t in expected)


def seed_source_registry():
    """Seed the source_registry table from initial_sources.json."""
    import json

    seed_file = (
        project_root / "ingestion" / "registry" / "seeds" / "initial_sources.json"
    )
    with open(seed_file, "r", encoding="utf-8") as f:
        sources = json.load(f)

    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = conn.cursor()

    inserted = 0
    for source in sources:
        try:
            cur.execute("""
                INSERT INTO source_registry
                    (source_id, school_id, school_name, source_type, root_url,
                     trust_level, priority, fetch_strategy, parser_profile,
                     update_frequency_hint, is_official, active, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO NOTHING
            """, (
                source["source_id"],
                source["school_id"],
                source["school_name"],
                source["source_type"],
                source["root_url"],
                source.get("trust_level", 3),
                source.get("priority", 5),
                source.get("fetch_strategy", "http"),
                source.get("parser_profile", "default"),
                source.get("update_frequency_hint", "weekly"),
                source.get("is_official", True),
                source.get("active", True),
                json.dumps(source.get("metadata")) if source.get("metadata") else None,
            ))
            inserted += 1
        except Exception as e:
            print(f"  ⚠️  Failed to seed {source['source_id']}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n🌱 Seeded {inserted} sources into source_registry")


if __name__ == "__main__":
    print("=" * 50)
    print("  Admission Database Setup")
    print("=" * 50)
    print(f"\n🔌 Connecting to PostgreSQL at {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"   User: {DB_CONFIG['user']}")
    print(f"   Database: {DB_CONFIG['database']}\n")

                             
    print("Step 1: Creating database...")
    create_database()

                            
    print("\nStep 2: Running migrations...")
    run_migrations()

                    
    print("\nStep 3: Verifying tables...")
    ok = verify_tables()

                       
    if ok:
        print("\nStep 4: Seeding source registry...")
        seed_source_registry()

    print("\n" + "=" * 50)
    if ok:
        print("  ✅ Setup complete!")
    else:
        print("  ❌ Some tables missing, check errors above")
    print("=" * 50)
