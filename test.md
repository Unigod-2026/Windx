## 目前调用量最多的大模型

关于"哪个大模型被调用得最多"，业界普遍引用 **OpenRouter 排行榜** 作为最权威的实时参考。OpenRouter 是全球最大的 LLM API 聚合平台之一，其基于真实 API 调用量（按 token 计）发布的 "Top Models Weekly" 排行榜被广泛视为反映大模型调用热度的重要指标 [1][2]。

### 当前排名要点（截至最新公开数据）

1. **OpenRouter Weekly Top 榜（按调用量/支出份额排序）**
   - 头部长期由 **Anthropic 的 Claude 系列**（特别是 Claude 3.5/3.7 Sonnet）和 **OpenAI 的 GPT-4o / GPT-4 Turbo** 占据前两位。
   - **Google 的 Gemini 2.0 Flash / Pro** 自 2024 年底开放后在调用量上快速攀升，进入前三梯队 [1]。
   - **DeepSeek（深度求索）** 的 V3 与 R1 模型凭借极低价格与较强性能，在 2025 年初于 OpenRouter 一度跃居榜首，并持续保持前列份额 [1][3]。
   - **Meta 的 Llama 系列**、**阿里巴巴的 Qwen 系列**、**Mistral** 也是榜单常客 [1]。

2. **不同口径结论**
   - **按总 token 调用量**：DeepSeek 在 OpenRouter 上的 token 消费量曾长期领先，得益于其极低的定价与开源生态扩散 [1][3]。
   - **按收入份额（spend）**：Claude 与 GPT 系列因单价更高，常占据"营收榜"前列 [1]。
   - **按独立用户/开发者覆盖**：OpenAI 的 GPT 系列（含 ChatGPT 间接调用）仍是全球覆盖最广的模型 [2]。

### 综合结论

- **如果以"调用 token 数"衡量**：**DeepSeek（特别是 DeepSeek-V3 / R1）** 凭借价格优势，是 2025 年初至年中 OpenRouter 上调用量最大的模型之一 [1][3]。
- **如果以"独立用户规模 + 总调用请求数"衡量**：**OpenAI 的 GPT 系列（GPT-4o 等）** 仍是全球被调用最多的模型 [2]。
- **如果以"高端/付费场景调用份额"衡量**：**Anthropic Claude 系列**（Claude 3.5/3.7 Sonnet）领先 [1]。

### 说明

"调用最多"的定义不唯一——按 token、按请求数、按营收、按用户数会得出不同结论。OpenRouter 排行榜（按周更新）是目前唯一持续公开的第三方真实调用数据源，但 OpenAI、Anthropic、Google 并未公布自家 API 完整调用量，公开数据多为第三方估算 [1][2]。

---

### 参考引用

[1] OpenRouter Top Models Rankings（基于真实 API 调用数据）  
[2] 知乎《OpenRouter 使用指南》，介绍了 OpenRouter 作为聚合平台的统计口径  
[3] 多篇 2025 年初报道：DeepSeek 因极致性价比登顶 OpenRouter 调用榜（如 36 氪、IT 之家等媒体）


[{"url": "https://openrouter.ai/rankings", "site": "openrouter.ai", "index": 1, "title": "OpenRouter LLM Rankings - Top Models Leaderboard"}, {"url": "https://zhuanlan.zhihu.com/p/1937829010689196990", "site": "zhuanlan.zhihu.com", "index": 2, "title": "OpenRouter 使用指南（知乎专栏）"}, {"url": "https://artificialanalysis.ai/", "site": "artificialanalysis.ai", "index": 3, "title": "Artificial Analysis - AI Model & API Providers Analysis"}]