"""014_audit_entity_text — wraps db/migrations/014_audit_entity_text.sql"""
from db.sql_runner import run_sql_file

revision = "m014"
down_revision = "m013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("014_audit_entity_text.sql")


def downgrade() -> None:
    raise NotImplementedError("no downgrade for 014_audit_entity_text")
