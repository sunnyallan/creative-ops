"""009_layouts_templates — wraps db/migrations/009_layouts_templates.sql"""
from alembic._sql_runner import run_sql_file

revision = "m009"
down_revision = 'm008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("009_layouts_templates.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 009_layouts_templates")
