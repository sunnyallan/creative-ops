"""015_meta_conn_per_brand — wraps db/migrations/015_meta_conn_per_brand.sql"""
from db.sql_runner import run_sql_file

revision = "m015"
down_revision = "m014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("015_meta_conn_per_brand.sql")


def downgrade() -> None:
    raise NotImplementedError("no downgrade for 015_meta_conn_per_brand")
