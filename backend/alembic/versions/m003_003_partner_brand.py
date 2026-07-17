"""003_partner_brand — wraps db/migrations/003_partner_brand.sql"""
from db.sql_runner import run_sql_file

revision = "m003"
down_revision = 'm002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("003_partner_brand.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 003_partner_brand")
