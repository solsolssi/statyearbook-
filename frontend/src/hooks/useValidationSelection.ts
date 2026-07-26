import { useEffect, useState } from "react";

export type CheckFilter = "all" | "passed" | "review" | "error";

interface SelectableCheck {
  id: string;
}

interface ValidationBuckets<T extends SelectableCheck> {
  all: T[];
  passed: T[];
  review: T[];
  error: T[];
}

interface UseValidationSelectionOptions<T extends SelectableCheck> {
  buckets: ValidationBuckets<T>;
  resetKey: string;
  firstFocusable?: (checks: T[]) => T | undefined;
}

function checksForFilter<T extends SelectableCheck>(
  filter: CheckFilter,
  buckets: ValidationBuckets<T>,
): T[] {
  return buckets[filter];
}

export function useValidationSelection<T extends SelectableCheck>({
  buckets,
  resetKey,
  firstFocusable = (checks) => checks[0],
}: UseValidationSelectionOptions<T>) {
  const [filter, setFilter] = useState<CheckFilter>("error");
  const [selectedId, setSelectedId] = useState<string>();
  const [scrollSignal, setScrollSignal] = useState(0);
  const filteredChecks = checksForFilter(filter, buckets);
  const selected =
    filteredChecks.find((check) => check.id === selectedId) ?? filteredChecks[0];
  const selectedIndex = Math.max(
    filteredChecks.findIndex((check) => check.id === selected?.id),
    0,
  );

  function select(checkId: string) {
    setSelectedId(checkId);
    setScrollSignal((value) => value + 1);
  }

  function selectFilter(nextFilter: CheckFilter) {
    const nextChecks = checksForFilter(nextFilter, buckets);
    const next = firstFocusable(nextChecks);
    setFilter(nextFilter);
    setSelectedId(next?.id);
    if (next) {
      setScrollSignal((value) => value + 1);
    }
  }

  function move(direction: -1 | 1) {
    if (filteredChecks.length === 0) {
      return;
    }
    const nextIndex =
      (selectedIndex + direction + filteredChecks.length) % filteredChecks.length;
    select(filteredChecks[nextIndex].id);
  }

  function resetScrollSignal() {
    setScrollSignal(0);
  }

  useEffect(() => {
    const initialFilter: CheckFilter =
      buckets.error.length > 0
        ? "error"
        : buckets.review.length > 0
          ? "review"
          : "all";
    const initialChecks = checksForFilter(initialFilter, buckets);
    setFilter(initialFilter);
    setSelectedId(firstFocusable(initialChecks)?.id);
  }, [buckets, firstFocusable, resetKey]);

  return {
    filter,
    filteredChecks,
    selected,
    selectedIndex,
    scrollSignal,
    select,
    selectFilter,
    move,
    resetScrollSignal,
  };
}

