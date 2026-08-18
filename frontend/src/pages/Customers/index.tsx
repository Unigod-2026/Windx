import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import dayjs from "dayjs";
import {
  createCustomer,
  deleteCustomer,
  listCustomers,
  updateCustomer,
  uploadLogo,
  type Customer,
  type CustomerCreatePayload,
  type CustomerUpdatePayload,
} from "../../api/customers";

interface FormValues {
  name: string;
  code?: string;
  contact?: string;
  status?: "active" | "disabled";
}

const BRAND_BLUE = "var(--brand-blue)";

const logoBoxStyle: React.CSSProperties = {
  width: 36,
  height: 36,
  borderRadius: "var(--radius-md, 8px)",
  background: "#fff",
  border: "1px solid var(--border-light)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  overflow: "hidden",
  flexShrink: 0,
};

const fallbackLogoStyle: React.CSSProperties = {
  ...logoBoxStyle,
  background:
    "linear-gradient(135deg, var(--brand-blue-light), var(--brand-blue))",
  color: "#fff",
  fontWeight: 600,
};

function CustomerLogo({ customer }: { customer: Customer }) {
  if (customer.logo_url) {
    return (
      <div style={logoBoxStyle}>
        <img
          src={customer.logo_url}
          alt={customer.name}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>
    );
  }
  const letter = customer.name?.trim().charAt(0) ?? "?";
  return <div style={fallbackLogoStyle}>{letter}</div>;
}

export default function Customers() {
  const [items, setItems] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [editing, setEditing] = useState<Customer | null>(null);
  const [isCreate, setIsCreate] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async (p = page, s = pageSize) => {
    setLoading(true);
    try {
      const data = await listCustomers({ page: p, size: s });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(page, pageSize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return items;
    return items.filter(
      (c) => c.name.toLowerCase().includes(k) || (c.code || "").toLowerCase().includes(k),
    );
  }, [items, keyword]);

  const openCreate = () => {
    setIsCreate(true);
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ status: "active" });
  };

  const openEdit = (c: Customer) => {
    setIsCreate(false);
    setEditing(c);
    form.setFieldsValue({
      name: c.name,
      code: c.code,
      contact: c.contact ?? "",
      status: c.status,
    });
  };

  const closeModal = () => {
    setEditing(null);
    setIsCreate(false);
    form.resetFields();
  };

  const onSave = async () => {
    try {
      const v = await form.validateFields();
      if (isCreate) {
        const payload: CustomerCreatePayload = {
          name: v.name,
          code: v.code!,
          contact: v.contact || null,
        };
        await createCustomer(payload);
        message.success("已创建");
      } else if (editing) {
        const payload: CustomerUpdatePayload = {
          name: v.name,
          contact: v.contact || null,
          status: v.status,
        };
        await updateCustomer(editing.id, payload);
        message.success("已更新");
      }
      closeModal();
      load();
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return; // antd validation
      message.error((err as Error).message || "保存失败");
    }
  };

  const onUpload = async (id: number, file: File) => {
    try {
      await uploadLogo(id, file);
      message.success("logo 已上传");
      load();
    } catch (err) {
      message.error((err as Error).message || "上传失败");
    }
    return false;
  };

  const uploadProps = (id: number): UploadProps => ({
    beforeUpload: (file) => {
      onUpload(id, file);
      return false;
    },
    showUploadList: false,
    accept: "image/png,image/jpeg,image/webp",
  });

  const onDelete = (c: Customer) => {
    Modal.confirm({
      title: "确认停用该客户?",
      content: `客户「${c.name}」将被标记为停用,可在编辑中重新启用。`,
      okText: "确认停用",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteCustomer(c.id);
          message.success("已停用");
          load();
        } catch (err) {
          message.error((err as Error).message || "操作失败");
        }
      },
    });
  };

  const columns: ColumnsType<Customer> = [
    {
      title: "Logo",
      key: "logo",
      width: 80,
      render: (_, record) => <CustomerLogo customer={record} />,
    },
    {
      title: "客户名称",
      dataIndex: "name",
      render: (name: string, record) => (
        <div>
          <div
            style={{
              color: BRAND_BLUE,
              fontWeight: 500,
              cursor: "pointer",
              lineHeight: 1.4,
            }}
          >
            {name}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
            编号 {record.code}
          </div>
        </div>
      ),
    },
    {
      title: "编码",
      dataIndex: "code",
      width: 140,
      render: (v: string) => <span style={{ color: "var(--text-secondary)" }}>{v}</span>,
    },
    {
      title: "联系人",
      dataIndex: "contact",
      render: (v: string | null) =>
        v ? <span>{v}</span> : <span style={{ color: "var(--text-quaternary)" }}>—</span>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: "active" | "disabled") =>
        s === "active" ? (
          <Tag color="success">启用</Tag>
        ) : (
          <Tag>停用</Tag>
        ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => (
        <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
          {dayjs(v).format("YYYY-MM-DD HH:mm")}
        </span>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 240,
      render: (_, record) => (
        <Space size="small">
          <Upload {...uploadProps(record.id)}>
            <Button size="small" icon={<UploadOutlined />}>
              上传 logo
            </Button>
          </Upload>
          <Button size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button size="small" danger onClick={() => onDelete(record)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>
            客户管理
          </h1>
          <div style={{ fontSize: 13, color: "var(--text-tertiary)", marginTop: 4 }}>
            管理所有客户实体 · 上传客户 logo · 查看旗下项目
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建客户
        </Button>
      </div>

      <Card bordered={false} styles={{ body: { padding: 16 } }}>
        <div style={{ marginBottom: 12 }}>
          <Input.Search
            placeholder="搜索客户名 / 编码"
            allowClear
            style={{ maxWidth: 320 }}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(v) => setKeyword(v)}
          />
        </div>
        <Table<Customer>
          rowKey="id"
          loading={loading}
          dataSource={filtered}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 个客户`,
            onChange: (p) => setPage(p),
          }}
        />
      </Card>

      <Modal
        open={isCreate || !!editing}
        title={isCreate ? "新建客户" : "编辑客户"}
        okText="保存"
        cancelText="取消"
        onCancel={closeModal}
        onOk={onSave}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="客户名称"
            rules={[{ required: true, message: "请输入客户名称" }]}
          >
            <Input placeholder="例如:ACME 集团" />
          </Form.Item>
          {isCreate && (
            <Form.Item
              name="code"
              label="客户编码"
              rules={[
                { required: true, message: "请输入客户编码" },
                { max: 64, message: "最多 64 个字符" },
              ]}
            >
              <Input placeholder="唯一编码,例如 CUS-0001" />
            </Form.Item>
          )}
          <Form.Item name="contact" label="联系人">
            <Input placeholder="选填" />
          </Form.Item>
          {!isCreate && (
            <Form.Item name="status" label="状态">
              <Select
                options={[
                  { value: "active", label: "启用" },
                  { value: "disabled", label: "停用" },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
