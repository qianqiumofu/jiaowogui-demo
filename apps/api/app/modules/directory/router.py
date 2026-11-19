"""目录模块（B 主责）：联系方式是字段级权限，仅当班阿姨可按值班范围取。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.errors import out_of_scope
from app.modules.authorization.dependencies import require
from app.modules.directory import service
from app.modules.identity.schemas import SessionContext

router = APIRouter(prefix="/directory", tags=["directory"])

ContactDep = Annotated[SessionContext, Depends(require("contact:read_duty"))]
ResidentsDep = Annotated[SessionContext, Depends(require("building_residents:read_duty"))]


@router.get("/buildings/{building_id}/residents")
def building_residents(
    building_id: str, context: ResidentsDep, request: Request, q: str | None = None
) -> dict:
    """现场补录的选人入口：楼栋必须在当前有效值班范围内，否则 OUT_OF_SCOPE（R11）。

    与 `/return-records/manual` 用同一份 `scope.building_ids` 判定，能搜到的才补得录。
    名册不含联系方式——补录只需要身份，联系方式另走 `contact:read_duty`。
    """
    allowed = [str(item) for item in context.scope.get("building_ids") or []]
    if building_id not in allowed:
        raise out_of_scope("building", building_id, allowed)
    items = service.search_building_residents(
        building_id, q, request.app.state.clock.now()
    )
    return {"building_id": building_id, "items": items, "next_cursor": None}


@router.get("/students/{student_id}/contact")
def student_contact(student_id: str, context: ContactDep, request: Request) -> dict:
    """名单里点开发消息时才走这里：不在班或楼栋不在值班范围内一律 403（R11、docs/08）。

    学生不存在与不在范围内给同一个响应，避免用状态码探测名册。
    """
    at = request.app.state.clock.now()
    contact = service.get_contact(student_id, at)
    allowed = service.get_duty_buildings(context.user_id, at)
    if contact is None or contact["building_id"] not in allowed:
        raise out_of_scope("student_contact", student_id, allowed)
    return {
        "student_id": contact["student_id"],
        "school_id": contact["school_id"],
        "display_name": contact["display_name"],
        "grade": contact["grade"],
        "gender": contact["gender"],
        "building_id": contact["building_id"],
        "room_no": contact["room_no"],
        "phone": contact["phone"],
    }


@router.get("/students")
def students(guarded: Annotated[SessionContext,Depends(require("directory:students"))],college_org_id: str|None=None,major: str|None=None,grade: str|None=None,class_name: str|None=None,q: str|None=None):
    return {"items":service.student_directory(guarded,{"college_org_id":college_org_id,"major":major,"grade":grade,"class_name":class_name,"q":q}),"next_cursor":None}


@router.get("/options")
def student_options(guarded: Annotated[SessionContext,Depends(require("directory:students"))]):
    rows=service.student_directory(guarded)
    return {"colleges":[{"org_id":k,"name":v} for k,v in sorted({r["college_org_id"]:r["college_name"] for r in rows}.items())],
            "majors":sorted({r["major"] for r in rows}),"grades":sorted({r["grade"] for r in rows}),"classes":sorted({r["class_name"] for r in rows})}
