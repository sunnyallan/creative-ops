"""012_meta_connections — wraps db/migrations/012_meta_connections.sql"""
from db.sql_runner import run_sql_file

revision = "m012"
down_revision = 'm011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("012_meta_connections.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 012_meta_connections")
