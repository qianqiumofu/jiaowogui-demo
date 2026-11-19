"""目录培养层次；旧档案未知值不猜测、不覆盖现有记录。"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("students", sa.Column("education_level", sa.String(16), nullable=True))
    op.create_check_constraint("ck_students_education_level", "students", "education_level IN ('BACHELOR', 'MASTER', 'DOCTORAL')")


def downgrade():
    op.drop_constraint("ck_students_education_level", "students", type_="check")
    op.drop_column("students", "education_level")
