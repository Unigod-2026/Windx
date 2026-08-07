# 查询完整结果

## GET /task/result/{taskId}

返回全部子任务的完整结果，包含 `answerContent`、`referenceList`、`citationList`、`reasoningProcess`、`recommendedQuestions`、`mediaContent`、`pageScreenshot`、`errorMessage`、`proxyIp` 等。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| taskId | string | 主任务 ID |

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {
    "taskId": "ec617e1996174c129a872680fa27078e",
    "status": "partial_completed",
    "totalItems": 1,
    "completedItems": 1,
    "failedItems": 0,
    "subTaskList": [
      {
        "subTaskId": "4124831",
        "platform": "deepseek",
        "mode": "search",
        "prompt": "用户要监控的问题",
        "status": "completed",
        "time": 1722672000000,
        "pageScreenshot": "https://cdn.example.com/screenshot.png",
        "answerContent": "## 标题\n回答 Markdown...",
        "referenceList": [
          {"index": 1, "title": "示例", "url": "https://example.com", "site": "example.com", "icon": null}
        ],
        "citationList": [],
        "reasoningProcess": {"summary": "思考摘要", "content": "详细推理文本"},
        "recommendedQuestions": ["相关追问 1", "相关追问 2"],
        "mediaContent": [],
        "errorMessage": null,
        "proxyIp": "1.2.3.4"
      }
    ]
  }
}
```

### 子任务字段

| 字段 | 说明 |
|------|------|
| subTaskId | 子任务 ID |
| platform | 平台 |
| mode | 模式 |
| prompt | 原始问题 |
| status | pending / assigned / processing / completed / stopped / failed / error |
| time | 毫秒级 Unix 时间戳 |
| pageScreenshot | 截图 URL，可能为 URL / 空字符串 / null / 字段缺失 |
| answerContent | AI 回答（Markdown 可能混 HTML），不要在后端清洗 |
| referenceList | 引用来源数组 |
| citationList | 实际引用数组 |
| reasoningProcess | 推理过程对象，常见字段 summary、content，可能为 null |
| recommendedQuestions | 推荐追问数组 |
| mediaContent | 媒体内容数组 |
| errorMessage | 失败原因，成功通常为 null |
| proxyIp | 节点 IP |

`referenceList` / `citationList` 单项：

```json
{"index": 1, "title": "...", "url": "...", "site": "...", "icon": null}
```
`icon` 可能为 null 或相对路径。

### 调用约定

1. **必须**保存每个子任务的 `rawResult` JSON，不丢字段。
2. 不要用本地提交时的 `rawRequest` 覆盖子任务结果。
3. 保存成功后回写 `geo_tasks.completed_at`（若终态）。
