import io
import sys

from ingestion.main import _print_schools, main
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline


def _cp1252_stdout(monkeypatch):
    output_buffer = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(output_buffer, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)
    return output_buffer, cp1252_stdout


def test_print_schools_writes_cp1252_safe_output(monkeypatch):
    output_buffer, cp1252_stdout = _cp1252_stdout(monkeypatch)

    _print_schools(IngestionPipeline())

    cp1252_stdout.flush()
    output = output_buffer.getvalue().decode("cp1252")
    output.encode("ascii")
    assert "School ID" in output
    assert "------------" in output


def test_main_no_arg_path_writes_cp1252_safe_header(monkeypatch):
    output_buffer, cp1252_stdout = _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["ingestion.main"])

    main()

    cp1252_stdout.flush()
    output = output_buffer.getvalue().decode("cp1252")
    output.encode("ascii")
    assert "Admission Data Ingestion Pipeline" in output
    assert "No action specified" in output


def test_print_schools_transliterates_unicode_school_names(monkeypatch):
    output_buffer, cp1252_stdout = _cp1252_stdout(monkeypatch)

    class UnicodeSchoolPipeline:
        def list_schools(self):
            return [
                {
                    "school_id": "vnu_uet",
                    "school_name": "Trường Đại học Công nghệ - ĐHQGHN",
                    "active_sources": 1,
                    "total_sources": 2,
                }
            ]

    _print_schools(UnicodeSchoolPipeline())

    cp1252_stdout.flush()
    output = output_buffer.getvalue().decode("cp1252")
    output.encode("ascii")
    assert "Truong Dai hoc Cong nghe - DHQGHN" in output
    assert "?" not in output
