"""007_drop_brand_kits — wraps db/migrations/007_drop_brand_kits.sql"""
from alembic._sql_runner import run_sql_file

revision = "m007"
down_revision = 'm006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("007_drop_brand_kits.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 007_drop_brand_kits")
