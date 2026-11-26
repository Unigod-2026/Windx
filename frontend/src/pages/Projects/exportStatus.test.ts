import { describe, expect, it } from "vitest";
import {
  exportStatusLabel,
  exportStatusTone,
  isExportActive,
} from "./exportStatus";

describe("exportStatusLabel", () => {
  it("把四种状态翻成中文", () => {
    expect(exportStatusLabel("pending")).toBe("排队中");
    expect(exportStatusLabel("running")).toBe("生成中");
    expect(exportStatusLabel("success")).toBe("已完成");
    expect(exportStatusLabel("failed")).toBe("生成失败");
  });

  it("未知状态兜底成生成失败", () => {
    expect(exportStatusLabel("whatever")).toBe("生成失败");
  });
});

describe("exportStatusTone", () => {
  it("进行中用蓝、完成用绿、失败用红", () => {
    expect(exportStatusTone("pending")).toBe("blue");
    expect(exportStatusTone("running")).toBe("blue");
    expect(exportStatusTone("success")).toBe("green");
    expect(exportStatusTone("failed")).toBe("red");
  });
});

describe("isExportActive", () => {
  it("只有排队中与生成中算进行中", () => {
    expect(isExportActive("pending")).toBe(true);
    expect(isExportActive("running")).toBe(true);
    expect(isExportActive("success")).toBe(false);
    expect(isExportActive("failed")).toBe(false);
  });
});
