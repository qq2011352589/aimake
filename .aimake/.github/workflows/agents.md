# agents.md — .github/workflows 的知识边界
## OVERVIEW
存放仓库的 GitHub Actions 工作流：一条用于自动生成 aimake 知识树（增量、可续跑），一条用于多平台（原生 + Termux）发布 Release。此目录是 CI 编排层，只管"何时跑、在什么机器上跑、怎么跑"，不含业务逻辑；如需改发布流程或知识生成节奏，改这里。

## FILES
- **aimake-knowledge.yml**：`aimake knowledge (incremental)` —— 每日 03:00（cron）自动增量生成仓库知识树，也可 workflow_dispatch 手动触发并传入时间预算与节点上限；产物提交推送到 `aimake-knowledge` 分支（force push，不污染主分支），并上传 status 报告；全部节点落盘后自动递增打 `knowledge-vN` tag；无 `AIMAKE_OPENAI_API_KEY` 时整体跳过（守卫）。
- **release.yml**：`release` —— 推送 `v*` tag 时触发构建并发布 Release；`build-native` 用 Nuitka onefile 在 Linux/macOS(arm64)/Windows 上并行原生编译出 `aimake-<os>-<arch>` 单文件资产；`build-termux` 用 qemu + termux-docker 容器编译出 bionic 版 `aimake-termux-<aarch64|arm|x86_64>`（与 glibc 版不可互换）；`publish` 校验全部资产就绪后一次性创建 GitHub Release 附带资产（workflow_dispatch 仅产出 artifact 不发布）。