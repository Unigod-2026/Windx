# 错误处理

## 业务错误

| code | 含义 |
|------|------|
| 200 | 业务成功 |
| 300001 | 参数错误 |
| 403 | 无权访问该任务 |
| 404 | 主任务不存在 |
| 500001 | 余额不足 |
| 500 | 服务端业务失败（含 Token 失效） |

注意：业务失败也可能返回 HTTP 200，**必须**使用 `success` 与 `code` 判断。

## 传输错误

- HTTP 非 2xx（502、503、504）
- 网络超时
- DNS / TLS 失败
- JSON 解码失败

传输错误应在重试与限流策略下重试，连续失败时记录 `last_error` 并延后重试，**不要**快速无限重试。

## 处理建议

| 场景 | 行为 |
|------|------|
| `success=false, code=500, message="Token失效"` | 立即停止调用并提醒管理员更新 `MOLIZHISHU_TOKEN` |
| `success=false, code=300001` | 参数错误，提示上游修正 |
| `success=false, code=500001` | 余额不足，提示管理员充值 |
| `success=false, code=403` | 该任务不属于本 Token，跳过 |
| `success=false, code=404` | 任务不存在，跳过并日志标记 |
| HTTP 502/503/504 | 重试 3 次，指数退避 |
| Timeout | 重试 2 次 |
| JSON 解码失败 | 记录原始响应，跳过本次 |

## 日志建议

每条远端调用日志至少包含：

```
source=... method=GET|POST|PUT url=https://... http_status=200 success=true|false code=200 message="..." duration=NNNms
```

`source` 必填，例如 `local-api:submit-task` / `local-api:manual-sync` / `background-sync:status` 等，便于追溯哪条路径触发了远端调用。
