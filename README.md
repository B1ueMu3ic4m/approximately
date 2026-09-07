# approximately

**让 AI 代理的记忆是近似的，但问责是精确的。**
**Approximate memory, exact accountability.**

<p align="center">
<b>免费开源 · 零依赖 · MIT 协议 · Python 3.9+ · pip install approximately</b>
</p>

---

## 这是什么？（一段话版本）

**approximately 是给 AI 代理（Agent）装的"行车记录仪 + 事故调查报告"。**

现在的 AI 代理会自己规划、自己调用工具、自己执行几十步任务——但你几乎看不到它到底干了什么。它跑挂了，你只知道"失败了"，不知道错在哪一步、错在哪类问题、下次会不会再犯。

approximately 把它干的每一步都录下来；失败时自动告诉你**错在第几步、属于学术上已分类的 14 种失败模式中的哪一种**、该怎么修；还能一键重放验证、自动生成防止复发的测试。除此之外，它还回答另一个所有团队都会遇到的问题：**给 AI 的上下文窗口开多大才划算？** 大了费钱，小了它会"忘记"关键信息——approximately 用数据告诉你答案。

## 它能帮你解决什么？

| 你遇到的烦恼 | approximately 给你的答案 |
|---|---|
| "代理跑挂了，但日志几千行，不知道哪步错的" | 自动归因：直接指出**第几步、哪种失败模式**（如"第 2 步：重复执行已完成的操作"——这是研究中占比最高的失败原因，占 17%） |
| "修好了，但下周又犯同样的错" | 自动把失败案例变成**回归测试**，同样的错第二次出现时 CI 直接报警 |
| "重跑一次要花钱，不想瞎试" | **一键重放**：不重跑整个任务，逐条验证修复是否生效 |
| "上下文窗口开多大？压缩会不会丢关键信息？" | **上下文预算管理**：告诉你"预算砍到多少时，AI 会开始忘记什么"，并能在 CI 里防止别人悄悄改坏它 |
| "团队 100 次失败里，最该先修什么？" | **惯犯模式统计**：跨任务聚类，找出系统性反复出现的失败模式 |
| "失败日志太长，人工 review 不过来" | 归因报告自带证据链（指向具体步骤），人工只看关键处 |

## 为什么这些数字可信？

approximately 的失败分类体系直接来自 2025–2026 年的权威研究，不是拍脑袋：

- 多智能体系统失败可以被系统分类为 **14 种模式、3 大类**（[MAST 论文，arXiv:2503.13657](https://arxiv.org/abs/2503.13657)，1600+ 条人工标注轨迹，分类一致性 κ=0.88）
- 其中 **41.8% 是规格与设计问题**（组织层面的问题，不是模型笨），**21.3% 是验证缺失**——都可以用工程手段修复
- 研究还证明：只加一步"结果验证"，成功率绝对值提升 **15.6%**（approximately 的修复建议直接引用了这些数字）
- 上下文"修一修比塞满更好"有实证：裁剪+摘要让任务成功率从 71% 升到 91.6%，token 省 2.7 倍（[arXiv:2606.10209](https://arxiv.org/abs/2606.10209)）

## 给谁用？

- **Agent 应用开发者**：你的代理上生产了，你需要"出事能查、查完能防"
- **技术负责人**：你想知道团队该优先修什么，而不是凭感觉
- **AI 应用创业公司**：客户问"为什么这次结果错了"，你要能拿出证据链
- **研究者**：14 种失败模式的分类器、基准评测工具、蒸馏数据导出，开箱即用

## 它是怎么工作的？（不写代码版本）

1. **录制**：在代理外面包一层"记录仪"，它调用的每个工具、每步推理、每次结果都会被存档（对 LangChain/LangGraph、OpenAI Agents SDK、CrewAI 提供了一键接入的适配器）
2. **归因**：失败发生后，内置的规则引擎 + 可选的 AI 判官按 MAST 分类学给出结论——模式、步骤、证据链、修复建议
3. **重放**：把录制的步骤重新执行一遍，对比每一步的输出，确认"修复真的生效了"
4. **防复发**：失败案例一键变成自动化测试，进 CI，永不重演

<details>
<summary><b>🔧 开发者快速开始（2 条命令 + 5 行代码）</b></summary>

```bash
pip install approximately
approximately demo        # 30 秒看懂：内置一个会犯三种典型错误的示例代理
```

```python
from approximately import Recorder, agentstep

@agentstep
def search_flights(origin, destination): ...   # 被装饰的函数自动录制

with Recorder("订一张 SFO 到东京的最便宜机票") as rec:
    search_flights("SFO", "NRT")               # 自动记录
    rec.tool("book_flight", {"seat": "12A"}, mutating=True, result="BOOKED #1")
    rec.respond("订好了！", success=True)
# 结束后轨迹自动存档，一条命令出归因报告
```

```bash
approximately attribute <trace-id>            # 自动归因（离线、免费）
approximately attribute <trace-id> --judge    # 加上 AI 判官（可选）
approximately test <trace-id> --budget 800    # 生成防复发测试 + 预算守卫
```

</details>

<details>
<summary><b>📺 真实运行输出（点开看 demo 长什么样）</b></summary>

```text
recorded demo trace 4deba35fcf37 (6 steps)
──────────────────────────────────────────────────────────────
  VERDICT  FM-1.3 Step Repetition
  FM-1.3 Step Repetition at step #2: The agent unnecessarily redoes steps it already completed.
──────────────────────────────────────────────────────────────
  · FM-1.3 via rule:RepeatDetector (confidence 0.80) — step #2
      - first call: #1 [tool_call] search_flights: JT-044 SFO→NRT ...
      - repeated call: #2 [tool_call] search_flights: JT-044 SFO→NRT ...
      - 2 identical calls within a 6-step window
  · FM-3.1 via rule:PrematureTerminationDetector (confidence 0.70) — step #5
  · FM-3.2 via rule:MissingVerificationDetector (confidence 0.70) — step #4
  SUGGESTED FIXES
    1. Track completed actions in an explicit working state ...
──────────────────────────────────────────────────────────────
  CONTEXT RUNTIME — what a 60-token budget would do to this run
──────────────────────────────────────────────────────────────
  context forecast for 4deba35fcf37 @ budget 60 tokens
    full context: 182 tokens | budgeted: 55 | saved: 127
    evictions: 2 | effective recall 50% (2 kept, 2 lost)
    lost facts: search_flights#1, search_flights#2
    hint: pin critical facts (runtime.pin) or raise the budget
──────────────────────────────────────────────────────────────
HTML report: ~/.approximately/traces/4deba35fcf37.report.html
```

同一份轨迹还会生成一份可视化 HTML 验尸报告：失败结论、证据链、该失败模式在研究数据中的占比位置、完整时间线（过错步骤高亮）、修复建议清单。

</details>

---

## 六大功能一览

| 功能 | 一句话说明 | 命令 / API |
|---|---|---|
| 📼 飞行记录仪 | 零依赖录制代理每一步，支持任意框架 | `Recorder` / 框架适配器 |
| 🔍 失败归因 | 按 MAST 分类学自动定位失败模式与步骤，附修复建议 | `approximately attribute` |
| 🔁 步级回放 | 不重跑任务即可验证修复，逐条 diff | `approximately replay` |
| 🧪 回归守卫 | 失败案例自动变成 pytest 测试，进 CI 防复发 | `approximately test` |
| 📉 上下文预算 | 告诉你"预算砍到多少会开始忘记什么"，可进 CI 守卫 | `approximately context` / `curve` |
| 🔎 惯犯聚类 | 跨任务统计系统性失败模式，排出修复优先级 | `approximately cluster` |

进阶能力：**本地小模型判官**（`distill` 导出训练数据，蒸馏到你自己的 1–7B 模型，省 API 费）、**归因基准评测**（`benchmark`，逐模式精确率/召回率）、**成本-召回曲线报告**（`curve`）。

## 设计原则

1. **零依赖**：核心只用 Python 标准库，归因完全离线、确定性、免费
2. **证据或闭嘴**：每个结论都带指向具体步骤的可读证据链
3. **永不帮倒忙**：没有 API key、没有网络？归因自动降级，绝不让你的程序崩
4. **失败是工程问题**：每条修复建议都有研究数据背书

## 常见问题

**Q: 它支持我的框架吗？**
支持。核心录制 API 不依赖任何框架——只要你的代码能调函数，就能被录制。此外官方适配器覆盖 LangChain / LangGraph（回调处理器）、OpenAI Agents SDK（追踪处理器）、CrewAI（事件总线）。

**Q: AI 判官必须联网吗？必须花钱吗？**
不必须。规则引擎离线免费覆盖大部分机械性失败模式（重复步骤、缺验证、提前终止等）；AI 判官是可选增强，支持任何 OpenAI 兼容接口（含本地 Ollama/llama.cpp），还能用 `distill` 蒸馏到本地小模型。

**Q: 录制会不会拖慢我的代理、或者泄露数据？**
录制是纯本地 JSON 写入，微秒级；数据存在你自己机器的 `~/.approximately/` 下，没有任何遥测和上传。

**Q: 上下文预算管理是什么意思？**
AI 代理的"工作记忆"（上下文窗口）有限且昂贵。塞满费钱还变笨（研究证实中部信息召回率会塌陷），砍小了又会"忘记"关键事实。approximately 把它当成有预算的资源来管理：哪些信息永不驱逐（pin）、超预算时先丢什么、丢完后 AI 还记得几分（有效召回探针量化），并且能在 CI 里防止别人悄悄改坏预算配置。

---

## Roadmap

- ✅ **v0.1** — 飞行记录仪 + MAST 归因 + 回放 + 回归守卫 + 上下文运行时
- ✅ **v0.2** — 框架适配器（LangChain/LangGraph、OpenAI Agents SDK、CrewAI）· 判官蒸馏 · 归因基准
- ✅ **v0.3** — 跨轨迹惯犯聚类 · 预算回归守卫 · 成本-召回曲线报告
- 🔜 **next** — 更多框架适配器（按需）· MAST-Data 榜单页 · 各推理栈蒸馏配方

完整设计文档见 [docs/PLAN.md](docs/PLAN.md)。

## Contributing

Issues 与 PR 欢迎走起。适合新手的：更多框架适配器、剩余 MAST 模式（FM-2.2、FM-2.4–2.6、FM-3.3）的规则检测器、可选 tokenizer 的精确 token 计数。

## Citation

```bibtex
@software{approximately2026,
  title  = {approximately: approximate memory, exact accountability for AI agents},
  year   = {2026},
  url    = {https://github.com/B1ueMu3ic4m/approximately}
}
```

失败分类体系来自 Cemri et al., *Why Do Multi-Agent LLM Systems Fail?*
([arXiv:2503.13657](https://arxiv.org/abs/2503.13657)).

## License

[MIT](LICENSE)
