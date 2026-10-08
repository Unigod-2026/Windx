/**
 * 差异化分析 tab 的 1 个指标区(整体提及率 / Top1 / Top3 之一)。
 *
 * 区头部:指标标题 + 描述 + 「M/N 个品牌」计数 + 「展开本区 / 收起本区」按钮。
 * 区主体:卡片网格(auto-fill,minmax 430px,窄屏 360px),每张卡是单品牌。
 *
 * 本身不维护显隐状态 —— 由父 DiffPane 统一通过 props 传入 isCardOpen / onOpenCard /
 * onCloseCard / onExpandAll / onCollapseAll,这样 3 个 zone 共享同一份
 * panels set,「全部展开 / 全部收起」是跨区动作。
 */

import type { DiffBrandCard, DiffBrandOut } from "../../../api/projects";
import DiffCard from "./DiffCard";

interface Props {
  metric: DiffBrandOut["metrics"][number];
  /** 当前 metric 下的所有 card(已按 brand 顺序:self 在前,竞品按 is_mention 倒序) */
  brandCards: DiffBrandCard[];
  /** 同 metric 下的自身卡 —— 给非自身卡的「vs 自身」列 / 头部「领先/落后自身」胶囊用 */
  selfCard: DiffBrandCard | null;
  /** 给定 card 是否展开 */
  isCardOpen: (card: DiffBrandCard) => boolean;
  onOpenCard: (card: DiffBrandCard) => void;
  onCloseCard: (card: DiffBrandCard) => void;
  /** 整区展开 / 收起(本 metric 下所有 brand 一起切) */
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

export default function DiffZone({
  metric,
  brandCards,
  selfCard,
  isCardOpen,
  onOpenCard,
  onCloseCard,
  onExpandAll,
  onCollapseAll,
}: Props) {
  const openCount = brandCards.filter((c) => isCardOpen(c)).length;
  return (
    <section className="diff-zone">
      <header className="diff-zone-head">
        <div className="diff-zone-title">
          <h3>{metric.name}</h3>
          <p>{metric.desc}</p>
        </div>
        <div className="diff-zone-tools">
          <span className="diff-zone-count">
            {openCount}/{brandCards.length} 个品牌
          </span>
          <button type="button" className="diff-tb-btn" onClick={onExpandAll}>
            展开本区
          </button>
          <button type="button" className="diff-tb-btn" onClick={onCollapseAll}>
            收起本区
          </button>
        </div>
      </header>
      <div className="diff-zone-body">
        {brandCards.map((card) => (
          <DiffCard
            key={`${card.metric}::${card.brand_canonical}`}
            card={card}
            // 自身卡不与自身比较 → selfCard 传 null
            selfCard={card.is_self ? null : selfCard}
            isOpen={isCardOpen(card)}
            onClose={() => onCloseCard(card)}
            onOpen={() => onOpenCard(card)}
          />
        ))}
      </div>
    </section>
  );
}
