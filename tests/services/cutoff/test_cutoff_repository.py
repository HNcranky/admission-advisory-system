from decimal import Decimal

from services.cutoff.repository import CutoffRepository


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = None

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._cur = _FakeCursor(rows)

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_fetch_cutoff_history_maps_rows_and_decimal():
    rows = [
        ("hust", "computer_science", 2025, "thpt_score",
         Decimal("30"), Decimal("28.25"), "https://ts.hust.edu.vn/dc-2025", 5, "TTNV <= 2"),
        ("hust", "computer_science", 2024, "thpt_score",
         Decimal("30"), Decimal("27.10"), "https://ts.hust.edu.vn/dc-2024", 5, None),
    ]
    conn = _FakeConn(rows)
    repo = CutoffRepository(connection_factory=lambda: conn)

    history = repo.fetch_cutoff_history({("hust", "computer_science")})

    entries = history[("hust", "computer_science")]
    assert [e.cutoff_year for e in entries] == [2025, 2024]
    assert entries[0].cutoff_score == 28.25          # Decimal -> float
    assert entries[0].score_scale == 30.0
    assert entries[0].trust_level == 5
    assert entries[0].note == "TTNV <= 2"
    assert "cutoff_records" in conn._cur.executed[0]


def test_fetch_cutoff_history_empty_pairs_skips_db():
    def explode():
        raise AssertionError("DB must not be touched for empty pairs")

    repo = CutoffRepository(connection_factory=explode)
    assert repo.fetch_cutoff_history(set()) == {}
    assert repo.fetch_cutoff_history({("hust", None)}) == {}
