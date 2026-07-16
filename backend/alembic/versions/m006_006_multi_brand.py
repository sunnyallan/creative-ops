"""006_multi_brand — wraps db/migrations/006_multi_brand.sql"""
from alembic._sql_runner import run_sql_file

revision = "m006"
down_revision = 'm005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("006_multi_brand.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 006_multi_brand")
