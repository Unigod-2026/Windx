# 远端任务列表

## GET /task/list

列出远端账号下最近一段时间内的任务，便于迁移/排查或导入本地库。

### Query 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，从 1 开始 |
| size | int | 否 | 每页条数，默认 20 |
| status | string | 否 | 按主任务状态过滤 |

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {
    "page": 1,
    "size": 20,
    "total": 1,
    "items": [
      {
        "taskId": "ec617e1996174c129a872680fa27078e",
        "status": "completed",
        "totalItems": 1,
        "completedItems": 1,
        "failedItems": 0,
        "createdAt": 1722671000000
      }
    ]
  }
}
```

### 调用约定

1. 本地仅在「手动同步或导入远端已有任务」时使用。
2. **不**接入后台轮询循环，避免对 `/task/list` 产生周期性压力。
