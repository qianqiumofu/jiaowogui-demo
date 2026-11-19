"""正式返宿的只追加证据；一事实多证据，不改唯一返宿约束。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision="0017"
down_revision="0016"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("return_evidence",sa.Column("id",sa.String(40),primary_key=True),sa.Column("return_id",sa.String(32),sa.ForeignKey("return_records.return_id",ondelete="CASCADE"),nullable=False),sa.Column("source_key",sa.String(160),nullable=False,unique=True),sa.Column("kind",sa.String(16),nullable=False),sa.Column("payload",JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))

def downgrade():
    op.drop_table("return_evidence")
