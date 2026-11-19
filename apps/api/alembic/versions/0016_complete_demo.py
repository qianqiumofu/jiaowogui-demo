"""完整 Demo：分层授权、持久会话、核验/回执、纠错、订阅与风险。冻结 DDL，旧迁移不修改。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("identity_types", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("users", sa.Column("college_org_id", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("position_title", sa.String(64), nullable=False, server_default=""))
    op.add_column("students", sa.Column("major", sa.String(64), nullable=False, server_default="合成专业"))
    op.add_column("students", sa.Column("class_name", sa.String(32), nullable=False, server_default="合成班级"))
    op.execute('\nCREATE TABLE role_assignments (\n\tid VARCHAR(40) NOT NULL, \n\tuser_id VARCHAR(40) NOT NULL, \n\trole VARCHAR(32) NOT NULL, \n\tscope JSONB NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tgranted_by VARCHAR(40), \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_user_role UNIQUE (user_id, role), \n\tFOREIGN KEY(user_id) REFERENCES users (user_id)\n)\n\n')
    op.execute('\nCREATE TABLE identity_sessions (\n\tid VARCHAR(40) NOT NULL, \n\ttoken_digest VARCHAR(64) NOT NULL, \n\tuser_id VARCHAR(40) NOT NULL, \n\trole VARCHAR(32) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (token_digest), \n\tFOREIGN KEY(user_id) REFERENCES users (user_id)\n)\n\n')
    op.execute('\nCREATE TABLE audit_logs (\n\tid VARCHAR(40) NOT NULL, \n\tactor_user_id VARCHAR(40), \n\taction VARCHAR(64) NOT NULL, \n\ttarget VARCHAR(128) NOT NULL, \n\tpayload JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n')
    op.execute('\nCREATE TABLE verification_sessions (\n\tid VARCHAR(32) NOT NULL, \n\treservation_id VARCHAR(40) NOT NULL, \n\tstudent_id VARCHAR(32) NOT NULL, \n\treservation_version INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tface_result BOOLEAN NOT NULL, \n\tpresence_result BOOLEAN NOT NULL, \n\tpass_id VARCHAR(32), \n\tconsumed_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n')
    op.execute('\nCREATE TABLE passage_attempts (\n\tid VARCHAR(32) NOT NULL, \n\tpass_id VARCHAR(32) NOT NULL, \n\tdevice_id VARCHAR(32) NOT NULL, \n\tstudent_id VARCHAR(32) NOT NULL, \n\tservice_date DATE NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tmock_result VARCHAR(16) NOT NULL, \n\trequested_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_attempt_pass UNIQUE (pass_id)\n)\n\n')
    op.execute('\nCREATE TABLE access_receipts (\n\tid VARCHAR(40) NOT NULL, \n\tevent_id VARCHAR(128) NOT NULL, \n\tattempt_id VARCHAR(32) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\treceived_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (event_id)\n)\n\n')
    op.execute('\nCREATE TABLE return_corrections (\n\tid VARCHAR(40) NOT NULL, \n\treturn_id VARCHAR(32) NOT NULL, \n\tactor_user_id VARCHAR(40) NOT NULL, \n\tnote VARCHAR(500) NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(return_id) REFERENCES return_records (return_id)\n)\n\n')
    op.execute('\nCREATE TABLE report_subscriptions (\n\tuser_id VARCHAR(40) NOT NULL, \n\tdaily BOOLEAN NOT NULL, \n\tweekly BOOLEAN NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (user_id), \n\tFOREIGN KEY(user_id) REFERENCES users (user_id)\n)\n\n')
    op.execute('\nCREATE TABLE risk_events (\n\tid VARCHAR(40) NOT NULL, \n\tstudent_id VARCHAR(32) NOT NULL, \n\tservice_date DATE NOT NULL, \n\trule_version VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tfacts JSONB NOT NULL, \n\trecipients JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_risk_event_fact UNIQUE (student_id, service_date, rule_version)\n)\n\n')
    op.execute('\nCREATE TABLE risk_actions (\n\tid VARCHAR(40) NOT NULL, \n\tevent_id VARCHAR(40) NOT NULL, \n\tactor_user_id VARCHAR(40) NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\tnote VARCHAR(500) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(event_id) REFERENCES risk_events (id)\n)\n\n')
    op.execute('\nCREATE TABLE policy_versions (\n\tversion VARCHAR(64) NOT NULL, \n\trules JSONB NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tactor_user_id VARCHAR(40) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (version)\n)\n\n')
    op.execute("UPDATE users SET identity_types = CASE WHEN source='STAFF_LOCAL' THEN '[\"EMPLOYEE\"]'::jsonb WHEN login_name='student' THEN '[\"STUDENT\"]'::jsonb WHEN login_name='counselor' THEN '[\"TEACHER\",\"STUDENT\"]'::jsonb ELSE '[\"TEACHER\"]'::jsonb END")
    op.execute("UPDATE users SET college_org_id=(SELECT college_org_id FROM students s WHERE s.user_id=users.user_id LIMIT 1)")
    op.execute("INSERT INTO role_assignments(id,user_id,role,scope,active) SELECT 'migrate:'||u.user_id||':'||r.role,u.user_id,r.role,'{}'::jsonb,true FROM users u JOIN (VALUES ('student','STUDENT'),('counselor','COUNSELOR'),('counselor','STUDENT'),('campus','CAMPUS'),('dorm','DORM_MANAGER')) AS r(login,role) ON r.login=u.login_name")


def downgrade():
    op.drop_table("policy_versions")
    op.drop_table("risk_actions")
    op.drop_table("risk_events")
    op.drop_table("report_subscriptions")
    op.drop_table("return_corrections")
    op.drop_table("access_receipts")
    op.drop_table("passage_attempts")
    op.drop_table("verification_sessions")
    op.drop_table("audit_logs")
    op.drop_table("identity_sessions")
    op.drop_table("role_assignments")
    op.drop_column("students", "class_name")
    op.drop_column("students", "major")
    op.drop_column("users", "position_title")
    op.drop_column("users", "college_org_id")
    op.drop_column("users", "identity_types")
