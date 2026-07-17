"""013_video_creatives — wraps db/migrations/013_video_creatives.sql"""
from db.sql_runner import run_sql_file

revision = "m013"
down_revision = 'm012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("013_video_creatives.sql")


def downgrade() -> None:
    # We intentionally don't ship downgrades. This is a forward-only
    # migration history — reverting a v-migration is a manual decision
    # per column/table, not a mechanical operation.
    raise NotImplementedError("no downgrade for 013_video_creatives")
