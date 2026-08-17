import { useEffect, useState } from "react";
import { Input, Modal, Tag, message } from "antd";
import { X } from "lucide-react";

interface AliasEditModalProps {
  open: boolean;
  title: string;
  initial: string[];
  onCancel: () => void;
  onConfirm: (aliases: string[]) => Promise<void> | void;
}

export default function AliasEditModal({
  open,
  title,
  initial,
  onCancel,
  onConfirm,
}: AliasEditModalProps) {
  const [aliases, setAliases] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (open) {
      setAliases([...initial]);
      setDraft("");
    }
  }, [open, initial]);

  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (aliases.includes(v)) {
      message.warning(`已存在别名「${v}」`);
      return;
    }
    setAliases([...aliases, v]);
    setDraft("");
  };

  const remove = (idx: number) => {
    setAliases(aliases.filter((_, i) => i !== idx));
  };

  return (
    <Modal
      open={open}
      title={title}
      okText="保存"
      cancelText="取消"
      onCancel={onCancel}
      onOk={async () => {
        await onConfirm(aliases);
      }}
      destroyOnHidden
      width={480}
    >
      <div style={{ marginBottom: 12, fontSize: 13, color: "var(--text-tertiary)" }}>
        别名会和品牌名一起用于远端 AI prompt 的关键词拼接,提升匹配召回率。
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
          marginBottom: 12,
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
                remove(i);
              }}
              closeIcon={<X size={12} />}
              style={{ margin: 0, padding: "2px 8px" }}
            >
              {a}
            </Tag>
          ))
        )}
      </div>
      <Input.Search
        placeholder="输入别名后回车或点添加"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onSearch={add}
        enterButton="添加"
        onPressEnter={(e) => {
          e.preventDefault();
          add();
        }}
      />
    </Modal>
  );
}