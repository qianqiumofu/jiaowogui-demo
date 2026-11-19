"""导出任务记录发起时的学生范围快照；NULL 表示不裁剪（园区全校与历史行）。

范围内导出让辅导员/思政/学院负责人复用统计口径时只导自己负责的学生，
范围在创建时固化，worker 渲染不再依赖会话上下文，也不受之后负责关系变更影响。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("export_jobs", sa.Column("scope_student_ids", JSONB(), nullable=True))


def downgrade():
    op.drop_column("export_jobs", "scope_student_ids")
