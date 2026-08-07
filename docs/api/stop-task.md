# 停止任务

## PUT /task/stop/{taskId}

通知远端停止指定主任务下所有未执行的子任务，已产出的子任务结果仍然有效，**必须**继续拉取并保存。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| taskId | string | 主任务 ID |

### 请求体

不需要请求体，路径参数即标识。

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {
    "taskId": "ec617e1996174c129a872680fa27078e",
    "status": "stopped"
  }
}
```

### 调用约定

1. `stopped` 是合法终态。停止后仍然要拉取 `GetTaskResult` 以保存已产出子任务。
2. 同一 taskId 短时间内可能并发触发 `StopTask`，本地按 `StopResult` 的成功响应幂等处理。
3. 远端返回 `success=false` 时（例如 `code=403` 无权访问、 `code=404` 不存在），保留错误码抛出。
