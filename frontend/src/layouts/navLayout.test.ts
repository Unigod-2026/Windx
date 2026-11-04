import { describe, expect, it } from "vitest";
import { PROJECT_GROUP_LAYOUT, groupTitleOf } from "./navLayout";

describe("侧边栏项目分组", () => {
  it("「数据导入」挂在「数据中心」组下", () => {
    const group = PROJECT_GROUP_LAYOUT.find((g) => g.title === "数据中心");
    expect(group?.keys).toContain("import");
  });

  it("「导入历史」挂在「数据中心」组下", () => {
    const group = PROJECT_GROUP_LAYOUT.find((g) => g.title === "数据中心");
    expect(group?.keys).toContain("import-history");
  });

  it("「数据导入」与「导入历史」是两项", () => {
    const group = PROJECT_GROUP_LAYOUT.find((g) => g.title === "数据中心");
    expect(group?.keys).toContain("import");
    expect(group?.keys).toContain("import-history");
  });

  it("每个 tab 只属于一个分组", () => {
    const all = PROJECT_GROUP_LAYOUT.flatMap((g) => g.keys);
    expect(new Set(all).size).toBe(all.length);
  });

  it("groupTitleOf 能查到分组名", () => {
    expect(groupTitleOf("import")).toBe("数据中心");
    expect(groupTitleOf("overview")).toBe("数据洞察");
  });
});
