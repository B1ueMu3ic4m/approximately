# Approximately — 项目计划与技术报告

> **Approximate memory, exact accountability.**
> 上下文运行时（预算窗口 + pins + 召回探针）与飞行记录仪（MAST 失败归因 + 回放 + 回归测试）共用一套录制基建，构成 Agent 可靠性技术栈。

- 仓库：`https://github.com/B1ueMu3ic4m/approximately`
- 版本：v0.1.0（MVP）
- 日期：2026-09-08
- 状态：本文件即设计与发布计划，随代码同仓发布

---

## 1. 问题定位（为什么做）

### 1.1 学术依据（2025–2026 一手论文结论）

| 结论 | 来源 | 关键数字 |
|---|---|---|
| 多智能体失败可被系统分类：14 种失败模式、3 大类 | MAST, [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) | 规格问题 41.77%、智能体失调 36.94%、验证缺失 21.30% |
| **失败自动归因在技术上已可行** | MAST（o1-as-judge） | F1 = 0.80（few-shot），人类标注一致性 κ = 0.88 |
| 失败主因是**系统组织**而非模型能力 | MAST 干预实验 | 仅加验证步骤 +15.6% 绝对成功率；角色提示 +9.4% |
| 第一直击死因是"重复已完成步骤" | MAST FM-1.3 | 占全部轨迹的 17.14% |
| 失败低效使成本/延迟恶化一个数量级 | MAST | 10x+ 成本/延迟放大 |
| GUI Agent 单任务 85% 但长程仅 31% | OSWorld / OSWorld 2.0 | 基准-现实鸿沟在"错误恢复"层 |

推论：失败归因的学术组件（分类学、判官、基准）2025–2026 已齐备，但**生产端只有扁平 tracing（Langfuse/LangSmith），没有 attribution 工具**——论文成果与工程产品之间存在明确空窗，这就是 Approximately 的位置。

### 1.2 产品假设

1. Agent 进入生产的团队每天都会遇到"跑挂了但不知道哪步坏"的问题（痛点频率：小时级）。
2. 开发者愿意为"自动定位 + 可复现 + 防复发"付费/点星，只要 demo 在 30 秒内可见。
3. 以 MAST 为分类内核形成学术差异化；以零依赖 SDK 形成工程差异化。

### 1.3 命名

一次 Agent 执行 = 一场"审判"；因程序性错误而失败 = **approximately（无效审判）**。
审查程序的是判官（LLM-as-judge），重跑是 retrial（replay），防复发是判例（regression tests）。隐喻自洽、单词可注册、全局无同名 AI 项目。

---

## 2. 架构设计

### 2.1 模块

```
approximately/
├── trace.py       轨迹数据模型（Step / Trace / Outcome），stdlib dataclasses + JSON
├── recorder.py    录制器：Recorder + @agentstep 装饰器，零侵入采集
├── store.py       轨迹存储：~/.approximately/traces/*.json
├── taxonomy.py    MAST 14 失败模式的结构化定义（含修复建议库）
├── detectors.py   规则检测引擎（无 LLM 也可归因）
├── judge.py       可选 LLM 判官（OpenAI 兼容接口，结构化输出）
├── attributor.py  归因编排：规则 ∪ 判官 → FailureReport（模式+定位+证据+修复）
├── replayer.py    回放器：对录制的步逐重放并 diff 结果
├── regress.py     回归测试生成器：轨迹 → pytest 文件
├── report.py      自包含 HTML 报告（无外部依赖，可离线打开）
└── cli.py         命令行：record / attribute / replay / test / report / demo / taxonomy
```

### 2.2 数据模型（核心五分钟）

```python
Step:
  index: int                  # 序号
  kind: str                   # "plan" | "tool_call" | "observation" | "response" | "error"
  tool: str | None            # 工具名（tool_call 时）
  args: dict                  # 工具参数
  result: str                 # 结果摘要
  thought: str | None         # 该步的推理摘要（可选）
  tokens: int                 # 该步消耗
  latency_ms: int
  error: str | None
  meta: dict                  # 自由扩展（mutating、success_criteria 等）

Trace:
  id, task, model, created_at, steps: list[Step]
  success: bool, final_output: str | None, meta: dict
```

### 2.3 归因管线

```
Trace ──► 规则检测器组（每个 MAST 模式一个 detector，输出 Detection{mode, step_index, evidence, confidence})
      ──► 可选 LLM 判官（MAST 全分类 + 轨迹 JSON → {mode, step, rationale, confidence}）
      ──► 仲裁：规则与判官一致 → 置信度叠加；冲突 → 取高置信方并标注分歧
      ──► FailureReport：primary_mode / category / evidence chain / suggested_fix / replay_ready
```

规则检测器（v0.1 内置 6 个，均映射 MAST 编号）：

| 检测器 | MAST | 机制 |
|---|---|---|
| `RepeatDetector` | FM-1.3 | 同 (tool, args-hash) 在窗口内重复 ≥2 次 |
| `ConversationResetDetector` | FM-2.1 | 初始任务 prompt 在轨迹中段原文重现 |
| `PrematureTerminationDetector` | FM-3.1 | success=False 且尾部 N 步无修复尝试即终止 |
| `MissingVerificationDetector` | FM-3.2 | 存在 mutating 工具调用但其后无验证步 |
| `DerailmentDetector` | FM-2.3 | 工具调用序列偏离任务关键词集（启发式） |
| `SpecViolationDetector` | FM-1.1 | 使用了任务规格中声明的禁用工具 |

修复建议库：每个模式配 2–3 条可操作修复，直接引用 MAST 干预数据（如 FM-3.2 → "加入显式验证步骤（MAST 干预实验 +15.6%）"）。

### 2.4 回放与回归

- **Replay**：`Executor = Callable[[Step], str]`。对录制轨迹逐步执行，diff 三元组（result 文本相似度 / error / args），输出 `ReplayDiff`。支持 A/B：原执行器 vs 修复后执行器。
- **Regression**：为失败轨迹生成 pytest 文件，两类断言：
  1. 模式断言——重跑后归因器不得再报出原失败模式；
  2. 合同断言——从证据步生成（如 "同一 (tool,args) 不得调用两次"、"mutating 调用后必须出现 verify"）。

### 2.5 零依赖原则

核心包只用 Python 标准库（3.9+）。`openai` 为 optional extra（`pip install approximately[llm]`）。
理由：目标用户环境各异（框架 lockfile 冲突是推广第一杀手）；tracing/归因本可以不碰网络。

---

## 3. 里程碑

### v0.1.0（本次交付，MVP）
- [x] 轨迹模型 + 录制器 + 存储
- [x] 上下文运行时：预算窗口 / pin / compact / 有效召回探针 / 预算推演（`approximately context`）
- [x] demo 集成上下文推演段（"60-token 预算会丢什么"）
- [x] MAST 14 模式结构化分类学与修复建议库
- [x] 6 个规则检测器 + 归因仲裁
- [x] 可选 LLM 判官（OpenAI 兼容）
- [x] 回放器 + A/B diff
- [x] pytest 回归测试生成
- [x] 自包含 HTML 报告
- [x] CLI（含 `approximately demo` 30 秒体验）
- [x] 无 API key 的确定性演示 Agent（重复调用 + 无验证 + 过早终止三重失败）
- [x] 单元测试全绿 + GitHub Actions CI

### v0.2（发布后 2–4 周）
- LangGraph / OpenAI Agents SDK / CrewAI 三个适配器（各 ~100 行）
- 判官 prompt 蒸馏：小模型（本地 Qwen 级）跑归因，成本降一个量级
- MAST-Data 公开轨迹上的归因基准页（对标 o1 F1=0.80，规则引擎能到多少就亮多少）

### v0.3（1–2 月）
- 失败聚类：跨轨迹统计团队级"惯犯模式"（对齐 MAST 的 41.77% 规格类问题）
- 上下文运行时接口预留（压缩/逐出的忠实性探针——调研报告方向 #2 的合并位）
- 与 pytest-github-annotation 集成，CI 里直接在 PR 上标失败步

---

## 4. 发布与增长计划

1. **发布物**：GitHub 公共仓 + PyPI + 一篇技术博客（含 MAST 数据可视化与 demo GIF）。
2. **引爆点排序**：① Hacker News "Show HN"（标题：*Show HN: Approximately – context runtime and automatic postmortems for AI agents*）；② r/LocalLLaMA + r/LLMDevs（本地模型判官角度）；③ X/Twitter Agent 圈；④ 即刻/知乎中文技术社区。
3. **首屏承诺**（README 第一屏即 demo）：`pip install approximately && approximately demo` → 30 秒内看到一份归因报告：找到"第 3 步重复调用搜索工具 + 从未验证预订 + 提前宣告成功"。
4. **传播钩子**：每个 HTML 报告页脚自带项目署名链接，天然自传播。
5. **度量**：首月 star 500 / PyPI 下载 2k 为增长健康线；核心转化是 demo→自有轨迹的替换成本（Recorder API 保持 5 行以内）。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| Langfuse/LangSmith 下沉做 attribution | 他们是 SaaS 记录优先；我们做本地、零依赖、MAST 语义层；且开源速度是护城河 |
| 规则检测器误报 | 每条 Detection 必须携带可读证据链；报告里规则/判官来源分开标注；置信度阈值可配 |
| 学术基准版权/复现问题 | 只引用分类学与数字并规范引用论文；不抓取 MAST-Data 分发，只提供适配接口 |
| 单人维护带宽 | 核心零依赖、接口小（Recorder/Attributor/Replayer 三类），刻意压低维护面 |

## 6. 引用

Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST), arXiv:2503.13657, 2025.
Bohnet et al., *Why Do LLM Agents Fail and How Can They Learn From Failures?*, arXiv:2509.25370, 2025.
*Who&When: Automated Failure Attribution in Multi-Agent Systems*, arXiv:2505.00212, 2025.
Xie et al., *OSWorld: Benchmarking Multimodal Agents*, arXiv:2404.07972, 2024.
Anthropic, *Effective Context Engineering for AI Agents*, 2025.
