from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db


@dataclass(frozen=True)
class ConfirmedSourceMapping:
    table_code: str
    source_external_ids: tuple[str, ...] = ()
    materializer: str | None = None
    effective_from_year: int = 2025
    effective_to_year: int | None = None
    target_period: str = ""
    instructions: str = ""
    item_projection: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ConfirmedManifestDecision:
    edition_year: int
    table_code: str
    lifecycle_status: str
    notes: str


# The mappings below are business decisions confirmed by the yearbook owner.
# Keep physical table codes here because one logical statistic can change source
# and layout at different points in its displayed time series.
CONFIRMED_SOURCE_MAPPINGS: tuple[ConfirmedSourceMapping, ...] = (
    # Explicit projections for source trees that feed a different physical
    # yearbook layout.  These are source-item rules, not values copied from a
    # completed annual report, so the same recipe applies to later increments.
    ConfirmedSourceMapping(
        "2-2-12-3 표1",
        ("M218233129571867",),
        materializer="current_period_rows",
        item_projection=((1, 10003), (2, 10007), (3, 10006), (4, 10005), (5, 10004)),
        instructions="원장 공용차량 수 하위 항목을 연보의 계·승용·승합·화물·특수 열로 재배치",
    ),
    ConfirmedSourceMapping(
        "3-2-1-1",
        ("M215063129202904",),
        materializer="period_rows",
        instructions="5개 기관 구분을 유지한 7개년 롤링 기간창",
    ),
    ConfirmedSourceMapping(
        "3-2-1-2",
        ("M217263129216944",),
        materializer="period_rows",
        instructions="5개 기관 구분을 유지한 7개년 롤링 기간창",
    ),
    ConfirmedSourceMapping(
        "4-1-1-3",
        ("M213233129859083",),
        materializer="period_rows",
        instructions="기준일별 행정구역 수를 10개년 롤링 기간창으로 이동",
    ),
    ConfirmedSourceMapping(
        "4-1-4-2",
        ("M214393129958981",),
        materializer="current_period_rows",
        instructions="인용·기각·각하 행은 원장에서, 계 행은 세 행의 합으로 산출",
    ),
    ConfirmedSourceMapping(
        "8-1-3-2 표1",
        ("M212113130877979",),
        materializer="period_rows",
        item_projection=((1, 10010), (3, 10012)),
        instructions="사이버교육 운영 하위 과정수·수료인원을 10개년 기간창에 반영",
    ),
    ConfirmedSourceMapping(
        "8-1-3-2 표2",
        ("M212113130877979",),
        materializer="period_rows",
        item_projection=((1, 10007), (2, 10008), (4, 10009)),
        instructions="연계 운영 하위 과정수·횟수·수료인원을 10개년 기간창에 반영",
    ),
    ConfirmedSourceMapping(
        "8-1-3-2 표3",
        ("M212113130877979",),
        materializer="period_rows",
        item_projection=((1, 10004), (3, 10006)),
        instructions="공동활용 하위 과정수·수료인원을 10개년 기간창에 반영",
    ),
    ConfirmedSourceMapping(
        "8-1-4 표1",
        ("M214083130887319",),
        materializer="period_rows",
        instructions="교육 훈련 구분별 수치를 표시 기간창에 반영",
    ),
    ConfirmedSourceMapping("2-1-1-6", ("M214863128953220",)),
    ConfirmedSourceMapping(
        "3-1-10-1",
        ("M215403129751227",),
        instructions="원장의 이용자 수 항목만 사용",
    ),
    ConfirmedSourceMapping(
        "3-1-10-2",
        ("M215403129751227",),
        instructions="원장의 활용업무 수 항목만 사용",
    ),
    ConfirmedSourceMapping(
        "4-1-8-10",
        ("M219063130145522",),
        instructions="원장 열을 연보 열 구조에 맞춰 재배치",
    ),
    ConfirmedSourceMapping("4-1-9 표1", ("M213863130151704",)),
    ConfirmedSourceMapping("4-1-9 표2", ("M214733130163047",)),
    ConfirmedSourceMapping("4-1-9 표3", ("M219183130174477",)),
    ConfirmedSourceMapping("4-1-9 표4", ("M211873130183601",)),
    ConfirmedSourceMapping("4-2-3", ("M212273130379572",)),
    ConfirmedSourceMapping("4-2-13", ("M213483130547199",)),
    ConfirmedSourceMapping("5-2-1-3 표1", ("M211753130734895",)),
    ConfirmedSourceMapping("5-2-1-3 표2", ("M211753130734895",)),
    ConfirmedSourceMapping("5-2-1-5 표3", ("M215733130758283",)),
    ConfirmedSourceMapping(
        "5-2-1-1",
        ("M214103130711463",),
        materializer="period_columns",
        effective_from_year=2026,
        target_period="2025",
    ),
    ConfirmedSourceMapping(
        "6-1-1-2",
        ("M219513131281465",),
        instructions="운영횟수 항목만 사용",
    ),
    ConfirmedSourceMapping("6-2-5-2 표1", ("M219273131498425",)),
    ConfirmedSourceMapping("6-2-5-2 표2", ("M225153136271741",)),
    ConfirmedSourceMapping("6-3-1-6 표1", ("M211093132483160",)),
    ConfirmedSourceMapping("6-3-1-6 표2", ("M215703132492436",)),
    ConfirmedSourceMapping("6-3-3-1", ("M262843136917166",)),
    ConfirmedSourceMapping(
        "6-3-3-2 표1",
        ("M213263132123448",),
        materializer="period_rows",
    ),
    ConfirmedSourceMapping("6-3-3-2 표2", ("M263323136902622",)),
    ConfirmedSourceMapping(
        "7-1-1-2 표1",
        ("M219373132161010",),
        materializer="copy",
        target_period="2021",
        instructions="2013~2021 고정 역사 구간; 이후 연도는 표2 원장을 사용",
    ),
    ConfirmedSourceMapping("7-1-1-2 표2", ("M237533136425478",)),
    ConfirmedSourceMapping("7-2-1-3", ("M217383131691668",)),
    ConfirmedSourceMapping("7-2-8-1", ("M235243136439598",)),
    ConfirmedSourceMapping(
        "7-2-8-2 표1",
        ("M218233131863939",),
        target_period="2016",
    ),
    ConfirmedSourceMapping("7-2-8-2 표2", ("M219633132359113",)),
    ConfirmedSourceMapping(
        "7-2-8-2 표3",
        ("M221263136244982",),
        effective_from_year=2026,
        target_period="2022",
    ),
    ConfirmedSourceMapping(
        "7-2-8-2 표4",
        ("M231213136441325",),
        materializer="period_rows",
    ),
    ConfirmedSourceMapping("7-3-2-1 표1", ("M266923136927852",)),
    ConfirmedSourceMapping("7-3-2-1 표2", ("M266923136927852",)),
    ConfirmedSourceMapping("7-3-3-2 표2", ("M269333136954264",)),
    ConfirmedSourceMapping("7-3-6-1", ("M265503136976572",)),
    ConfirmedSourceMapping("8-1-1-2 표1", ("M218243130828689",)),
    ConfirmedSourceMapping("8-1-1-2 표2", ("M214403132343168",)),
    ConfirmedSourceMapping("부록 3", ("M214663130943978",)),
    ConfirmedSourceMapping(
        "1-1-1-3",
        ("M213243127991826",),
        materializer="current_period_rows",
        instructions="매년 해당 기준연도의 정부조직 변천 전체 내용으로 교체",
    ),
    ConfirmedSourceMapping(
        "1-1-1-4 표1",
        materializer="copy",
        instructions="2019년 이전 구형 구간. 전체 표시기간에서 벗어난 연도만 순차 제거",
    ),
    ConfirmedSourceMapping("1-1-1-4 표2", ("M214673128004994",)),
    ConfirmedSourceMapping("1-2-2 표1", ("M217343128834632",)),
    ConfirmedSourceMapping("1-2-2 표2", ("M217343128834632",)),
    ConfirmedSourceMapping("3-1-4", ("M217263129685276",)),
    ConfirmedSourceMapping("4-1-5-2", ("M214363129975991",)),
    ConfirmedSourceMapping(
        "4-1-11-2 표1",
        ("M217723130212039", "M265333136875186"),
        instructions="두 원장의 연도별 사례 건수를 이어서 사용",
    ),
    ConfirmedSourceMapping(
        "4-1-11-2 표2",
        ("M217723130212039", "M265333136875186"),
        instructions="2021년까지 사례와 2025년 이후 사례를 이어서 사용",
    ),
    ConfirmedSourceMapping("4-2-12 표1", ("M262383137017378",)),
    ConfirmedSourceMapping("4-2-12 표2", ("M262383137017378",)),
    ConfirmedSourceMapping("7-2-5-1", ("M264943136882313",)),
    ConfirmedSourceMapping(
        "7-2-5-2 표1",
        ("M211783131778281",),
        materializer="period_rows",
    ),
    ConfirmedSourceMapping("7-2-5-2 표2", ("M269753136897179",)),
    ConfirmedSourceMapping("7-2-6", ("M211993131828600",)),
    # 2025 uses an older chapter numbering scheme. These aliases are scoped to
    # that edition so the same physical code may point elsewhere in 2026.
    ConfirmedSourceMapping(
        "2-2-12-1",
        ("M212913129553199",),
        effective_to_year=2025,
    ),
    ConfirmedSourceMapping(
        "3-1-1-1",
        ("M217873129608475",),
        materializer="period_columns",
        effective_to_year=2025,
        target_period="2023",
    ),
    ConfirmedSourceMapping(
        "3-1-1-2",
        ("M216893129619198",),
        materializer="period_columns",
        effective_to_year=2025,
        target_period="2023",
    ),
    ConfirmedSourceMapping(
        "3-1-11-1",
        ("M215403129751227",),
        materializer="period_columns",
        effective_to_year=2025,
        instructions="2025 편제의 GVPN 이용자 수 항목만 사용",
    ),
    ConfirmedSourceMapping(
        "3-1-11-2",
        ("M215403129751227",),
        materializer="period_columns",
        effective_to_year=2025,
        instructions="2025 편제의 GVPN 활용업무 수 항목만 사용",
    ),
    ConfirmedSourceMapping(
        "4-2-4",
        ("M212273130379572",),
        effective_to_year=2025,
    ),
    ConfirmedSourceMapping(
        "4-2-6-1",
        ("M248393136616373",),
        effective_to_year=2025,
    ),
    ConfirmedSourceMapping(
        "4-2-10-2",
        ("M216743130493312",),
        effective_to_year=2025,
    ),
    ConfirmedSourceMapping(
        "4-2-14",
        ("M219873135902084",),
        effective_to_year=2025,
        target_period="2023",
    ),
    ConfirmedSourceMapping(
        "5-1-1-1",
        ("M213963130568422",),
        materializer="current_period_rows",
        effective_to_year=2025,
        target_period="2025",
    ),
    ConfirmedSourceMapping(
        "5-2-1-1",
        ("M214103130711463",),
        materializer="period_columns",
        effective_to_year=2025,
        target_period="2024",
    ),
    ConfirmedSourceMapping(
        "6-1-1-1",
        ("M219513131281465",),
        materializer="current_period_rows",
        effective_to_year=2025,
        target_period="2024",
        instructions="2025 편제의 회차별 개최일·주요 안건을 사용",
    ),
    ConfirmedSourceMapping(
        "6-1-2",
        ("M212023131292802",),
        effective_to_year=2025,
    ),
    ConfirmedSourceMapping(
        "6-1-5",
        ("M213153131344045",),
        effective_to_year=2025,
    ),
)

CONFIRMED_MANIFEST_DECISIONS: tuple[ConfirmedManifestDecision, ...] = (
    ConfirmedManifestDecision(
        2026,
        "2-2-2-1",
        "empty",
        "사용자 확인: 데이터가 입력될 때까지 빈 표로 유지",
    ),
    ConfirmedManifestDecision(
        2026,
        "5-1-5-3",
        "empty",
        "사용자 확인: 데이터가 입력될 때까지 빈 표로 유지",
    ),
    ConfirmedManifestDecision(
        2026,
        "7-2-1-1",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "7-2-2",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "1-1-1-3",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "1-2-2 표1",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "1-2-2 표2",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "3-1-4",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "4-1-9 표4",
        "updated",
        "사용자 확인: 기준연도 원장값이 있으면 해당 값으로 업데이트",
    ),
    ConfirmedManifestDecision(
        2026,
        "4-1-9 표3",
        "no_change",
        "2025년 원장값이 아직 없어 2024년 값을 승계하고, 신규 입력 시 교체",
    ),
    ConfirmedManifestDecision(
        2026,
        "4-2-3",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "7-2-6",
        "no_change",
        "사용자 확인: 새 기준연도 데이터가 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "4-1-5-2",
        "no_change",
        "기수 단위 통계: 새 기수 원장값이 들어오기 전까지 현재 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "2-2-9 표2",
        "no_change",
        "현재 원장은 기관 수만 제공하고 기관명 목록은 없어 기존 상세 목록을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "5-2-1-5 표3",
        "no_change",
        "현재 원장은 국내 조세부담률만 제공하여 국가별 비교표는 기존 값을 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "6-2-4-3 표2",
        "no_change",
        "현재 원장은 분야별 건수만 제공하여 신고내용 설명표는 기존 문구를 승계",
    ),
    ConfirmedManifestDecision(
        2026,
        "8-1-1-1",
        "no_change",
        "현재 원장은 기록물 종류별 합계만 제공하여 보존처별 상세표는 기존 값을 승계",
    ),
    *(
        ConfirmedManifestDecision(
            2025,
            table_code,
            "no_change",
            note,
        )
        for table_code, note in (
            ("2-2-9 표2", "기관명 상세 원장이 없어 2025 확정 목록을 승계"),
            ("3-1-7-1", "2025 구형 모바일 공무원증 레이아웃을 확정값으로 승계"),
            ("3-1-7-2", "모바일 운전면허증 원장이 없어 2025 확정값을 승계"),
            ("3-1-10-1", "PC영상회의 전용 원장이 없어 2025 확정값을 승계"),
            ("3-1-10-2", "PC영상회의 전용 원장이 없어 2025 확정값을 승계"),
            ("4-1-4-2", "2024 기준기간 원장이 없어 2025 확정값을 승계"),
            ("4-1-11-2 표1", "사례 원장의 기준기간 공백으로 2025 확정값을 승계"),
            ("4-1-11-2 표2", "사례 원장의 기준기간 공백으로 2025 확정값을 승계"),
            ("4-2-13 표1", "2025 구형 온천 상세 레이아웃을 확정값으로 승계"),
            ("4-2-13 표2", "2025 구형 온천 상세 레이아웃을 확정값으로 승계"),
            ("5-1-1-1", "원장에 2025 예산 기준기간이 없어 2025 확정값을 승계"),
            ("5-2-1-5 표3", "국가별 조세부담률 원장이 없어 2025 확정값을 승계"),
            ("6-2-4-3 표2", "신고내용 설명 원장이 없어 2025 확정 문구를 승계"),
            ("6-3-3-1", "2024 기준기간 원장이 없어 2025 확정값을 승계"),
            ("6-3-3-3 표2", "재난예방방송 상세 원장이 없어 2025 확정값을 승계"),
            ("7-2-5-1", "2024 기준기간 원장이 없어 2025 확정값을 승계"),
            ("7-3-2-1 표1", "2023 기준기간 원장이 없어 2025 확정값을 승계"),
            ("7-3-2-1 표2", "2023 기준기간 원장이 없어 2025 확정값을 승계"),
            ("7-3-5-1", "2025 구형 다중 합계 레이아웃을 확정값으로 승계"),
            ("7-3-6-1", "2024 기준기간 원장이 없어 2025 확정값을 승계"),
            ("8-1-1-1", "보존처별 상세 원장이 없어 2025 확정값을 승계"),
        )
    ),
)

CARRY_FORWARD_UNTIL_UPDATED_CODES = frozenset(
    decision.table_code
    for decision in CONFIRMED_MANIFEST_DECISIONS
    if decision.lifecycle_status == "no_change"
    and decision.edition_year >= 2026
)

UPDATED_FROM_SOURCE_CODES = frozenset(
    decision.table_code
    for decision in CONFIRMED_MANIFEST_DECISIONS
    if decision.lifecycle_status == "updated"
)


class ConfirmedSourceMappingService:
    """Persist owner-confirmed source choices as approved reusable recipes."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        mappings: tuple[ConfirmedSourceMapping, ...] = CONFIRMED_SOURCE_MAPPINGS,
    ) -> None:
        self._db_path = db_path
        self._mappings = mappings

    def synchronize(self) -> int:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                applied = 0
                for mapping in self._mappings:
                    if apply_mapping(connection, mapping):
                        applied += 1
                return applied

    def synchronize_manifest_decisions(self) -> int:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                applied = 0
                for decision in CONFIRMED_MANIFEST_DECISIONS:
                    cursor = connection.execute(
                        """
                        UPDATE yearbook_edition_manifest
                        SET lifecycle_status = ?,
                            source_dataset_id = CASE
                                WHEN ? = 'updated' THEN (
                                    SELECT source_dataset_id
                                    FROM yearbook_table_recipes recipe
                                    WHERE recipe.table_code = ?
                                    ORDER BY revision DESC, id DESC
                                    LIMIT 1
                                )
                                ELSE source_dataset_id
                            END,
                            notes = ?, is_inferred = 0,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE edition_year = ? AND table_code = ?
                        """,
                        (
                            decision.lifecycle_status,
                            decision.lifecycle_status,
                            decision.table_code,
                            decision.notes,
                            decision.edition_year,
                            decision.table_code,
                        ),
                    )
                    if cursor.rowcount:
                        applied += 1
                for table_code in CARRY_FORWARD_UNTIL_UPDATED_CODES:
                    connection.execute(
                        """
                        UPDATE yearbook_table_update_policies
                        SET no_update_action = 'carry_forward',
                            notes = CASE
                                WHEN notes = '' THEN ?
                                ELSE notes || ' / ' || ?
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE table_code = ?
                          AND no_update_action <> 'carry_forward'
                        """,
                        (
                            "새 기준연도 원장값이 없으면 직전 값을 승계",
                            "새 기준연도 원장값이 없으면 직전 값을 승계",
                            table_code,
                        ),
                    )
                for table_code in UPDATED_FROM_SOURCE_CODES:
                    connection.execute(
                        """
                        UPDATE yearbook_table_update_policies
                        SET no_update_action = 'require_manifest',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE table_code = ?
                        """,
                        (table_code,),
                    )
                return applied


def apply_mapping(
    connection: DatabaseConnection,
    mapping: ConfirmedSourceMapping,
) -> bool:
    table = connection.execute(
        """
        SELECT table_row.id, table_row.report_id
        FROM stat_tables table_row
        JOIN annual_reports report ON report.id = table_row.report_id
        WHERE table_row.code = ?
        ORDER BY report.year DESC, report.is_archived, table_row.id DESC
        LIMIT 1
        """,
        (mapping.table_code,),
    ).fetchone()
    if table is None:
        return False

    source_rows = []
    for external_id in mapping.source_external_ids:
        source = connection.execute(
            """
            SELECT id, external_id, title
            FROM statistical_datasets
            WHERE external_id = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (external_id,),
        ).fetchone()
        if source is None:
            raise ValueError(
                f"{mapping.table_code}에 지정한 원장 {external_id}을 찾을 수 없습니다."
            )
        period_range = connection.execute(
            """
            SELECT MIN(period) AS first_period, MAX(period) AS last_period
            FROM statistical_values
            WHERE dataset_id = ?
            """,
            (int(source["id"]),),
        ).fetchone()
        source_rows.append(
            {
                "id": int(source["id"]),
                "external_id": str(source["external_id"]),
                "title": str(source["title"]),
                "first_period": str(period_range["first_period"] or ""),
                "last_period": str(period_range["last_period"] or ""),
            }
        )

    latest = connection.execute(
        """
        SELECT id, revision, materializer, status, config_json,
               effective_from_year, effective_to_year
        FROM yearbook_table_recipes
        WHERE table_code = ?
        ORDER BY revision DESC, id DESC
        LIMIT 1
        """,
        (mapping.table_code,),
    ).fetchone()
    matching = connection.execute(
        """
        SELECT id, revision, materializer, status, config_json,
               effective_from_year, effective_to_year
        FROM yearbook_table_recipes
        WHERE table_code = ?
          AND effective_from_year = ?
          AND (
              (effective_to_year IS NULL AND ? IS NULL)
              OR effective_to_year = ?
          )
        ORDER BY revision DESC, id DESC
        LIMIT 1
        """,
        (
            mapping.table_code,
            mapping.effective_from_year,
            mapping.effective_to_year,
            mapping.effective_to_year,
        ),
    ).fetchone()
    materializer = (
        mapping.materializer
        or (
            str(matching["materializer"])
            if matching is not None
            else (
                str(latest["materializer"])
                if latest is not None
                else "current_period_rows"
            )
        )
    )
    config = {
        "mapping_authority": "user_confirmed",
        "confirmation_key": "2026-owner-review-v1",
        "source_external_ids": list(mapping.source_external_ids),
        "source_bindings": [
            {
                "dataset_id": int(source["id"]),
                "external_id": str(source["external_id"]),
                "title": str(source["title"]),
                "first_period": str(source["first_period"]),
                "last_period": str(source["last_period"]),
                "priority": index,
            }
            for index, source in enumerate(source_rows)
        ],
        "instructions": mapping.instructions,
        "target_period": mapping.target_period,
        "value_authority": "source_ledger",
        "item_projection": {
            str(column): item
            for column, item in mapping.item_projection
        },
    }
    config_json = json.dumps(config, ensure_ascii=False)
    primary_source_id = int(source_rows[-1]["id"]) if source_rows else None
    approved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if matching is not None and str(matching["status"]) == "approved":
        existing_config = json.loads(str(matching["config_json"] or "{}"))
        if existing_config.get("confirmation_key") == config["confirmation_key"]:
            connection.execute(
                """
                UPDATE yearbook_table_recipes
                SET effective_from_year = ?, effective_to_year = ?,
                    source_dataset_id = ?,
                    materializer = ?, config_json = ?,
                    source_report_id = ?, source_table_id = ?, notes = ?,
                    approved_at = ?, approved_by = 'yearbook_owner'
                WHERE id = ?
                """,
                (
                    mapping.effective_from_year,
                    mapping.effective_to_year,
                    primary_source_id,
                    materializer,
                    config_json,
                    int(table["report_id"]),
                    int(table["id"]),
                    mapping.instructions or "사용자가 원장 연결을 확정했습니다.",
                    approved_at,
                    int(matching["id"]),
                ),
            )
            return True

    revision = int(latest["revision"] or 0) + 1 if latest is not None else 1
    connection.execute(
        """
        INSERT INTO yearbook_table_recipes (
            table_code, revision, effective_from_year, effective_to_year,
            source_dataset_id, materializer, config_json, status,
            source_report_id, source_table_id, notes, approved_at, approved_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?, 'yearbook_owner')
        """,
        (
            mapping.table_code,
            revision,
            mapping.effective_from_year,
            mapping.effective_to_year,
            primary_source_id,
            materializer,
            config_json,
            int(table["report_id"]),
            int(table["id"]),
            mapping.instructions or "사용자가 원장 연결을 확정했습니다.",
            approved_at,
        ),
    )
    return True
