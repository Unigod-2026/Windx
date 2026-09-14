import { Empty } from "antd";

interface Props {
  /** 副标题 —— 一般填 tab 名,如「信源明细」。 */
  label: string;
  /** 二级提示文案,默认「即将上线」。 */
  hint?: string;
}

/**
 * 「敬请期待」占位 —— 信源偏好 tab 4 个新增 sub-tab
 * (信源明细 / 自有文章 / 网站分类 / 视频类信源) 的占位实现,
 * 后期会按参考页 docs/风球GEO监控平台UI/index.html 替换成实际视图。
 */
export default function Placeholder({ label, hint = "即将上线" }: Props) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "80px 24px",
        background: "#fff",
        border: "1px solid var(--border-light, #f0f0f0)",
        borderRadius: 8,
      }}
    >
      <Empty description={null} />
      <div style={{ fontSize: 15, color: "var(--text-secondary)", marginTop: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 4 }}>
        {hint}
      </div>
    </div>
  );
}
