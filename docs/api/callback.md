# Callback 推送（远端 → 我方）

模力指数服务端主动推送至我方 `POST /webhooks/molizhishu`，用于加速数据回写。**不是**唯一数据来源，轮询补偿是最终一致性保障。

## 推送时机

- 当主任务状态变更时推送一次（包括中间态 processing → 终态）。
- 同一个 taskId 可能收到多次推送。
- 偶发网络问题或超时重试也会引发重发。

## Payload 结构

```json
{
  "taskId": "ec617e1996174c129a872680fa27078e",
  "userId": "u-001",
  "timestamp": 1722672000000,
  "status": "completed",
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
      "answerContent": "## 标题\n回答内容...",
      "referenceList": [{"index": 1, "title": "...", "url": "...", "site": "...", "icon": null}],
      "citationList": [],
      "reasoningProcess": null,
      "recommendedQuestions": [],
      "mediaContent": [],
      "errorMessage": null,
      "proxyIp": "1.2.3.4"
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| taskId | 是 | 主任务 ID |
| userId | 否 | 发起用户，可能为空或缺失 |
| timestamp | 否 | 回调触发时间，毫秒级 Unix 时间戳 |
| status | 是 | 主任务状态 |
| totalItems | 否 | 总子任务数 |
| completedItems | 否 | 完成数 |
| failedItems | 否 | 失败数 |
| subTaskList | 否 | 子任务结果列表 |

`status` 取值见 overview.md。

## 接收端要求（`POST /webhooks/molizhishu`）

1. 限制请求体大小（默认 4 MB，可调）。
2. 校验 JSON 格式，失败返回 400。
3. 校验 `taskId` 和 `status`，缺失返回 422。
4. 计算 `payload_hash = sha256(canonical_json(payload))`，基于 `(task_id, payload_hash)` 做幂等。
5. **upsert** 主任务与子任务，**不**因重复推送抛错。
6. 子任务结果字段必须尽量完整保存，包括 `referenceList` / `citationList` / `reasoningProcess` / `recommendedQuestions` / `mediaContent` / `pageScreenshot` / `errorMessage` / `proxyIp`。
7. 数据落库成功后才返回 2xx；下游业务请异步执行，不在回调路径里阻塞。
8. 失败返回非 2xx 以触发远端重试。

## 安全

- 默认文档未要求签名校验。
- 收到 HMAC-SHA256、AES 加密、第三方平台转发的需求时，请联系模力指数对接人员开通自定义回调。
- receiver 不能信任 `userId` 字段用于鉴权，仅作为元数据落库。
