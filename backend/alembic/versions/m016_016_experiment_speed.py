"""016_experiment_speed — sub-hour metric windows + skip_governance flag"""
from db.sql_runner import run_sql_file

revision = "m016"
down_revision = "m015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("016_experiment_speed.sql")


def downgrade() -> None:
    raise NotImplementedError("no downgrade for 016_experiment_speed")
