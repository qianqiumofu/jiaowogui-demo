"""宿管预约异动通知模板，追加迁移不重写已应用检查约束。"""
from alembic import op
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint("ck_notifications_template", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_template", "notifications", "template IN ('NIGHT_ROSTER','DAILY_REPORT','WEEKLY_REPORT','RISK_ALERT','DORM_APPROVED','DORM_RESCHEDULED','DORM_CANCELLED')")

def downgrade():
    op.drop_constraint("ck_notifications_template", "notifications", type_="check")
    op.create_check_constraint("ck_notifications_template", "notifications", "template IN ('NIGHT_ROSTER','DAILY_REPORT','WEEKLY_REPORT','RISK_ALERT')")
