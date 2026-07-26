from fastapi import APIRouter, Query

from app.models.operations import OperationsOverview
from app.operations.metrics import OperationsMetricsService


router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/metrics", response_model=OperationsOverview)
def get_operations_metrics(
    window_days: int = Query(default=30, ge=1, le=365),
    report_id: int | None = Query(default=None),
) -> OperationsOverview:
    return OperationsMetricsService().overview(
        window_days=window_days,
        report_id=report_id,
    )
