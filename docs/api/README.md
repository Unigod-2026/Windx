# 模力指数监控 API 文档目录

本文档是「模力指数监控 API」在我方接入侧的权威描述。所有路径、字段、状态值、错误码及行为约束均以本文档为准，代码实现必须与本文档保持一致。

| 文件 | 说明 |
|------|------|
| [overview.md](./overview.md) | Base URL、认证、响应格式、通用约定 |
| [submit-task.md](./submit-task.md) | 提交监控任务 /task/batch/shared |
| [get-task-status.md](./get-task-status.md) | 查询主任务状态 /task/status/{taskId} |
| [get-task-result.md](./get-task-result.md) | 查询完整结果 /task/result/{taskId} |
| [stop-task.md](./stop-task.md) | 停止任务 /task/stop/{taskId} |
| [callback-url.md](./callback-url.md) | 全局回调地址 /task/callback-url |
| [task-list.md](./task-list.md) | 远端任务列表 /task/list |
| [city-info.md](./city-info.md) | 可用城市区域 /eip-edge/ports/city-info |
| [callback.md](./callback.md) | 模力指数主动推送的 payload 结构 |
| [errors.md](./errors.md) | 业务错误码与异常处理 |
