from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
    """Enum that remains compatible with existing DB and JSON string values."""

    def __str__(self) -> str:
        return self.value


class ValidationStatus(StringEnum):
    NORMAL = "정상"
    NEEDS_REVIEW = "확인 필요"
    SUSPECTED_ERROR = "오류 의심"


class TableStatus(StringEnum):
    NORMAL = "normal"
    NEEDS_REVIEW = "needs_review"
    SUSPECTED_ERROR = "suspected_error"


class Severity(StringEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class HighlightRole(StringEnum):
    TARGET = "target"
    RELATED = "related"
    HEADER = "header"


class HighlightScope(StringEnum):
    NONE = "none"
    METADATA = "metadata"
    CELL = "cell"
    HEADER = "header"
    ROW = "row"
    COLUMN = "column"


class ProfileStatus(StringEnum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    RETIRED = "retired"


class JobStatus(StringEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LanguageReviewStatus(StringEnum):
    PENDING = "대기"
    COMPLETED = "완료"
