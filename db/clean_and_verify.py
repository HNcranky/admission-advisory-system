import sys
sys.path.insert(0, '.')
from ingestion.storage.db_connection import get_cursor

with get_cursor() as cur:
                                                                     
    cur.execute("DELETE FROM canonical_admission_records WHERE program_name_raw LIKE 'K00%'")
                         
    cur.execute("DELETE FROM canonical_admission_records WHERE program_name_raw LIKE 'D01D01%'")
    cur.execute("DELETE FROM canonical_admission_records WHERE program_name_canonical LIKE 'K00%'")
    cur.execute("DELETE FROM canonical_admission_records WHERE program_name_canonical LIKE 'D01%'")

with get_cursor(commit=False) as cur:
    cur.execute('SELECT COUNT(*) FROM canonical_admission_records')
    total = cur.fetchone()[0]
    print(f'Total clean records: {total}')
    
    cur.execute("""
        SELECT program_id, program_name_canonical, program_name_raw
        FROM canonical_admission_records
        ORDER BY program_name_raw
    """)
    
    rows = cur.fetchall()
    with open('db_final_clean.txt', 'w', encoding='utf-8') as f:
        f.write(f'HUST Admission Programs in PostgreSQL: {total} records\n')
        f.write('=' * 120 + '\n\n')
        for i, row in enumerate(rows, 1):
            pid = row[0] or 'N/A'
            canonical = row[1] or 'N/A'
            raw = row[2] or 'N/A'
            f.write(f'{i:3d}. [{pid}] {canonical}\n')
            if canonical != raw:
                f.write(f'     Raw: {raw}\n')
            f.write('\n')
    print('Wrote db_final_clean.txt')
