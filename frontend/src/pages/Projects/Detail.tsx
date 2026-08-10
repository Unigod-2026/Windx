import { Card, Empty, Descriptions } from "antd";
import { useParams } from "react-router-dom";

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();

  return (
    <Card
      title={`项目详情 #${id ?? ""}`}
      bordered={false}
      extra={
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="项目 ID">{id}</Descriptions.Item>
        </Descriptions>
      }
    >
      <Empty description="Page TBD — Task 14 will fill this in" />
    </Card>
  );
}
