"""004_creative_persona — wraps db/migrations/004_creative_persona.sql"""
from db.sql_runner import run_sql_file

revision = "m004"
down_revision = 'm003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("004_creative_persona.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 004_creative_persona")
