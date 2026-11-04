# agents.md — .github 的知识边界

## OVERVIEW
本目录是仓库的 **GitHub 协作/自动化元配置区**（社区规范入口 + CI/CD 工作流宿主），目前为**空骨架状态**：注入范围内未发现任何实际文件内容，唯一已知子目录 `workflows/` 也标注「未生成」。因此本页只是导航协议占位——当前无可承诺的「可达」内容，待工作流文件落地后再补充细节。与项目根目录协作：`workflows/` 将承载仓库级 CI/CD 逻辑，而本目录本身不包含业务代码。

## SUB-KNOWLEDGE
- `workflows/` —（未生成）预留的 GitHub Actions 工作流宿主，本目录唯一子目录，生成后在此给出各 workflow 职责摘要与相对路径指针。

## DEPENDS
（暂无真实依赖可记录。）按 GitHub 惯例，本目录未来会依赖：项目根目录的构建/测试脚本产物（项目内指针，生成后回填）、GitHub 托管的 `actions/checkout` 等外部动作（项目外，官方 marketplace）。

## FILES
当前注入范围内**无实际文件**（无模板、无 `.yml`、无 ISSUE_TEMPLATE / CODEOWNERS 等内容）。目录仅按 `.github` 命名约定存在。此小节在文件落地后须依据真实内容改写——禁止按文件名臆测实现。

## WHERE TO LOOK
- 新增/修改 CI 流水线 → `workflows/` 下新建或编辑 workflow 文件（当前未生成，路径待定）。
- 新增 Issue/PR 模板或社区规范 → 依 GitHub 约定建 `ISSUE_TEMPLATE/`、`PULL_REQUEST_TEMPLATE.md`、`CODEOWNERS.md` 于本目录（当前不存在）。
- 排查某个 workflow 触发问题 → 待 `workflows/` 生成后，查看对应 `.yml` 的 `on:` 触发段。
- 复用既有 CI 步骤 → 在根目录与其他子目录的 agents.md 中查构建/测试命令，再映射到 workflow。

## QA
- **Q：.github 里有什么可用的文件？** A：目前为空，注入范围未发现任何文件；不要假设存在默认模板或 workflow。证据：本目录与 `workflows/` 的文件检索均无命中。
- **Q：为什么文档里没有 workflow 细节？** A：`workflows/` 子目录标注「未生成」，无真实内容可溯源，故不臆测，待其生成后补录。
- **Q：想给仓库加 GitHub Actions 应该去哪？** A：放入 `workflows/`（按 GitHub 约定即 `.github/workflows/*.yml`）；触发、job 定义细节见生成后的子目录 agents.md。

## KEY SYMBOLS
（无）——无实际文件与导出符号可列出；本目录为元配置区，正常情况下也不产出被业务代码引用的符号。待文件生成后回填。

## COMMANDS
无独立构建/测试命令。命令编排（若有）将由 `workflows/` 中的 CI 文件引用根目录的构建/测试脚本，届时以那些文件为准。

## ANTI-PATTERNS
- **禁止按目录名虚构内容**：`.github` 是约定名，不代表一定已有 Issue 模板或 workflow——本目录目前确实为空，写出不存在文件即误导。
- **不要把业务逻辑放进 .github**：此目录只承载协作规范与自动化编排，不放实现代码。
- **不要把 workflow 细节写进本页**：细节归 `workflows/` 子级 agents.md，此处仅保留一句话摘要指针。

## EXTERNAL
- GitHub Docs「Using workflows」：https://docs.github.com/actions/using-workflows （外部；知识时效性强，随 GitHub Actions 更新）
- GitHub Docs「社区配置文件」：https://docs.github.com/communities/setting-up-your-project-for-healthy-contributions
- 时效性标注：以上外部链接为 2025 年前后状态；本目录当前无任何内部文件可作时效锚点，更新请以子目录 `workflows/` 生成内容为准。