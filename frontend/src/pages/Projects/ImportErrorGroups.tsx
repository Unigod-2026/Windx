/**
 * 导入错误分组展示 —— 「数据导入」预览页与「导入历史」详情页共用。
 *
 * 每组：错误原因 + 影响行数 + **完整取值清单** + 一键复制 + 明细样本。
 * 清单要完整 —— 用户要照着它去项目配置里补，一条条抄 40 个名字不现实。
 */

import { Button, Space, Table, message } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import type { ImportErrorGroup } from "../../api/imports";
import { describeErrorGroup } from "./importPreview";
import "./ImportErrorGroups.css";

interface Props {
  groups: ImportErrorGroup[];
}

export default function ImportErrorGroups({ groups }: Props) {
  if (!groups.length) return null;
  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {groups.map((g) => (
        <ErrorGroupBlock key={`${g.sheet}-${g.code}`} group={g} />
      ))}
    </Space>
  );
}

function ErrorGroupBlock({ group }: { group: ImportErrorGroup }) {
  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(group.distinct.join("\n"));
      message.success(`已复制 ${group.distinct.length} 个名称`);
    } catch {
      message.error("复制失败，请手动选中下方文本");
    }
  };

  return (
    <div>
      <div className="imp-error-headline">{describeErrorGroup(group)}</div>
      {group.distinct.length > 0 && (
        <>
          <div className="imp-error-values">{group.distinct.join("、")}</div>
          <Button
            size="small"
            type="link"
            icon={<CopyOutlined />}
            onClick={copyAll}
            style={{ paddingLeft: 0 }}
          >
            复制这 {group.distinct.length} 个名称
          </Button>
        </>
      )}
      <Table
        size="small"
        rowKey="row"
        pagination={{ pageSize: 5, size: "small" }}
        style={{ marginTop: 8 }}
        dataSource={group.samples}
        columns={[
          { title: "行号", dataIndex: "row", width: 70 },
          {
            title: "内容",
            dataIndex: "context",
            render: (ctx: Record<string, string>) =>
              Object.entries(ctx)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · "),
          },
        ]}
      />
    </div>
  );
}
