"""010_creative_editor — wraps db/migrations/010_creative_editor.sql"""
from db.sql_runner import run_sql_file

revision = "m010"
down_revision = 'm009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("010_creative_editor.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 010_creative_editor")
