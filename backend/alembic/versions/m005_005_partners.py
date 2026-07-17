"""005_partners — wraps db/migrations/005_partners.sql"""
from db.sql_runner import run_sql_file

revision = "m005"
down_revision = 'm004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("005_partners.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 005_partners")
