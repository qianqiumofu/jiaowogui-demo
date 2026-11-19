"""复用 A 的共享任务表，补 B 的领取索引和 JSONB 默认值（首次导入迁移）。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "b0005"
down_revision = "b0004"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column("background_jobs", "payload", type_=JSONB(), postgresql_using="payload::jsonb", server_default=sa.text("'{}'::jsonb"))
    op.create_index("ix_jobs_due", "background_jobs", ["status", "planned_at"])

def downgrade():
    op.drop_index("ix_jobs_due", table_name="background_jobs")
    op.alter_column("background_jobs", "payload", type_=sa.JSON(), postgresql_using="payload::json", server_default=None)
