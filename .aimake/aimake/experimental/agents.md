# agents.md — aimake/experimental 的知识边界
## OVERVIEW
本目录是 aimake 的**冻结实验入口**（FROZEN，非演进区）：以单文件收纳非核心命令 `scan / update --feedback / ask / scaffold / maintain / ignore`，函数体全部从 `aimake/__main__.py` 逐字迁移，不新增也不删除功能；核心命令（init / update 指纹 / status / tree）不在此处、由 `aimake` 提供。运行方式 `python -m aimake.experimental <命令> [参数]`。
## FILES
- **`__init__.py`**：包级说明文档字符串，声明本包为冻结的实验入口、命令清单与「不拆分多模块、只逐字迁移」的边界约定，无实际逻辑。
- **`__main__.py`**：单文件 CLI 主体，承载全部非核心命令实现（scan 目录扫描/拓扑、ask 关键词问答导航、update --feedback 反馈驱动重生成、scaffold 一句话建项目、maintain 一键维护、ignore 管理忽略规则）及 argparse 子命令分发入口 `main()`/`__main__`。