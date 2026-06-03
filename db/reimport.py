import sys, json
sys.path.insert(0, '.')

import ingestion.normalization.program_mapper as pm
if hasattr(pm, "_PROGRAMS_CACHE"):
    pm._PROGRAMS_CACHE = None
if hasattr(pm, "_PROGRAMS_DICT"):
    pm._PROGRAMS_DICT = None

import ingestion.normalization.method_mapper as mm
if hasattr(mm, "_METHODS_CACHE"):
    mm._METHODS_CACHE = None
if hasattr(mm, "_METHOD_DICT"):
    mm._METHOD_DICT = None

import ingestion.normalization.combo_method_mapper as cmm
if hasattr(cmm, "_RULES_CACHE"):
    cmm._RULES_CACHE = None

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records
from ingestion.storage.db_connection import get_cursor

                    
with get_cursor() as cur:
    cur.execute('DELETE FROM canonical_admission_records')
    cur.execute('DELETE FROM extracted_facts')
    print('Cleared old data')

              
pipeline = IngestionPipeline()
source = pipeline.registry.get_source('hust_program_listing')
records = pipeline.run_for_source(source)
print(f'Pipeline produced {len(records)} records')

            
count = save_canonical_records(records)
print(f'Saved {count} records to DB')

        
with get_cursor(commit=False) as cur:
    cur.execute('SELECT COUNT(*) FROM canonical_admission_records')
    total = cur.fetchone()[0]
    print(f'\nDB canonical records: {total}')
    
    cur.execute("""
        SELECT program_id, program_name_canonical, program_name_raw, admission_method
        FROM canonical_admission_records
        ORDER BY program_name_raw
    """)
    
    rows = cur.fetchall()
    with open('db_final_results.txt', 'w', encoding='utf-8') as f:
        f.write(f'Total: {total} clean records\n\n')
        f.write(f'{"Program ID":30s} | {"Canonical":40s} | {"Raw Name":45s} | {"Method"}\n')
        f.write('-' * 140 + '\n')
        for row in rows:
            pid = (row[0] or 'N/A')[:29]
            canonical = (row[1] or 'N/A')[:39]
            raw = (row[2] or 'N/A')[:44]
            method = (row[3] or 'N/A')
            f.write(f'{pid:30s} | {canonical:40s} | {raw:45s} | {method}\n')
    print('Wrote db_final_results.txt')
