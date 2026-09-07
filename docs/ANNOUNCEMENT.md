# 宣传文案 / Announcement Copy

## X 主帖（中文）

你的 AI 员工在上班时间干了什么，你其实一无所知。

它自己搜资料、自己点按钮、自己执行几十步任务——直到有一天搞砸了，你只知道"失败了"，不知道错在哪一步、以后还会不会犯。

我们做了个开源工具：approximately（近似 / 大概其）

📼 像行车记录仪：AI 代理干的每一步，全程录下来
🔍 出了错，自动告诉你是第几步、犯了哪种错（分类体系来自 1600+ 条失败案例的学术研究，一共 14 种）
🔁 一键重放：不用重新花钱跑任务，就能验证修没修好
🧪 自动生成测试：同样的错，第二次出现直接报警
📉 还能算出 AI 的"记忆窗口"开多大最划算——大了费钱，小了它开始忘事

一句话总结：让 AI 代理的记忆是近似的，但问责是精确的。

完全开源，免费，装上就能用（30 秒看懂）：
https://github.com/B1ueMu3ic4m/approximately

#开源 #AIAgent #AI编程 #LLM #开发者工具

---

## X 主帖（English）

Your AI agent runs 40-step tasks on its own. When it fails, do you know
WHICH step broke — or will it happen again next week?

Neither did we. So we built approximately (open source):

📼 A dashcam for agents — every tool call, recorded
🔍 Auto-postmortem: "failed at step #2, mode: Step Repetition" (14 failure
   modes, from a 1,600-trace academic study)
🔁 Replay to verify the fix — without re-running the whole task
🧪 Failed runs become regression tests automatically
📉 And it tells you how big your agent's context window should actually be

Approximate memory. Exact accountability.

Free, MIT, pip install approximately — 30s demo:
https://github.com/B1ueMu3ic4m/approximately

#OpenSource #AIAgents #LLM #DevTools

---

## 短版（转评/二次传播用）

AI 代理搞砸了不知道错哪步？这个开源工具给它装了行车记录仪：
自动归因（错在第几步+哪种错）→ 一键重放验证 → 自动生成防复发测试。
免费开源，30 秒上手 👇
https://github.com/B1ueMu3ic4m/approximately

## 回复楼（跟帖补充技术细节用）

技术底细：失败分类对齐 MAST 分类学（arXiv:2503.13657，14 种失败模式，
人工标注一致性 κ=0.88）；归因零依赖、可离线、确定性；AI 判官可选，支持
本地模型蒸馏；上下文预算管理内置"有效召回探针"。122 个测试全绿，MIT。
