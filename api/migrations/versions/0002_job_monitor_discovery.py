"""Persist monitor resume references and latest results.

Revision ID: 0002_job_monitor_discovery
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_job_monitor_discovery"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_monitors", sa.Column("resume_id", sa.String(length=36), nullable=False, server_default=""))
    op.add_column("job_monitors", sa.Column("last_results", sa.JSON(), nullable=False, server_default="[]"))
    op.alter_column("job_monitors", "resume_id", server_default=None)
    op.alter_column("job_monitors", "last_results", server_default=None)


def downgrade() -> None:
    op.drop_column("job_monitors", "last_results")
    op.drop_column("job_monitors", "resume_id")
