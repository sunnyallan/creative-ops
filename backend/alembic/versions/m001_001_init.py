"""001_init — wraps db/migrations/001_init.sql"""
from db.sql_runner import run_sql_file

revision = "m001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("001_init.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 001_init")
