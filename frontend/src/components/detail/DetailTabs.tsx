export type DetailTab = "checks" | "metadata";

const TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "checks", label: "검수 결과" },
  { id: "metadata", label: "출처·메타정보" },
];

interface DetailTabsProps {
  activeTab: DetailTab;
  onChange: (tab: DetailTab) => void;
  isTestTable?: boolean;
}

export function DetailTabs({ activeTab, onChange, isTestTable = false }: DetailTabsProps) {
  return (
    <nav className="detail-tabs" aria-label="상세 탭">
      {TABS.map((tab) => (
        <button
          className={activeTab === tab.id ? "is-active" : ""}
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
        >
          <span>
            {isTestTable && tab.id === "checks"
              ? "생성 상태"
              : tab.label}
          </span>
        </button>
      ))}
    </nav>
  );
}
