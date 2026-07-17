"""008_social_content — wraps db/migrations/008_social_content.sql"""
from db.sql_runner import run_sql_file

revision = "m008"
down_revision = 'm007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("008_social_content.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 008_social_content")
