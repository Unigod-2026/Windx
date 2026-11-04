import { describe, expect, it } from "vitest";
import type { ImportErrorGroup, ImportTotals, SheetPreview } from "../../api/imports";
import {
  apiErrorText,
  batchStatusLabel,
  batchStatusTone,
  describeErrorGroup,
  describeTotals,
  sheetTone,
  toneLabel,
} from "./importPreview";

const sheet = (over: Partial<SheetPreview> = {}): SheetPreview => ({
  key: "answers",
  title: "问题问答",
  total_rows: 10,
  importable_rows: 10,
  blocked_rows: 0,
  subtasks: 3,
  selected: true,
  sample: [],
  ...over,
});

const group = (over: Partial<ImportErrorGroup> = {}): ImportErrorGroup => ({
  sheet: "竞品分析",
  code: "competitor_unregistered",
  message: "该品牌不在当前项目的竞品列表里，请先在「竞品信息」Tab 添加",
  row_count: 2190,
  distinct: ["概念词甲", "概念词乙"],
  samples: [],
  ...over,
});

describe("sheetTone", () => {
  it("有阻断行时标 error", () => {
    const errors = [group()];
    expect(sheetTone(sheet({ title: "竞品分析" }), errors)).toBe("error");
  });

  it("全部通过时标 ok", () => {
    expect(sheetTone(sheet(), [])).toBe("ok");
  });

  it("没有数据时标 warn", () => {
    expect(sheetTone(sheet({ total_rows: 0 }), [])).toBe("warn");
  });
});

describe("toneLabel", () => {
  it("三种语气各有中文标签", () => {
    expect(toneLabel("ok")).toBe("通过");
    expect(toneLabel("warn")).toBe("无数据");
    expect(toneLabel("error")).toBe("有阻断");
  });
});

describe("describeErrorGroup", () => {
  it("带上行数与不同取值数量", () => {
    const text = describeErrorGroup(group());
    expect(text).toContain("2190");
    expect(text).toContain("2");
    expect(text).toContain("竞品");
  });

  it("没有不同取值时只说行数", () => {
    const text = describeErrorGroup(group({ distinct: [] }));
    expect(text).toContain("2190");
    expect(text).not.toContain("不同取值");
  });
});

describe("describeTotals", () => {
  it("汇总三个数字", () => {
    const totals: ImportTotals = {
      total_rows: 9936,
      importable_rows: 7746,
      blocked_rows: 2190,
      tasks: 5,
      subtasks: 360,
      brand_mentions: 2880,
      citations: 4506,
    };
    expect(describeTotals(totals)).toContain("9936");
    expect(describeTotals(totals)).toContain("7746");
    expect(describeTotals(totals)).toContain("2190");
  });
});

describe("apiErrorText", () => {
  it("优先取后端 detail 里的可操作文案", () => {
    const err = {
      message: "Request failed with status code 400",
      response: { data: { detail: "请到项目「编辑」里的『监控模型』补充" } },
    };
    expect(apiErrorText(err)).toBe("请到项目「编辑」里的『监控模型』补充");
  });

  it("后端没给 detail 时丢掉 axios 的废话，用兜底文案", () => {
    const err = { message: "Request failed with status code 500" };
    expect(apiErrorText(err, "解析失败")).toBe("解析失败");
  });

  it("非 http 错误保留原始 message", () => {
    expect(apiErrorText(new Error("Network Error"))).toBe("Network Error");
  });

  it("422 的对象数组也能转成人话", () => {
    const err = { response: { data: { detail: [{ msg: "field required" }] } } };
    expect(apiErrorText(err)).toContain("field required");
  });
});


describe("batchStatusLabel", () => {
  it("三种状态各有中文标签", () => {
    expect(batchStatusLabel("success")).toBe("成功");
    expect(batchStatusLabel("partial")).toBe("部分成功");
    expect(batchStatusLabel("failed")).toBe("失败");
  });

  it("未知状态兜底成「失败」", () => {
    expect(batchStatusLabel("weird" as never)).toBe("失败");
  });
});

describe("batchStatusTone", () => {
  it("success 绿 / partial 橙 / failed 红", () => {
    expect(batchStatusTone("success")).toBe("green");
    expect(batchStatusTone("partial")).toBe("orange");
    expect(batchStatusTone("failed")).toBe("red");
  });
});
