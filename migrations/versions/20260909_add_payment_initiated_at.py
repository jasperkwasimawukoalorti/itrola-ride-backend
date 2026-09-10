"""add payment_initiated_at to trips

Revision ID: 20260909_payment_initiated_at
Revises: None
Create Date: 2026-09-09 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260909_payment_initiated_at'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE trips ADD COLUMN IF NOT EXISTS payment_initiated_at TIMESTAMP WITH TIME ZONE NULL;"
    )


def downgrade():
    op.execute(
        "ALTER TABLE trips DROP COLUMN IF EXISTS payment_initiated_at;"
    )
