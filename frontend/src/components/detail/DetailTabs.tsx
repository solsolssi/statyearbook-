export type DetailTab = "checks" | "changes" | "visuals" | "metadata";

const TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "checks", label: "검수 결과" },
  { id: "changes", label: "전년도 비교" },
  { id: "visuals", label: "시각화" },
  { id: "metadata", label: "출처·메타정보" },
];

interface DetailTabsProps {
  activeTab: DetailTab;
  onChange: (tab: DetailTab) => void;
}

export function DetailTabs({ activeTab, onChange }: DetailTabsProps) {
  return (
    <nav className="detail-tabs" aria-label="상세 탭">
      {TABS.map((tab) => (
        <button
          className={activeTab === tab.id ? "is-active" : ""}
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
        >
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}

