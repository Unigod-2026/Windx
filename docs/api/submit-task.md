# 提交任务

## POST /task/batch/shared

提交一批监控子任务，由远端按 `platforms × prompts` 笛卡尔积拆分成多个子任务。同一 `platform` 按名称去重，实际子任务数见响应 `data.totalTask` / `data.subTaskList.length`。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| monitorKeywords | string | 否 | 品牌或监控关键词 |
| prompts | string[] | 是 | 监控问题，最多 50 个 |
| platforms | object[] | 是 | 平台列表 |
| platforms[].platform | string | 是 | `deepseek` / `doubao` / `yuanbao` / `kimi` / `qianwen` / `quark` / `baiduai` / `weibo_zhisou` / `wenxinyiyan` / `doubao_mobile` 等 |
| platforms[].mode | string | 是 | `standard` / `reasoning` / `search` / `reasoning_search` |
| platforms[].screenshot | int | 否 | `0` 不截图，`1` 截图，`2` 提及截图 |
| regionCode | string[] | 否 | 行政区代码数组，目前最多 1 个，例如 `["410000"]` |
| callbackUrl | string | 否 | 任务级回调地址；缺省时由远端使用全局配置 |

```json
{
  "monitorKeywords": "品牌或监控关键词，可选",
  "prompts": ["用户要监控的问题"],
  "platforms": [
    {"platform": "deepseek", "mode": "search", "screenshot": 1}
  ],
  "regionCode": ["410000"],
  "callbackUrl": "https://your-domain.com/webhooks/molizhishu"
}
```

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "批量任务已提交",
  "data": {
    "taskId": "ec617e1996174c129a872680fa27078e",
    "totalTask": 1,
    "status": "pending",
    "pollUrl": "/api/business/monitor/task/status/ec617e1996174c129a872680fa27078e",
    "callbackUrl": "https://your-domain.com/webhooks/molizhishu",
    "subTaskList": [
      {
        "subTaskId": "4124831",
        "prompt": "用户要监控的问题",
        "platform": "deepseek",
        "mode": "search",
        "status": "pending"
      }
    ]
  }
}
```

### 调用约定

1. `callbackUrl` 取值顺序：
   - 调用方传入的任务级 `callbackUrl`
   - 环境变量 `MOLIZHISHU_CALLBACK_URL`
   - 都不存在则请求体中**不传** `callbackUrl` 字段
2. `prompts` 长度必须 ≤ 50；超过应本地 400 拒绝。
3. 同一 `platform` 在 `platforms` 中按名字去重。
4. 提交成功必须本地落库：`taskId`、`status`、`prompts`/`platforms`/`regionCode` 原始 JSON、`totalTask`/`totalItems`、`pollUrl`、`callbackUrl`（实际生效，可能为 null）、`subTaskList` 摘要、`rawRequest`、`rawResponse`。
