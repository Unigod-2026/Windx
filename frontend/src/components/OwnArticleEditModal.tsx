/**
 * 自有文章引用分析 —— 编辑单条 modal。
 *
 * 故意只暴露可编辑两列(发布日期 / 分发渠道);URL / 标题作为声明项不应
 * 被后期手改篡改,错了应该删了重新声明。``remind`` 不在表单里 —— 旧 toggle
 * 端点已删,字段保留在 DB 是给历史行兜底。
 */

import {
  Alert,
  DatePicker,
  Form,
  Input,
  Modal,
  message,
} from "antd";
import dayjs, { Dayjs } from "dayjs";
import {
  updateOwnArticle,
  type OwnArticleOut,
} from "../api/projects";

interface Props {
  projectId: number;
  article: OwnArticleOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

interface FormValues {
  publish_date: Dayjs | null;
  channel: string;
}

export default function OwnArticleEditModal({
  projectId,
  article,
  open,
  onClose,
  onSaved,
}: Props) {
  const [form] = Form.useForm<FormValues>();

  const handleOk = async () => {
    if (!article) return;
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // antd 已经在字段下面标红
    }
    const publish_date = values.publish_date
      ? values.publish_date.format("YYYY-MM-DD")
      : null;
    try {
      await updateOwnArticle(projectId, article.id, {
        publish_date,
        channel: values.channel.trim(),
      });
      message.success("已保存");
      onSaved();
      onClose();
    } catch (err) {
      const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
      message.error(
        (typeof e?.response?.data?.detail === "string" && e.response.data.detail) ||
          e?.message ||
          "保存失败",
      );
    }
  };

  return (
    <Modal
      open={open}
      title={article ? `编辑自有文章` : ""}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
      onCancel={onClose}
      onOk={handleOk}
      maskClosable={false}
    >
      {article && (
        <>
          <Form
            form={form}
            layout="vertical"
            preserve={false}
            initialValues={{
              publish_date: article.publish_date ? dayjs(article.publish_date) : null,
              channel: article.channel,
            }}
          >
            <Form.Item label="URL">
              <Input
                value={article.url}
                readOnly
                disabled
                aria-readonly
              />
            </Form.Item>
            <Form.Item label="标题">
              <Input
                value={article.title || "—"}
                readOnly
                disabled
                aria-readonly
              />
            </Form.Item>
            <Form.Item
              label="发布日期"
              name="publish_date"
              extra="可清空,留空表示不记录日期。"
            >
              <DatePicker
                style={{ width: "100%" }}
                format="YYYY-MM-DD"
                allowClear
              />
            </Form.Item>
            <Form.Item
              label="分发渠道"
              name="channel"
              rules={[
                { required: true, message: "分发渠道不能为空" },
                { max: 64, message: "不超过 64 字" },
              ]}
            >
              <Input
                placeholder="如:微信公众号 / 知乎 / 小红书"
                maxLength={64}
                showCount
              />
            </Form.Item>
          </Form>
          <Alert
            type="info"
            showIcon
            message="URL 与标题为声明项,不可在此修改;若数据有误请删除后重新导入。"
            style={{ marginTop: 8 }}
          />
        </>
      )}
    </Modal>
  );
}