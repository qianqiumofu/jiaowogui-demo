"""根路由由 A 维护；B 只需在标注区追加自己模块的 router。"""

from fastapi import APIRouter

from app.api.demo import router as demo_router
from app.modules.agent.router import router as agent_router
from app.modules.access.router import router as access_router
from app.modules.authorization.router import router as authorization_router
from app.modules.building_list.router import router as building_list_router
from app.modules.building_list.router import campus_router as campus_night_router
from app.modules.directory.router import router as directory_router
from app.modules.duty.router import router as duty_router
from app.modules.exports.router import router as exports_router
from app.modules.identity.router import router as identity_router
from app.modules.identity.staff_router import router as staff_accounts_router
from app.modules.notification.router import router as notification_router
from app.modules.reports.router import router as reports_router
from app.modules.reservation.router import router as reservation_router
from app.modules.returns.router import router as returns_router
from app.modules.risk.router import router as risk_router
from app.modules.statistics.router import router as statistics_router

api_router = APIRouter()

# --- A：身份、预约、核验、风险、报告、通知 ---
api_router.include_router(identity_router)
api_router.include_router(staff_accounts_router)
api_router.include_router(authorization_router)
api_router.include_router(reservation_router)
api_router.include_router(risk_router)
api_router.include_router(reports_router)
api_router.include_router(agent_router)
api_router.include_router(notification_router)
api_router.include_router(demo_router)

# --- B：目录、代班、楼栋名单、通行、返宿记录、统计、导出 ---
api_router.include_router(access_router)
api_router.include_router(building_list_router)
api_router.include_router(campus_night_router)
api_router.include_router(directory_router)
api_router.include_router(returns_router)
api_router.include_router(duty_router)
api_router.include_router(statistics_router)
api_router.include_router(exports_router)
# B 新增模块在此追加：from app.modules.<name>.router import router as <name>_router

from app.modules.authorization.management import router as management_router
api_router.include_router(management_router)

from app.modules.verification.router import router as verification_router
api_router.include_router(verification_router)

from app.modules.access.router import integration_router
api_router.include_router(integration_router)
