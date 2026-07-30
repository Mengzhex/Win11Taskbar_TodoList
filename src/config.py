"""
应用配置 — 持久化用户设置
========================
保存字体大小、存储路径等设置到 JSON 文件。
配置文件路径: %APPDATA%/TaskbarTodo/settings.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# 默认配置
DEFAULTS: dict[str, Any] = {
    "font_size": 11,           # 字体大小（之前写死 9，太小）
    "font_family": "Microsoft YaHei UI",  # Win11 中文原生 UI 字体；不可用时自动回退
    "data_dir": "",            # 空=使用默认 %APPDATA%/TaskbarTodo
}


class Settings:
    """用户配置管理。"""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        """从 JSON 文件加载配置。"""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 只接受已知 key，合并默认值
                for key in DEFAULTS:
                    if key in saved:
                        self._data[key] = saved[key]
            except (json.JSONDecodeError, OSError):
                pass  # 配置损坏时用默认值

    def save(self) -> None:
        """保存配置到 JSON 文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    # ---- 便捷属性 ----

    @property
    def font_size(self) -> int:
        return int(self._data.get("font_size", DEFAULTS["font_size"]))

    @property
    def font_family(self) -> str:
        return str(self._data.get("font_family", DEFAULTS["font_family"]))

    @property
    def data_dir(self) -> str:
        """返回数据存储目录，空字符串表示用默认路径。"""
        return str(self._data.get("data_dir", ""))

    def resolve_data_dir(self) -> Path:
        """返回最终的数据存储目录 Path（展开环境变量）。"""
        d = self.data_dir.strip()
        if d:
            return Path(os.path.expandvars(d))
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "TaskbarTodo"
