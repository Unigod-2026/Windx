/**
 * 报告生成弹窗内的"模型 / 问题"多选控件。
 *
 * 关键设计(spec §2.2):**与 GlobalToolbar 解耦** —— 弹窗打开瞬间把
 * toolbar 当前值复制到这里,关闭弹窗丢弃本地 state,**不写回 toolbar**。
 * 这样:
 * - 用户可以临时在弹窗里裁剪 / 扩大筛选,不影响全局数据 tab
 * - 关闭再打开,弹窗总是显示 toolbar 当前最新状态
 *
 * ``value`` / ``onChange`` 是可选的:antd Form 会自动注入它们(本组件
 * 放在 ``<Form.Item>`` 里时),其他场景也能独立传。Task 9 走 Form 路径。
 */

import { Select } from "antd";
import type { ProjectPlatform, PromptOut } from "../../api/projects";

interface Props {
  kind: "models" | "prompts";
  /** antd Form injects this; the union includes ``null`` because the
   *  Form holds ``null`` as the "no filter" sentinel and we propagate
   *  that back out via ``onChange``. */
  value?: string[] | number[] | null;
  onChange?: (next: string[] | number[] | null) => void;
  platforms: ProjectPlatform[];
  prompts: PromptOut[];
}

export default function ReportPreviewScope({
  kind,
  value,
  onChange,
  platforms,
  prompts,
}: Props) {
  if (kind === "models") {
    const options = platforms.map((p) => ({
      value: p.platform_code,
      label: `${p.platform_code}`,
    }));
    const v = Array.isArray(value) ? (value as string[]) : undefined;
    return (
      <Select<string[]>
        mode="multiple"
        allowClear
        placeholder="默认全部模型"
        value={v}
        options={options}
        onChange={(next) =>
          onChange?.(next && next.length > 0 ? next : null)
        }
        style={{ width: "100%" }}
      />
    );
  }
  // prompts
  const options = prompts
    .filter((p) => p.status !== "archived")
    .map((p) => ({ value: p.id, label: p.prompt }));
  const v = Array.isArray(value) ? (value as number[]) : undefined;
  return (
    <Select<number[]>
      mode="multiple"
      allowClear
      placeholder="默认全部问题"
      value={v}
      options={options}
      onChange={(next) =>
        onChange?.(next && next.length > 0 ? next : null)
      }
      style={{ width: "100%" }}
    />
  );
}
