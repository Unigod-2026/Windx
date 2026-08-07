# 概览

## Base URL

```
https://business-api.molizhishu.com/api/business/monitor
```

所有「模力指数监控」相关接口（除城市区域单独域名）都挂在这条前缀下。

## 认证

所有请求都必须携带：

```
Authorization: Bearer <token>
```

- Token 仅服务端使用。
- 通过环境变量 `MOLIZHISHU_TOKEN` 注入，不得写入代码、README、测试快照或日志。
- 缺失或失效时，远端将以 `success=false code=500 message="Token失效"` 响应，且可能不返回 `data` 字段。

## 通用响应格式

正常响应：

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {}
}
```

业务失败：

```json
{
  "success": false,
  "code": 500,
  "message": "Token失效"
}
```

注意：
- 业务失败也可能返回 HTTP 200，因此判断成功必须使用 `success` + `code`。
- 业务失败响应通常没有 `data` 字段。
- HTTP 非 2xx（网关 5xx、超时、网络断开）必须视为传输层错误，区别于业务错误。

## 超时

默认 30 秒。所有 I/O 必须带超时，禁止永久阻塞。

## 城市区域接口

城市区域接口在另一个域名前缀：

```
https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info
```

仅这一个接口换前缀，其它接口统一走 `/api/business/monitor` 前缀。

## 主任务终态

| 值 | 含义 |
|----|------|
| pending | 已创建，未开始 |
| processing | 正在执行 |
| completed | 全部完成且无失败 |
| partial_completed | 部分成功部分失败 |
| failed | 全部失败 |
| stopped | 人工停止 |

`completed` / `partial_completed` / `failed` / `stopped` 均为终态。

## 子任务状态

`pending` / `assigned` / `processing` / `completed` / `stopped` / `failed` / `error`。

## 时间

- 远端毫秒级 Unix 时间戳统一为 int，不做时区转换。
- 本地 MySQL 中 DATETIME 字段按 Asia/Shanghai（UTC+8）保存。
- Docker 容器必须显式设置 `TZ=Asia/Shanghai`，MySQL 推荐 `--default-time-zone=+08:00`。
