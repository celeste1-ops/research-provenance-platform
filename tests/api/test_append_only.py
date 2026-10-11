"""AC-05: the records table rejects UPDATE/DELETE; no route edits or deletes records."""

import re
import sqlite3

import pytest
from fastapi.routing import APIRoute

from app.main import create_app


def test_direct_update_and_delete_fail(api, ctx):
    api.init()
    api.entry("first", body="some text", files=[("a.csv", b"1,2\n")])
    con = sqlite3.connect(ctx.settings.db_path)
    before = con.execute("SELECT id, manifest_bytes, payload_bytes, signature FROM records ORDER BY seq").fetchall()
    for sql in (
        "UPDATE records SET payload_bytes = x'00' WHERE seq = 1",
        "UPDATE records SET kind = 'entry'",
        "DELETE FROM records WHERE seq = 1",
        "DELETE FROM records",
        "UPDATE record_files SET sha256 = 'x'",
        "DELETE FROM record_files",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute(sql)
    after = con.execute("SELECT id, manifest_bytes, payload_bytes, signature FROM records ORDER BY seq").fetchall()
    assert before == after
    con.close()


def test_no_route_edits_or_deletes_records(ctx):
    app = create_app(ctx)
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    assert routes
    for route in routes:
        assert not ({"PUT", "PATCH", "DELETE"} & route.methods), route.path
        assert not re.search(r"edit|update|delete|remove|modify", route.path), route.path
    record_routes = [r for r in routes if r.path.startswith("/api/records")]
    assert all(r.methods <= {"GET", "HEAD"} for r in record_routes)
