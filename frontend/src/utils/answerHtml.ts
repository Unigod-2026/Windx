/**
 * AI 答案内容渲染工具 —— 把 LLM 返回的 Markdown + HTML 混合文本,转成带品牌
 * 高亮的 sanitized HTML 字符串。
 *
 * 抽出位置说明:
 * - 原实现内联在 [QuestionTab.tsx](frontend/src/pages/Projects/QuestionTab.tsx)
 *   的 `renderAnswerHtml` / `escapeRegex` / `HighlightGroup` 三处。
 * - 「答案质量分析」页 raw / detail sub-tab 都需要同样的高亮 + Markdown
 *   渲染,直接 import 此模块复用,避免在多个文件里维护同一份逻辑。
 *
 * 渲染管线(沿用原 QuestionTab 注释,行为完全不变):
 * 1. 按 groups 优先级(self > competitor > keyword),把 token 替换成
 *    private-use Unicode placeholder,记录 token 文本与 class
 * 2. ``marked.parse`` 把 Markdown 变 HTML;placeholder 是普通字符,不会
 *    破坏 ``**...**`` / ``##...`` 这类定界符的配对
 * 3. 把 placeholder 还原成 ``<span class="hl-...">`` 包裹
 * 4. ``DOMPurify.sanitize`` 过滤危险标签,保留 LLM 输出常见的
 *    ``<table>`` / ``<ul>`` / ``<blockquote>`` / yuanbao 的 ``<div class="media-*">``
 */

import DOMPurify from "dompurify";
import { marked } from "marked";

export interface HighlightGroup {
  /** 要高亮的 token 列表,顺序无关,正则按出现位置取首个匹配。空 / 纯空白 token
   *  提前过滤掉。 */
  tokens: string[];
  /** 包裹匹配项的 CSS class,通常为 ``hl-self`` / ``hl-competitor`` / ``hl-keyword``。 */
  cls: string;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Token placeholder:private-use Unicode 区段的一个字符,marked 当普通文本处理。
 *  在 Markdown 解析阶段用它暂存高亮 token 的位置,解析完后再换回 ``<span>`` 包裹。
 *  解析前插 ``<span>`` 会破坏 ``**token**`` 这类定界符的配对。 */
const HL_PLACEHOLDER = "";

export function renderAnswerHtml(content: string, groups: HighlightGroup[]): string {
  const usable = groups.filter((g) => g.tokens.length > 0);
  if (!content || usable.length === 0) {
    return DOMPurify.sanitize(marked.parse(content) as string);
  }
  const tokens: Array<{ token: string; cls: string }> = [];
  let pre = content;
  usable.forEach((g) => {
    const re = new RegExp(`(${g.tokens.map(escapeRegex).join("|")})`, "g");
    pre = pre.replace(re, (match) => {
      const idx = tokens.length;
      tokens.push({ token: match, cls: g.cls });
      return `${HL_PLACEHOLDER}${idx}${HL_PLACEHOLDER}`;
    });
  });
  let html = marked.parse(pre) as string;
  tokens.forEach((entry, i) => {
    const ph = `${HL_PLACEHOLDER}${i}${HL_PLACEHOLDER}`;
    html = html.split(ph).join(`<span class="${entry.cls}">${entry.token}</span>`);
  });
  return DOMPurify.sanitize(html);
}

/** 把项目的「自有品牌 + 别名 / 竞品 + 别名 / 关键词」清洗去重后,组装成
 *  HighlightGroup 数组。优先级 self > competitor > keyword,靠前的高优
 *  先匹配,后续 group 不会再覆盖前者的 ``<span>``。
 *
 *  4 色分组(详情页要求「监控品牌主 / 监控品牌别名 / 竞品主 / 竞品别名」
 *  分别上色):把 self / competitor 拆成「主名」「别名」两个 group;若
 *  品牌或竞品没有别名,合并到主名组(避免多一个空 group 浪费一次 replace)。 */
export function buildHighlightGroups(input: {
  selfBrand?: string | null;
  selfAliases?: string[] | null;
  competitors?: Array<{ name: string; aliases?: string[] | null }>;
  keywords?: string[];
}): HighlightGroup[] {
  const cleanTokens = (xs: Array<string | null | undefined>): string[] => {
    const out: string[] = [];
    const seen = new Set<string>();
    xs.forEach((x) => {
      if (!x) return;
      const t = x.trim();
      if (!t) return;
      const k = t.toLowerCase();
      if (seen.has(k)) return;
      seen.add(k);
      out.push(t);
    });
    return out;
  };
  const groups: HighlightGroup[] = [];
  // 自有品牌主名(group A:hl-self),别名(group B:hl-self-alias)
  const selfPrimary = cleanTokens([input.selfBrand ?? null]);
  if (selfPrimary.length > 0) groups.push({ tokens: selfPrimary, cls: "hl-self" });
  const selfAliasTokens = cleanTokens(input.selfAliases ?? []);
  if (selfAliasTokens.length > 0) {
    groups.push({ tokens: selfAliasTokens, cls: "hl-self-alias" });
  }
  // 竞品主名(group C:hl-competitor),别名(group D:hl-competitor-alias)
  const competitorPrimaries: string[] = [];
  const competitorAliases: string[] = [];
  input.competitors?.forEach((c) => {
    if (c.name) competitorPrimaries.push(c.name);
    (c.aliases ?? []).forEach((a) => a && competitorAliases.push(a));
  });
  const compPrimary = cleanTokens(competitorPrimaries);
  if (compPrimary.length > 0) groups.push({ tokens: compPrimary, cls: "hl-competitor" });
  const compAlias = cleanTokens(competitorAliases);
  if (compAlias.length > 0) {
    groups.push({ tokens: compAlias, cls: "hl-competitor-alias" });
  }
  const kwClean = cleanTokens(input.keywords ?? []);
  if (kwClean.length > 0) groups.push({ tokens: kwClean, cls: "hl-keyword" });
  return groups;
}
