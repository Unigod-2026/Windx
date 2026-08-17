import { useEffect, useState } from "react";
import { Button, Input, Modal, Tag, message } from "antd";
import { PlusOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { X } from "lucide-react";

interface BrandEditModalProps {
  open: boolean;
  title: string;
  initialName: string;
  initialAliases: string[];
  /** Optional right-aligned action in the header next to the title. */
  headerExtra?: React.ReactNode;
  onCancel: () => void;
  onConfirm: (name: string, aliases: string[]) => Promise<void> | void;
}

export default function BrandEditModal({
  open,
  title,
  initialName,
  initialAliases,
  headerExtra,
  onCancel,
  onConfirm,
}: BrandEditModalProps) {
  const [name, setName] = useState(initialName);
  const [aliases, setAliases] = useState<string[]>([]);
  const [aliasDraft, setAliasDraft] = useState("");

  useEffect(() => {
    if (!open) return;
    setName(initialName);
    setAliases([...initialAliases]);
    setAliasDraft("");
  }, [open, initialName, initialAliases]);

  const addAlias = () => {
    const v = aliasDraft.trim();
    if (!v) return;
    if (aliases.includes(v)) {
      message.warning(`已存在别名「${v}」`);
      return;
    }
    setAliases([...aliases, v]);
    setAliasDraft("");
  };

  const removeAlias = (idx: number) => {
    setAliases(aliases.filter((_, i) => i !== idx));
  };

  return (
    <Modal
      open={open}
      title={
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>{title}</span>
          {headerExtra}
        </div>
      }
      okText="确定"
      cancelText="取消"
      onCancel={onCancel}
      onOk={async () => {
        const trimmed = name.trim();
        if (!trimmed) {
          message.warning("品牌名称不能为空");
          return;
        }
        await onConfirm(trimmed, aliases);
      }}
      destroyOnHidden
      width={520}
    >
      <div
        style={{
          marginBottom: 6,
          fontSize: 13,
          color: "var(--text-secondary)",
        }}
      >
        品牌名称<span style={{ color: "#ef4444", marginLeft: 2 }}>*</span>
      </div>
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="例如:伊速达"
        autoFocus
        style={{ marginBottom: 16 }}
      />

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
          fontSize: 13,
          color: "var(--text-secondary)",
        }}
      >
        <span>品牌别名</span>
        <Button
          type="link"
          size="small"
          icon={<ThunderboltOutlined />}
          style={{ padding: 0, fontSize: 12 }}
          onClick={() => message.info("AI 拓展预留入口")}
        >
          AI 拓展
        </Button>
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
          minHeight: 40,
          padding: "8px 10px",
          border: "1px solid var(--border-default, #d1d5db)",
          borderRadius: 6,
          background: "#fff",
          marginBottom: 8,
        }}
      >
        {aliases.length === 0 ? (
          <span style={{ color: "var(--text-quaternary)", fontSize: 13 }}>
            尚未添加别名
          </span>
        ) : (
          aliases.map((a, i) => (
            <Tag
              key={`${a}-${i}`}
              closable
              onClose={(e) => {
                e.preventDefault();
                removeAlias(i);
              }}
              closeIcon={<X size={12} />}
              style={{ margin: 0, padding: "2px 8px" }}
            >
              {a}
            </Tag>
          ))
        )}
      </div>

      <Input
        placeholder="输入品牌别名,回车添加"
        value={aliasDraft}
        onChange={(e) => setAliasDraft(e.target.value)}
        onPressEnter={(e) => {
          e.preventDefault();
          addAlias();
        }}
        suffix={
          <Button
            type="link"
            size="small"
            onClick={addAlias}
            icon={<PlusOutlined />}
            style={{ padding: 0 }}
          >
            添加
          </Button>
        }
      />
    </Modal>
  );
}