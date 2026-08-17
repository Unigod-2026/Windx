import { Card, Empty } from "antd";
import { ClockCircleOutlined } from "@ant-design/icons";

interface Props {
  title: string;
  hint?: string;
}

/**
 * 占位 tab — 后续有后端数据后再替换为真实页面。
 * 保持与详情页其他 tab 相同的 padding / 排版,避免点击后页面"塌陷"。
 */
export default function PlaceholderTab({ title, hint }: Props) {
  return (
    <Card
      bordered={false}
      styles={{ body: { padding: 0 } }}
    >
      <Empty
        image={
          <ClockCircleOutlined style={{ fontSize: 48, color: "var(--text-quaternary)" }} />
        }
        description={
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--text-secondary)" }}>
              {title}
            </div>
            {hint && (
              <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 4 }}>
                {hint}
              </div>
            )}
          </div>
        }
        style={{ padding: "48px 16px" }}
      >
        <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
          该模块正在开发中 — 待后端数据接口就绪后接入
        </div>
      </Empty>
    </Card>
  );
}
