// /api/molizhishu/cities 客户端 —— 后端代理 Molizhishu /city-info,
// 避免把 MOLIZHISHU_TOKEN 暴露到浏览器 (见 CLAUDE.md §Token 安全)。
//
// 设计 Step 6 「指定区域」单选用:Province = { code, name }。level 字段
// 在本代理里被拍平了 —— 详见后端实现;这里只暴露 wizard 真正用得到的
// 两个字段,后端再加字段也不会影响前端类型。

import client from "./client";

export interface Province {
  code: string;
  name: string;
}

export interface ListCitiesResult {
  items: Province[];
  // 后端在 upstream 拿不到数据时返回的提示;null 表示 OK。
  warning: string | null;
}

export const listMolizhishuCities = () =>
  client.get<ListCitiesResult>("/molizhishu/cities").then((r) => r.data);