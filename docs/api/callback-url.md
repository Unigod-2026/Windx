# 全局回调地址

## GET /task/callback-url

查询远端维护的全局回调地址。当任务提交时未传入任务级 `callbackUrl`，远端会按该全局地址推送。

### 响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {
    "callbackUrl": "https://your-domain.com/webhooks/molizhishu"
  }
}
```
或未设置时：
```json
{"success": true, "code": 200, "message": "操作成功", "data": {"callbackUrl": null}}
```

## PUT /task/callback-url

更新远端全局回调地址。

### 请求体

```json
{"callbackUrl": "https://your-domain.com/webhooks/molizhishu"}
```
或清空：
```json
{"callbackUrl": null}
```

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {"callbackUrl": "https://your-domain.com/webhooks/molizhishu"}
}
```

### 注意事项

1. 生产环境回调地址必须使用 HTTPS。
2. 修改全局地址不会回溯已提交任务的回调推送行为。
3. 修改后立即对新提交的任务生效。
4. 本地 PUT 接口同步远端成功后，本地不再缓存地址，永远以「环境变量 → 远端 → 任务级」三级覆盖为准。
