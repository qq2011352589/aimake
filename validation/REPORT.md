# aimake 真实项目验证报告

> 日期：2026-09-09 ｜ 引擎：opencode 1.17.7（模型 deepseek-v4.1-flash）｜ 消费模型：同族（有效性威胁）
> 目标：`wap`（TypeScript，27 个可见目录，4 层，双框架）｜ 提交：`8951465`（本地）

## 1. 结论（Executive Summary）

**NEEDS WORK（结构性）** —— aimake 的核心承诺**成立**：**可达性 100%**（10/10 问题都从知识树路由到了正确源文件，0 MISS）。
但**精度受限**：只有 50% 得到精确到行/符号的指针，20% 树内直接给出答案。根因是**轻量档阈值过激**（20/27 节点只含 OVERVIEW+FILES），而非模型能力。
此外发现一个独立缺陷：**符号自检误报率极高（37 条告警，精确率约 19%）**，削弱了"status 可信"的承诺。

## 2. 生成指标（Generation）

| 指标 | 值 |
|---|---|
| 节点覆盖 | **27/27（100%）** |
| 失败 | 0 |
| 墙钟时间 | **6m15s** |
| 引擎调用 | 27（每目录 1 次，全部首次成功） |
| 并发 | 6 |
| ANSI 污染 | 无 |
| 内容分级 | **7 FULL / 20 LIGHT** |

## 3. 方法（Method）

- **Agent A（真值）**：只读**冻结快照** `$RUN/wap` 源码，产出 10 个非平凡问题 + `file:line` 证据（5 个 `wap-framework` + 5 个 `WAPGamePlayFramework`）。
- **Agent B（盲测）**：物理隔离沙箱（只含 `.aimake` 树 + 全 0 字节的源码占位），仅用树 + `tree`/`ask` 回答同样 10 问，报告机制与指针。
- **评分**：机制分（QA_DIRECT 4 / WHERE_ROUTE 3 / DEPENDS_JUMP 3 / SOURCE_CANDIDATE 2 / TREE_DRILL 1 / MISS 0）+ 正确性分（2/1/0）。

> 注：首次真值取自**实时** `~/wap`，期间仓库正被改动（`AIController.ts` 出现/消失、文件变动），故改为对**同一冻结快照**重新取真值，消除快照漂移。

## 4. 盲测结果（逐题）

| 题 | 目标（真值） | 机制 | 指针 | 命中文件 | M | C | 合计 |
|---|---|---|---|---|---|---|---|
| Q1 | `wap-framework/src/safety.ts:28` | QA_DIRECT | `safety.ts:28-37` | ✅ | 4 | 2 | 6 |
| Q2 | `wap-framework/src/config.ts:106` | WHERE_ROUTE | `config.ts:127-176` | ✅ | 3 | 1 | 4 |
| Q3 | `wap-framework/src/client/WapParser.ts:213` | WHERE_ROUTE | `WapParser.ts:20` | ✅ | 3 | 1 | 4 |
| Q4 | `wap-framework/src/client/GameClient.ts:69` | SOURCE_CANDIDATE | `GameClient.ts:13` | ✅ | 2 | 1 | 3 |
| Q5 | `wap-framework/src/game/actionBuilder.ts:11-29` | SOURCE_CANDIDATE | `actionBuilder.ts:31` | ✅ | 2 | 1 | 3 |
| Q6 | `WAPGamePlayFramework/src/game/GameLoop.ts:91` | WHERE_ROUTE | `GameLoop.ts:17-27` | ✅ | 3 | 0 | 3 |
| Q7 | `WAPGamePlayFramework/src/config.ts:79` | QA_DIRECT | `config.ts:79-90,102` | ✅ | 4 | 2 | 6 |
| Q8 | `WAPGamePlayFramework/src/client/StateTracker.ts:131` | SOURCE_CANDIDATE | `StateTracker.ts` | ✅ | 2 | 1 | 3 |
| Q9 | `WAPGamePlayFramework/src/game/StateSync.ts:176` | SOURCE_CANDIDATE | `StateSync.ts` | ✅ | 2 | 1 | 3 |
| Q10 | `WAPGamePlayFramework/src/framework/gameRunner.ts:327` | SOURCE_CANDIDATE | `gameRunner.ts` | ✅ | 2 | 1 | 3 |

**汇总**
- 总分：**38/60（63%）**
- 可达性（命中正确文件）：**10/10 = 100%**
- 精确导航（M≥3）：**5/10 = 50%**
- 树内直接给答案（C=2）：**2/10 = 20%**
- MISS：**0**
- 机制分布：QA_DIRECT 2 ｜ WHERE_ROUTE 3 ｜ SOURCE_CANDIDATE 5 ｜ MISS 0

## 5. 关键发现

### F1（好）核心承诺成立——可达性 100%
每一个问题都通过树路由到了**正确的源文件**，零 MISS。这验证了"导航仪不是答案本、承诺可达不承诺已知"的定位。`ask` 在 QA 命中时给出带证据的答案（Q1/Q7），WHERE TO LOOK 在未命中时给出正确文件级导航。

### F2（瓶颈）轻量档阈值过激，精度止步于"文件级"
`decide_tier`：`file_count < 10 且 child_count == 0 → LIGHT`。真实代码目录（`src/ai` 2 文件、`src/client` 3 文件…）**全部落为 LIGHT**，只生成 `OVERVIEW + FILES`（7-9 行），**没有 QA / WHERE TO LOOK / KEY SYMBOLS / DEPENDS**。
结果：74%（20/27）的节点只能给到"哪个文件"，给不到"哪一行/哪个符号"。这是精确导航只有 50%、树内答案只有 20% 的**结构性根因**——不是模型不行，是档位设计把信息砍掉了。

### F3（缺陷）符号自检误报率极高（精确率约 19%）
`aimake status` 报 **37 条"KEY SYMBOLS 失效"**，逐条核验后 **30/37 是被冤枉的**（符号真实存在）。两个根因：
1. **反引号未剥离**：生成的真实格式是 `` - `loadConfig` — `src/config.ts:130` ``,而 `_symbol_selfcheck` 取 head 时**没去掉反引号**，于是 `` `loadConfig` `` 在源码（无引号）里当然找不到——**连本目录自己文件里定义的符号都被判失效**。现有单测只覆盖 markdown 表格格式，未覆盖模型实际输出的 bullet+反引号格式，所以没被发现。
2. **聚合节点越界**：父节点的 KEY SYMBOLS 天然会引用子目录符号（如根节点列 `HttpClient`/`FreeAIModel`），但自检只搜"本目录自己的文件"，于是全判失效。

影响：通道 3 本是"零 token 的信任兜底"，现在几乎全噪音，`status` 的可信度受损。

### F4（缺陷）跨目录契约过度泛化
根 `agents.md` 跨目录契约 #5 断言"两份副本都检查标签+链接 href+表单 action"，但真值显示 `WAPGamePlayFramework` 的 `GameLoop` **只检查 `action.label`**。盲测 Agent B 因此被误导（Q6 答案错误，C=0）。聚合层的横切契约把一份副本的行为套到了另一份上。

### F5（现实）源码漂移
验证期间 `~/wap` 正被改动（`AIController.ts` 在快照后出现）。树对**其快照**是忠实的（不含该文件、并正确标注"源码缺失"），但实时源码已变——说明 `status`/`update` 的时效性检查在真实开发中至关重要。

## 6. 建议（按杠杆排序）

1. **重标定内容分级**（最高杠杆）：把 LIGHT 阈值收紧（如"有代码文件即 FULL"），或让 LIGHT 节点也产出**极简 WHERE/KEY SYMBOLS**。直接提升精确导航率。
2. **修符号自检**：`_symbol_selfcheck` 取符号时 `strip("`")`；聚合节点改为搜索**子树**或跳过父节点。补一个"bullet+反引号"格式的回归测试。
3. **收紧跨目录契约生成**：要求每条契约带证据且**逐副本**验证，禁止把一份副本的行为泛化到另一份。

## 7. 复现

```bash
export PYTHONPATH=/data/data/com.termux/files/home/aimake
RUN=/data/data/com.termux/files/usr/tmp/opencode/aimake-validation
cd $RUN && python3 -m aimake init wap --engine opencode --concurrency 6
python3 -m aimake status wap
python3 -m aimake tree wap
# 盲测沙箱：$RUN/agentB（.aimake 树 + 0 字节源码占位）
```
