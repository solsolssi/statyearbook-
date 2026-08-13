import { Download } from "lucide-react";

import type { StatTable } from "../types";
import { downloadTableCsv, downloadTableXlsx } from "../utils/tableDownload";

interface DownloadMenuProps {
  table: StatTable;
}

export function DownloadMenu({ table }: DownloadMenuProps) {
  return (
    <details className="download-menu">
      <summary className="secondary-button detail-download">
        <Download aria-hidden="true" size={16} />
        <span>다운로드</span>
      </summary>
      <div className="download-menu__options">
        <button type="button" onClick={() => downloadTableCsv(table)}>
          CSV
        </button>
        <button type="button" onClick={() => downloadTableXlsx(table)}>
          XLSX
        </button>
      </div>
    </details>
  );
}
