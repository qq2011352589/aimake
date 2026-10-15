# agents.md — bin 的知识边界
## OVERVIEW
`bin` 目录只有一个自包含启动器 `aimake`：它是 `aimake` 可执行程序的入口（Termux 环境专用），负责在调用真正的 `aimake.bin` 前修正动态链接器所需的 `LD_LIBRARY_PATH`，以定位 bionic libpython。

## FILES
- `aimake`：Bash 启动器。解析自身真实路径并定位同目录下的 `aimake.bin`，向环境导出 Termux 的 `/data/data/com.termux/files/usr/lib` 到 `LD_LIBRARY_PATH`（保留已有值），随后用 `exec` 把参数转交给 `aimake.bin`，实现 Python 可执行文件的独立封装。