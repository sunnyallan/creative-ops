"""002_v1_1 — wraps db/migrations/002_v1_1.sql"""
from db.sql_runner import run_sql_file

revision = "m002"
down_revision = 'm001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("002_v1_1.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 002_v1_1")
