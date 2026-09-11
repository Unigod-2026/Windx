import { useEffect, useState } from "react";
import { Button, Input, Modal, message } from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";

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
    const v = aliasDraft.trim().replace(/[,，]$/, "");
    if (!v) return;
    if (aliases.includes(v)) {
      setAliasDraft("");
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
          alignItems: "center",
          gap: 4,
          minHeight: 32,
          padding: "4px 8px",
          border: "1px solid var(--border-default, #d1d5db)",
          borderRadius: 6,
          background: "#fff",
        }}
      >
        {aliases.length === 0 && aliasDraft === "" && (
          <span style={{ color: "var(--text-quaternary)", fontSize: 13 }}>
            尚未添加别名
          </span>
        )}
        {aliases.map((a, i) => (
          <span
            key={`${a}-${i}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              background: "#eff6ff",
              color: "var(--brand-blue)",
              border: "1px solid #bfdbfe",
              borderRadius: 4,
              padding: "1px 6px",
              fontSize: 13,
              lineHeight: "20px",
            }}
          >
            {a}
            <button
              type="button"
              aria-label={`删除 ${a}`}
              onClick={() => removeAlias(i)}
              style={{
                background: "none",
                border: 0,
                color: "var(--brand-blue)",
                fontSize: 13,
                lineHeight: 1,
                cursor: "pointer",
                padding: 0,
              }}
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          placeholder={aliases.length === 0 ? "输入品牌别名,回车添加" : ""}
          value={aliasDraft}
          onChange={(e) => setAliasDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addAlias();
            }
          }}
          style={{
            border: 0,
            outline: "none",
            fontSize: 13,
            flex: 1,
            minWidth: 100,
            background: "transparent",
            padding: "2px 4px",
          }}
        />
      </div>
    </Modal>
  );
}