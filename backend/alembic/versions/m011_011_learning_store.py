"""011_learning_store — wraps db/migrations/011_learning_store.sql"""
from alembic._sql_runner import run_sql_file

revision = "m011"
down_revision = 'm010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("011_learning_store.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 011_learning_store")
