# 查询主任务状态

## GET /task/status/{taskId}

返回主任务当前状态以及子任务摘要。**不**返回完整结果内容。

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
    "status": "processing",
    "totalItems": 1,
    "completedItems": 0,
    "failedItems": 0,
    "subTaskList": [
      {
        "subTaskId": "4124831",
        "platform": "deepseek",
        "mode": "search",
        "prompt": "用户要监控的问题",
        "status": "processing"
      }
    ]
  }
}
```

### 调用约定

1. 远端返回 `status=processing` 时，本地只更新 `geo_tasks.status` 与子任务摘要，**不**触发结果拉取。
2. 当 `completedItems > 0` 或任意子任务进入终态（`completed` / `failed` / `error` / `stopped`），本地应主动拉取 [GetTaskResult](./get-task-result.md) 以增量保存已完成子任务的 `answerContent` 等详细字段。
3. `stopped` 任务也可能带有已完成子任务，必须拉取并保存。
4. 不修改本地提交时已保存的 `prompts_json` / `platforms_json` / `region_code_json` / `callback_url` / `raw_request_json`。
