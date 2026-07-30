"""Todo 数据模型与管理逻辑：增删改查 + JSON 持久化。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class TodoItem:
    """单条待办事项。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    done: bool = False
    priority: int = 0          # 0 普通, 1 重要, 2 紧急
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            title=data.get("title", ""),
            done=data.get("done", False),
            priority=int(data.get("priority", 0)),
            created_at=float(data.get("created_at", time.time())),
        )


# ---------------------------------------------------------------------------
# 管理器
# ---------------------------------------------------------------------------
class TodoManager:
    """负责加载、保存、增删改查待办列表。"""

    def __init__(self, save_path: str | Path) -> None:
        self.save_path = Path(save_path)
        self.todos: list[TodoItem] = []
        # 当列表发生变化时通知外部（用于刷新 UI / 更新托盘文字）
        self._listeners: list[Callable[[], None]] = []
        self.load()

    # ---- 持久化 ----------------------------------------------------------
    def load(self) -> None:
        if not self.save_path.exists():
            self.todos = []
            return
        try:
            raw = json.loads(self.save_path.read_text(encoding="utf-8"))
            self.todos = [TodoItem.from_dict(d) for d in raw]
        except (json.JSONDecodeError, OSError):
            self.todos = []

    def save(self) -> None:
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        data = [t.to_dict() for t in self.todos]
        self.save_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- 观察者 ----------------------------------------------------------
    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    # ---- CRUD ------------------------------------------------------------
    def add(self, title: str, priority: int = 0) -> TodoItem:
        item = TodoItem(title=title.strip(), priority=priority)
        self.todos.append(item)
        self.save()
        self._notify()
        return item

    def update(
        self, todo_id: str, title: str | None = None,
        priority: int | None = None, done: bool | None = None,
    ) -> bool:
        for t in self.todos:
            if t.id == todo_id:
                if title is not None:
                    t.title = title.strip()
                if priority is not None:
                    t.priority = priority
                if done is not None:
                    t.done = done
                self.save()
                self._notify()
                return True
        return False

    def toggle(self, todo_id: str) -> bool:
        for t in self.todos:
            if t.id == todo_id:
                t.done = not t.done
                self.save()
                self._notify()
                return True
        return False

    def delete(self, todo_id: str) -> bool:
        before = len(self.todos)
        self.todos = [t for t in self.todos if t.id != todo_id]
        changed = len(self.todos) < before
        if changed:
            self.save()
            self._notify()
        return changed

    def clear_done(self) -> int:
        before = len(self.todos)
        self.todos = [t for t in self.todos if not t.done]
        removed = before - len(self.todos)
        if removed:
            self.save()
            self._notify()
        return removed

    # ---- 查询 ------------------------------------------------------------
    @property
    def pending(self) -> list[TodoItem]:
        return [t for t in self.todos if not t.done]

    def stats(self) -> tuple[int, int]:
        """返回 (待办数, 已完成数)。"""
        done = sum(1 for t in self.todos if t.done)
        return len(self.todos) - done, done
