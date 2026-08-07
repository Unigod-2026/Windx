# 可用城市区域

## GET https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info

注意这个接口的 Base URL 与其它接口不同，挂在 `eip-edge` 域下：

```
https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info
```

仍然走 `Authorization: Bearer ***` 与统一响应格式。

### 成功响应

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": [
    {"code": "410000", "name": "河南省", "level": "province"},
    {"code": "410100", "name": "郑州市", "level": "city", "parentCode": "410000"}
  ]
}
```

### 调用约定

1. `regionCode` 数组目前最多 1 个元素。
2. 该接口用于前端提交任务时下拉选择城市，未选择时可不传 `regionCode`。
