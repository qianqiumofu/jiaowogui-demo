"""全仓库唯一的 SQLAlchemy DeclarativeBase；各模块模型注册到同一个 metadata。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
