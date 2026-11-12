/** 「编辑监控项目」弹窗的 payload 往返 + 错误文案。
 *
 *  两个回归点:
 *  1. 分类表 key 必须和问题文本一样先 trim —— 历史问题文本带首尾空格时,
 *     保存通道查不到分类 → ``category: ""`` → 后端 422 → 用户点保存没反应。
 *  2. 后端 422 的 ``detail`` 是对象数组,直接丢给 ``message.error()`` 会让
 *     React 渲染非字符串子节点抛错,toast 根本不显示 —— 必须先拍平成字符串。
 */

import { describe, expect, it } from "vitest";
import {
  apiErrorText,
  buildWizardPayloadFromForm,
  hydrateFromWizardPayload,
} from "./BatchQuestionModal";
import type { WizardPayload, WizardQuestion } from "../../api/projects";

function payloadWith(questions: WizardQuestion[]): WizardPayload {
  return {
    questions,
    brand: { name: "监控名称", product: "监控品牌", aliases: [] },
    competitors: [],
    models: ["doubao"],
    models_config: [{ code: "doubao", modes: ["fast"], screenshot: false }],
    monitor: {
      devices: ["pc"],
      modes: ["fast"],
      schedules: { fast: null, think: null },
    },
    categories: ["引流类"],
    geo: { mode: "national_random", region_code: null },
    sentiment: "on",
    semantic: {
      selling_points: [],
      website: null,
      phone: null,
      address: null,
      email: null,
      wechat_service: null,
      wechat_official: null,
      xiaohongshu: null,
      douyin: null,
      weibo: null,
      custom: null,
    },
  };
}

function roundTrip(payload: WizardPayload) {
  const hydrated = hydrateFromWizardPayload(payload);
  return buildWizardPayloadFromForm({
    questionsText: hydrated.questionsText,
    questionCategories: hydrated.questionCategories,
    categoryTaxonomy: hydrated.categoryTaxonomy,
    brand: hydrated.brand,
    brandName: hydrated.brandName,
    brandAliases: hydrated.brandAliases,
    competitors: hydrated.competitors,
    modelsConfig: hydrated.modelsConfig,
    monitor: hydrated.monitor,
    geo: hydrated.geo,
    sentiment: hydrated.sentiment,
    semantic: hydrated.semantic,
    original: payload,
  });
}

describe("wizard payload 往返", () => {
  it("保留带首尾空格的问题的分类", () => {
    const payload = payloadWith([
      { text: " 敏感肌品牌推荐 ", category: "引流类", tag: null },
    ]);
    const built = roundTrip(payload);
    expect(built.questions[0].text).toBe("敏感肌品牌推荐");
    expect(built.questions[0].category).toBe("引流类");
  });

  it("没有分类的问题原样保持空分类(未分类)", () => {
    const payload = payloadWith([
      { text: "没有分类的问题", category: "", tag: null },
    ]);
    expect(roundTrip(payload).questions[0].category).toBe("");
  });
});

describe("apiErrorText", () => {
  it("把 FastAPI 422 的 detail 数组拍平成可读文案", () => {
    const err = {
      response: {
        data: {
          detail: [
            {
              type: "string_too_short",
              loc: ["body", "payload", "questions", 0, "category"],
              msg: "String should have at least 1 character",
            },
          ],
        },
      },
    };
    expect(apiErrorText(err, "保存失败")).toBe(
      "String should have at least 1 character",
    );
  });

  it("字符串 detail 原样透出", () => {
    const err = { response: { data: { detail: "调度中的项目不能修改" } } };
    expect(apiErrorText(err, "保存失败")).toBe("调度中的项目不能修改");
  });

  it("没有 detail 时回落到 fallback", () => {
    expect(apiErrorText({}, "保存失败")).toBe("保存失败");
  });
});
