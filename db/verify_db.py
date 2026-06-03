import sys
sys.path.insert(0, '.')
from ingestion.storage.db_connection import get_cursor

with get_cursor(commit=False) as cur:
    for table in ['source_registry', 'canonical_admission_records']:
        cur.execute(f'SELECT COUNT(*) FROM {table}')
        print(f'{table}: {cur.fetchone()[0]} rows')

    cur.execute("""
        SELECT DISTINCT program_id, program_name_canonical, admission_method
        FROM canonical_admission_records
        WHERE program_id IS NOT NULL
        ORDER BY program_name_canonical
        LIMIT 20
    """)
    print()
    rows = cur.fetchall()
    for row in rows:
        pid, name, method = row
        print(f'  {pid:30s} | {name or "":30s} | {method or ""}')
