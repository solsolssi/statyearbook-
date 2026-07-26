import { useEffect, useState } from "react";

import { fetchValidationCatalog } from "../api/reportApi";
import type { ValidationCatalogItem } from "../types";
import { VALIDATION_CHECK_TYPES } from "../utils/validationVisibility";

const FALLBACK_CATALOG: ValidationCatalogItem[] = VALIDATION_CHECK_TYPES.map(
  (label, order) => ({
    key: `fallback-${order}`,
    label,
    order,
    default_visible: label !== "이상치 검수",
    default_status: "확인 필요",
    default_severity: "warning",
    description: "",
  }),
);

export function useValidationCatalog(): ValidationCatalogItem[] {
  const [catalog, setCatalog] = useState(FALLBACK_CATALOG);

  useEffect(() => {
    let active = true;
    fetchValidationCatalog()
      .then((items) => {
        if (active && items.length > 0) {
          setCatalog([...items].sort((left, right) => left.order - right.order));
        }
      })
      .catch(() => {
        // The fallback keeps local work and older backends usable.
      });
    return () => {
      active = false;
    };
  }, []);

  return catalog;
}
