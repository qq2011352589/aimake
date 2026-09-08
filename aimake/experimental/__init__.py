"""aimake 实验入口（FROZEN）。

本包是**冻结的实验入口**：只收纳 aimake 的非核心命令
（scan / update --feedback / ask / scaffold / maintain / ignore），
全部从 `aimake/__main__.py` **逐字迁移**而来。

- 冻结含义：不新增功能、不删除功能——是"冻结墓地"不是"演进区"。
- 核心命令（init / update 指纹 / status / tree）仍由 `aimake` 提供。
- 本包刻意为单文件 `__main__.py`，不拆分多模块。

用法：

    python -m aimake.experimental <命令> [参数]
"""
