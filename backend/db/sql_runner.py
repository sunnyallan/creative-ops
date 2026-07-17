"""Helper used by every SQL-wrapper revision.

Each revision calls `run_sql_file(__file__, 'NNN_name.sql')` — the helper
resolves the sibling db/migrations/ dir, reads the SQL, and executes it
inside Alembic's current connection so it runs in the same transaction as
the version-table update.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

_SQL_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def run_sql_file(filename: str) -> None:
    """Execute the contents of db/migrations/<filename>. Splits on ';' at
    statement boundaries so each statement runs individually — required
    because Postgres can't run multi-statement DDL in a single execute
    when some statements are in a DO $$…$$ block."""
    path = _SQL_DIR / filename
    sql = path.read_text()

    # Simple but correct-enough splitter that respects dollar-quoted blocks
    # (used by our migrations for the create-role idempotency wrapper).
    statements: list[str] = []
    buf: list[str] = []
    in_dollar = False
    for line in sql.splitlines():
        buf.append(line)
        stripped = line.strip()
        if "$$" in stripped:
            in_dollar = not in_dollar
        # A statement ends on a line whose semicolon is outside a $$ block.
        if not in_dollar and stripped.endswith(";"):
            joined = "\n".join(buf).strip()
            if joined and not joined.startswith("--"):
                statements.append(joined)
            buf = []
    tail = "\n".join(buf).strip()
    if tail and not tail.startswith("--"):
        statements.append(tail)

    for stmt in statements:
        # Skip lines that are ONLY comments
        clean = "\n".join(l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")).strip()
        if not clean:
            continue
        op.execute(stmt)
