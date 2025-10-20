from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from mcp_vertica import sqlman


@dataclass
class _FakeCursor:
    rows: list[tuple]

    def __post_init__(self) -> None:
        self.executed_sql: str | None = None
        self.params: dict | None = None

    def execute(self, sql: str, params: dict) -> None:
        self.executed_sql = sql
        self.params = params

    def fetchall(self):
        return list(self.rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _NoopTimeout:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return None

    def __exit__(self, *_exc):
        return False


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows):
    cursor = _FakeCursor(rows=rows)

    @contextmanager
    def fake_conn():
        yield _FakeConn(cursor)

    monkeypatch.setattr(sqlman, "get_conn", fake_conn)
    monkeypatch.setattr(sqlman, "Timeout", _NoopTimeout)
    monkeypatch.setattr(sqlman, "SQL_DIR", tmp_path)
    return cursor


def test_run_sql_injects_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cursor = _setup(monkeypatch, tmp_path, rows=[("a", 1)])
    (tmp_path / "limit_check.sql").write_text("SELECT :limit AS v", encoding="utf-8")

    monkeypatch.setattr(sqlman.settings, "max_rows", 10)

    rows, provenance = sqlman.run_sql("limit_check.sql", {"schema": "public"}, limit=99)

    assert rows == [("a", 1)]
    assert cursor.params["limit"] == 10
    assert provenance.row_count == 1
    assert provenance.params["limit"] == 10


def test_run_sql_schema_allowlist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _setup(monkeypatch, tmp_path, rows=[])
    (tmp_path / "bad.sql").write_text("SELECT * FROM secret.table", encoding="utf-8")
    monkeypatch.setattr(sqlman.settings, "allowed_schemas", ["public"])

    with pytest.raises(PermissionError):
        sqlman.run_sql("bad.sql", {"schema": "public"})


def test_ensure_schema_allowed_validates_identifiers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sqlman.settings, "allowed_schemas", ["public"], raising=False)

    with pytest.raises(ValueError):
        sqlman.ensure_schema_allowed("bad-schema")

    with pytest.raises(PermissionError):
        sqlman.ensure_schema_allowed("secret")


def test_run_sql_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cursor = _setup(monkeypatch, tmp_path, rows=[("a", 1)])
    (tmp_path / "timeout.sql").write_text("SELECT 1", encoding="utf-8")

    monkeypatch.setattr(sqlman.settings, "max_rows", 5, raising=False)
    monkeypatch.setattr(sqlman.settings, "query_timeout_s", 42, raising=False)

    events: list = []

    class _RecordTimeout:
        def __init__(self, seconds: int) -> None:
            events.append(seconds)

        def __enter__(self):
            events.append("enter")
            return None

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")
            return False

    monkeypatch.setattr(sqlman, "Timeout", _RecordTimeout)

    rows, provenance = sqlman.run_sql("timeout.sql", {"schema": "public"}, limit=10)

    assert rows == [("a", 1)]
    assert cursor.params["limit"] == 5
    assert events[0] == 42
    assert events[-1] == "exit"
    assert provenance.duration_ms >= 0


def test_ranked_multi(monkeypatch: pytest.MonkeyPatch):
    def fake_run_sql(name, params, limit=None):
        rows = {
            "one.sql": [("alpha", 1.0), ("beta", 0.5)],
            "two.sql": [("beta", 0.9), ("gamma", 0.2)],
        }[name]
        prov = sqlman.Provenance(name, params, "ts", len(rows), 0.1)
        return rows, prov

    monkeypatch.setattr(sqlman, "run_sql", fake_run_sql)

    ranked, provenances = sqlman.ranked_multi(
        [("one.sql", {"schema": "public"}), ("two.sql", {"schema": "public"})],
        k=5,
    )

    assert ranked[0] == ("alpha", 1.0)
    assert dict(ranked) == {"alpha": 1.0, "beta": 0.9, "gamma": 0.2}
    assert len(provenances) == 2
    assert {p.sql_or_view for p in provenances} == {"one.sql", "two.sql"}
