from .base import DuplicateWeekError, Storage
from .memory import MemoryStorage

__all__ = ["Storage", "MemoryStorage", "DuplicateWeekError", "SqlStorage"]


def __getattr__(name: str):
    # 惰性导入:仅在真正使用 SqlStorage 时才依赖 SQLAlchemy,
    # 内存实现/测试无需安装该依赖。
    if name == "SqlStorage":
        from .sql import SqlStorage
        return SqlStorage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
