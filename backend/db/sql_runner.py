"""Helper used by every SQL-wrapper revision.

Each revision calls `run_sql_file('NNN_name.sql')` — the helper resolves
the sibling db/migrations/ dir, reads the SQL, and executes it inside
Alembic's current connection so it runs in the same transaction as the
version-table update.
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

_SQL_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def _has_real_sql(block: str) -> bool:
    """True iff block contains any non-comment, non-whitespace line."""
    for line in block.splitlines():
        s = line.strip()
        if s and not s.startswith("--"):
            return True
    return False


def run_sql_file(filename: str) -> None:
    """Execute the contents of db/migrations/<filename> statement-by-statement.
    Splits on ';' at statement boundaries so each statement runs individually
    — required because Postgres can't run multi-statement DDL in a single
    execute when some statements are in a DO $$…$$ block.

    Comments and blank lines that precede a real statement are kept in the
    statement (Postgres tolerates leading comments) — this fixes the earlier
    bug where a leading comment made the whole statement look like a comment
    and got skipped, silently dropping the ALTER TABLE in migration 015.
    """
    path = _SQL_DIR / filename
    sql = path.read_text()

    statements: list[str] = []
    buf: list[str] = []
    in_dollar = False
    for line in sql.splitlines():
        buf.append(line)
        stripped = line.strip()
        if "$$" in stripped:
            in_dollar = not in_dollar
        # Statement boundary: semicolon on this line, outside a $$ block.
        if not in_dollar and stripped.endswith(";"):
            joined = "\n".join(buf).strip()
            # Only skip if the block is EMPTY OR pure comments/whitespace.
            # If there's any real SQL in there, execute the whole block —
            # leading comments are fine for Postgres.
            if _has_real_sql(joined):
                statements.append(joined)
            buf = []
    tail = "\n".join(buf).strip()
    if _has_real_sql(tail):
        statements.append(tail)

    for stmt in statements:
        op.execute(stmt)
