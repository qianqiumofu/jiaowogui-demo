"""账号表归一后保留原账号字段长度上限。"""
from alembic import op
import sqlalchemy as sa
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column("users", "user_id", type_=sa.String(40))
    op.alter_column("users", "school_id", type_=sa.String(64))
    op.alter_column("users", "display_name", type_=sa.String(80))

def downgrade():
    op.alter_column("users", "display_name", type_=sa.String(64))
    op.alter_column("users", "school_id", type_=sa.String(32))
