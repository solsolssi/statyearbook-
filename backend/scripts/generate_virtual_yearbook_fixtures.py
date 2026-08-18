from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "generated" / "virtual_yearbook_test"


@dataclass(frozen=True)
class TableSpec:
    code: str
    title: str
    title_en: str
    unit: str
    department: str
    officer: str
    phone: str
    source_key: str
    management_number: str
    rows: tuple[tuple[str, ...], ...]
    base_date: str = "2027. 12. 31."
    include_metadata: bool = True
    note: str = ""
    html: str = ""


def table_source(table: TableSpec) -> str:
    identity = ""
    if table.source_key:
        identity += f" 원장 ID: {table.source_key}"
    if table.management_number:
        identity += f" 관리 번호: {table.management_number}"
    return (
        f"* {table.department} 주무관 {table.officer} ({table.phone}) /"
        f" 가상 통합테스트 자료{identity}"
    )


def annual_code(code: str) -> str:
    """Keep fixtures in a dedicated chapter while satisfying 3-part codes."""
    return f"9-{code}"


def render_table(table: TableSpec) -> str:
    lines = [f"{annual_code(table.code)} {table.title} {table.title_en}", ""]
    if table.html:
        lines.append(table.html.strip())
    else:
        width = max(len(row) for row in table.rows)
        if table.include_metadata:
            metadata = f"({table.base_date} 기준)(단위 : {table.unit})"
            lines.append("| " + " | ".join([metadata, *([""] * (width - 1))]) + " |")
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in table.rows:
            padded = [*row, *([""] * (width - len(row)))]
            lines.append("| " + " | ".join(padded) + " |")
    if table.note:
        lines.extend(["", f"#주1) {table.note}"])
    lines.extend(["", table_source(table), ""])
    return "\n".join(lines)


def write_markdown(path: Path, title: str, tables: Iterable[TableSpec]) -> None:
    introduction = [
        f"# {title}",
        "",
        "이 파일은 통계연보 업로드·증분 연결·검수·수정·재검수 통합 테스트 전용 가상 자료입니다.",
        "실제 기관이나 수치를 나타내지 않습니다.",
        "",
    ]
    body = "\n".join(render_table(table) for table in tables)
    path.write_text("\n".join(introduction) + body, encoding="utf-8")


def v1_tables() -> list[TableSpec]:
    common = {
        "base_date": "2027. 12. 31.",
    }
    return [
        TableSpec("1-1", "민원 처리 채널별 현황", "Civil Petitions by Channel", "건", "민원제도과", "가상일", "02-2000-1001", "M-V-001", "V-001", (
            ("구분<br>Classification", "합계<br>Total", "온라인<br>Online", "방문<br>In-person"),
            ("신청<br>Applications", "150", "90", "60"),
            ("완료<br>Completed", "120", "75", "45"),
            ("미처리<br>Pending", "30", "15", "15"),
        ), **common),
        TableSpec("1-2", "지역별 상담 실적", "Consultations by Region", "건", "상담지원과", "가상두", "02-2000-1002", "M-V-002", "V-002", (
            ("지역<br>Region", "상담 건수<br>Consultations"),
            ("합계<br>Total", "300"),
            ("동부<br>East", "120"),
            ("서부<br>West", "100"),
            ("남부<br>South", "80"),
        ), **common),
        TableSpec("1-3", "사업별 예산 집행", "Budget Execution by Program", "백만원", "재정시험과", "가상삼", "02-2000-1003", "M-V-003", "V-003", (
            ("사업<br>Program", "인건비(a)<br>Labor", "운영비(b)<br>Operation", "합계(c=a+b)<br>Total"),
            ("서비스 개선<br>Service Improvement", "60", "40", "100"),
            ("시스템 구축<br>System Development", "70", "50", "125"),
            ("교육 운영<br>Training", "30", "50", "80"),
        ), note="시스템 구축 합계 125는 의도적인 오류이며 실제 합은 120이다.", **common),
        TableSpec("1-4", "성별 교육 참여", "Training Participation by Gender", "명, %", "인재개발과", "가상사", "02-2000-1004", "M-V-004", "V-004", (
            ("과정<br>Course", "전체(a)<br>Total", "여성(b)<br>Women", "여성 비율(b/a*100)<br>Women Share"),
            ("기본 과정<br>Basic", "100", "55", "55.0"),
            ("심화 과정<br>Advanced", "80", "36", "45.0"),
            ("관리자 과정<br>Manager", "50", "20", "40.0"),
        ), **common),
        TableSpec("1-5", "서비스 신청 승인률", "Service Application Approval Rate", "건, %", "서비스정책과", "가상오", "02-2000-1005", "M-V-005", "V-005", (
            ("서비스<br>Service", "신청(a)<br>Applications", "승인(b)<br>Approvals", "승인률(b/a*100)<br>Approval Rate"),
            ("알림 서비스<br>Notification", "100", "80", "83.0"),
            ("증명 서비스<br>Certificate", "200", "150", "75.0"),
        ), note="알림 서비스 승인률 83.0은 의도적인 오류이며 기대값은 80.0이다.", **common),
        TableSpec("2-1", "연도별 민원 접수", "Civil Petitions by Year", "건", "민원분석과", "가상육", "02-2000-1006", "M-V-006", "V-006", (
            ("연도<br>Year", "합계<br>Total", "온라인<br>Online", "방문<br>In-person"),
            ("2023", "100", "60", "40"),
            ("2024", "120", "75", "45"),
            ("2025", "140", "90", "50"),
            ("2026", "160", "105", "55"),
            ("2027", "180", "120", "60"),
        ), **common),
        TableSpec("2-2", "연도별 서비스 처리", "Service Processing by Year", "건", "디지털운영과", "가상칠", "02-2000-1007", "M-V-007", "V-007", (
            ("구분<br>Classification", "2023", "2024", "2025", "2026", "2027"),
            ("신청<br>Applications", "100", "120", "140", "160", "180"),
            ("승인<br>Approvals", "80", "95", "110", "130", "150"),
            ("반려<br>Rejected", "20", "25", "30", "30", "30"),
        ), **common),
        TableSpec("2-3", "부서별 인력 현황", "Personnel by Department", "명", "조직시험과", "가상팔", "02-2000-1008", "M-V-008", "V-008", (
            ("부서<br>Department", "정원<br>Authorized", "현원<br>Actual"),
            ("정책팀<br>Policy", "20", "19"),
            ("운영팀<br>Operations", "30", "28"),
            ("지원팀<br>Support", "15", "15"),
        ), **common),
        TableSpec("2-4", "접수·처리 방식별 실적", "Requests and Processing by Method", "건", "통합운영과", "가상구", "02-2000-1009", "M-V-009", "V-009", (), html="""
<table>
<tr><th colspan="5">(2027. 12. 31. 기준)(단위 : 건)</th></tr>
<tr><th rowspan="2">구분<br>Classification</th><th colspan="2">접수<br>Requests</th><th colspan="2">처리<br>Processing</th></tr>
<tr><th>온라인<br>Online</th><th>방문<br>In-person</th><th>완료<br>Completed</th><th>대기<br>Pending</th></tr>
<tr><td>일반<br>General</td><td>70</td><td>30</td><td>90</td><td>10</td></tr>
<tr><td>긴급<br>Urgent</td><td>20</td><td>10</td><td>25</td><td>5</td></tr>
</table>
""", **common),
        TableSpec("2-5", "정책 만족도 조사", "Policy Satisfaction Survey", "점, 명", "정책평가과", "가상십", "02-2000-1010", "M-V-010", "V-010", (), html="""
<table>
<tr><th colspan="3">▫ 만족도 점수 Satisfaction Score</th></tr>
<tr><th colspan="3">(2027. 12. 31. 기준)(단위 : 점, 명)</th></tr>
<tr><th>구분<br>Classification</th><th>점수<br>Score</th><th>응답자<br>Respondents</th></tr>
<tr><td>정책 A<br>Policy A</td><td>82.5</td><td>120</td></tr>
<tr><td>정책 B<br>Policy B</td><td>76.0</td><td>100</td></tr>
</table>

<table>
<tr><th colspan="3">▫ 응답 분포 Response Distribution</th></tr>
<tr><th colspan="3">(2027. 12. 31. 기준)(단위 : 명)</th></tr>
<tr><th>구분<br>Classification</th><th>만족<br>Satisfied</th><th>불만족<br>Dissatisfied</th></tr>
<tr><td>정책 A<br>Policy A</td><td>100</td><td>20</td></tr>
<tr><td>정책 B<br>Policy B</td><td>76</td><td>24</td></tr>
</table>
""", **common),
        TableSpec("3-1", "업무 처리 품질", "Work Processing Quality", "건", "품질관리과", "가상십일", "02-2000-1011", "M-V-011", "V-011", (
            ("구분<br>Classification", "처리건슈<br>Processed Cases", "오류 건수<br>Errors"),
            ("1분기<br>Q1", "100", "2"),
            ("2분기<br>Q2", "110", "1"),
        ), note="처리건슈는 오탈자 검수용 의도적 오류다.", **common),
        TableSpec("3-2", "시설 방문자 현황", "Facility Visitors", "명", "시설운영과", "가상십이", "02-2000-1012", "M-V-012", "V-012", (
            ("시설<br>Facility", "방문자<br>Operating Budget"),
            ("가상관 A<br>Virtual Hall A", "1,200"),
            ("가상관 B<br>Virtual Hall B", "900"),
        ), note="방문자의 영문값 Operating Budget은 번역 검수용 의도적 오류다.", **common),
        TableSpec("3-3", "민원 유형별 건수", "Cases by Petition Type", "건", "민원통계과", "가상십삼", "02-2000-1013", "M-V-013", "V-013", (
            ("민원 유형", "건수<br>Cases"),
            ("질의", "70"),
            ("건의", "20"),
            ("신고", "10"),
        ), note="첫 열의 영문값 누락을 번역 후보로 남기는 케이스다.", **common),
        TableSpec("3-4", "월별 장애 발생", "Monthly Service Failures", "건", "정보보호과", "가상십사", "02-2000-1014", "M-V-014", "V-014", (
            ("월<br>Month", "장애 건수<br>Failures"),
            ("1월<br>January", "2"),
            ("2월<br>February", "3"),
            ("3월<br>March", "2"),
            ("4월<br>April", "9,999"),
            ("5월<br>May", "3"),
        ), note="4월 값은 이상치 검수용이다.", **common),
        TableSpec("3-5", "내부 점검 실적", "Internal Inspection Results", "건", "감사시험과", "가상십오", "02-2000-1015", "M-V-015", "V-015", (
            ("구분<br>Classification", "점검<br>Inspections", "조치<br>Actions"),
            ("정기<br>Regular", "20", "4"),
            ("수시<br>Ad hoc", "10", "3"),
        ), include_metadata=False, **common),
        TableSpec("4-1", "디지털 서비스 이용 현황 A", "Digital Service Usage A", "건", "디지털운영과", "가상십육", "02-2000-1016", "", "", (
            ("채널<br>Channel", "이용 건수<br>Usage"),
            ("웹<br>Web", "500"),
            ("앱<br>App", "700"),
        ), note="유사 제목 증분 후보 A. LLM 연결 보조 테스트를 위해 M키를 의도적으로 넣지 않았다.", **common),
        TableSpec("4-2", "디지털 서비스 이용 현황 B", "Digital Service Usage B", "건", "디지털지원과", "가상십칠", "02-2000-1017", "", "", (
            ("채널<br>Channel", "이용 건수<br>Usage"),
            ("전화<br>Phone", "300"),
            ("챗봇<br>Chatbot", "400"),
        ), note="유사 제목 증분 후보 B. LLM 연결 보조 테스트를 위해 M키를 의도적으로 넣지 않았다.", **common),
        TableSpec("4-3", "재난 알림 전달 실적", "Disaster Alert Delivery", "건", "재난정보과", "가상십팔", "02-2000-1018", "M-V-018", "V-018", (
            ("유형<br>Type", "발송<br>Sent", "성공<br>Delivered"),
            ("문자<br>SMS", "1,000", "980"),
            ("앱<br>App", "800", "760"),
        ), note="v2에서 열이 추가되어 구조 변경 프로파일 재생성을 확인한다.", **common),
        TableSpec("4-4", "기관 유형별 현황", "Organizations by Type", "개", "조직통계과", "가상십구", "02-2000-1019", "M-V-019", "V-019", (
            ("유형<br>Type", "기관 수<br>Organizations"),
            ("공공기관<br>Public", "30"),
            ("민간기관<br>Private", "70"),
        ), **common),
        TableSpec("4-5", "교육 과정 운영", "Training Course Operation", "과정, 명", "교육운영과", "가상이십", "02-2000-1020", "M-V-020", "V-020", (
            ("과정<br>Course", "운영 횟수<br>Sessions", "참여 인원<br>Participants"),
            ("기본<br>Basic", "10", "200"),
            ("심화<br>Advanced", "5", "80"),
        ), **common),
    ]


def v2_tables() -> list[TableSpec]:
    tables = [
        replace(
            table,
            base_date="2028. 12. 31.",
            html=table.html.replace("2027. 12. 31.", "2028. 12. 31."),
        )
        for table in v1_tables()
    ]
    by_code = {table.code: index for index, table in enumerate(tables)}

    tables[by_code["1-3"]] = replace(
        tables[by_code["1-3"]],
        rows=(
            ("사업<br>Program", "인건비(a)<br>Labor", "운영비(b)<br>Operation", "합계(c=a+b)<br>Total"),
            ("서비스 개선<br>Service Improvement", "65", "45", "110"),
            ("시스템 구축<br>System Development", "75", "55", "130"),
            ("교육 운영<br>Training", "35", "55", "90"),
        ),
        note="v1의 합계 오류를 수정하고 모든 값도 변경한 재검수 케이스다.",
    )
    tables[by_code["1-5"]] = replace(
        tables[by_code["1-5"]],
        rows=(
            ("서비스<br>Service", "신청(a)<br>Applications", "승인(b)<br>Approvals", "승인률(b/a*100)<br>Approval Rate"),
            ("알림 서비스<br>Notification", "120", "96", "80.0"),
            ("증명 서비스<br>Certificate", "220", "176", "80.0"),
        ),
        note="v1의 비율 오류를 수정한 재검수 케이스다.",
    )
    tables[by_code["2-1"]] = replace(
        tables[by_code["2-1"]],
        rows=(
            ("연도<br>Year", "합계<br>Total", "온라인<br>Online", "방문<br>In-person"),
            ("2024", "120", "75", "45"), ("2025", "140", "90", "50"),
            ("2026", "160", "105", "55"), ("2027", "180", "120", "60"),
            ("2028", "210", "145", "65"),
        ),
        note="증분의 시계열 행 추가와 가장 오래된 연도 제거 기대 결과다.",
    )
    tables[by_code["2-2"]] = replace(
        tables[by_code["2-2"]],
        rows=(
            ("구분<br>Classification", "2024", "2025", "2026", "2027", "2028"),
            ("신청<br>Applications", "120", "140", "160", "180", "210"),
            ("승인<br>Approvals", "95", "110", "130", "150", "175"),
            ("반려<br>Rejected", "25", "30", "30", "30", "35"),
        ),
        note="증분의 시계열 열 추가와 가장 오래된 연도 제거 기대 결과다.",
    )
    tables[by_code["2-3"]] = replace(
        tables[by_code["2-3"]],
        rows=(
            ("부서<br>Department", "정원<br>Authorized", "현원<br>Actual"),
            ("정책팀<br>Policy", "22", "21"),
            ("운영팀<br>Operations", "32", "30"),
            ("지원팀<br>Support", "16", "15"),
        ),
        note="전체 스냅샷 교체 기대 결과다.",
    )
    tables[by_code["3-1"]] = replace(
        tables[by_code["3-1"]],
        rows=(
            ("구분<br>Classification", "처리 건수<br>Processed Cases", "오류 건수<br>Errors"),
            ("1분기<br>Q1", "120", "1"), ("2분기<br>Q2", "130", "1"),
        ),
        note="오탈자 수정과 값 변경이 함께 발생한 언어 재검수 케이스다.",
    )
    tables[by_code["4-3"]] = replace(
        tables[by_code["4-3"]],
        rows=(
            ("유형<br>Type", "발송<br>Sent", "성공<br>Delivered", "실패<br>Failed", "성공률<br>Delivery Rate"),
            ("문자<br>SMS", "1,100", "1,078", "22", "98.0"),
            ("앱<br>App", "900", "855", "45", "95.0"),
        ),
        note="열 추가로 프로파일 재생성이 필요한 구조 변경 케이스다.",
    )
    tables.append(TableSpec(
        "5-1", "신규 데이터 품질 지표", "New Data Quality Indicators", "건, %",
        "데이터혁신과", "가상이십일", "02-2000-1021", "M-V-021", "V-021",
        (
            ("구분<br>Classification", "처리량(a)<br>Processed", "정확 처리(b)<br>Accurate", "표준합계(c=a+b)<br>Standard Total", "품질지수<br>Quality Index"),
            ("자동 처리<br>Automated", "100", "95", "195", "95.0"),
            ("수동 처리<br>Manual", "80", "72", "152", "90.0"),
            ("혼합 처리<br>Hybrid", "120", "114", "234", "95.0"),
        ),
        base_date="2028. 12. 31.",
        note=(
            "신규 통계다. c=a+b는 규칙으로 생성 가능하고, 의미가 모호한 품질지수는 "
            "여러 행에서 b/a×100과 일치한다는 근거를 LLM 프로파일 보조가 확인하는 케이스다."
        ),
    ))
    return tables


def save_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "data"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    workbook.save(path)


def increment_datasets() -> list[dict[str, object]]:
    return [
        {
            "key": "M-V-006", "title": "연도별 민원 접수", "management": "V-006",
            "department": "민원분석과", "reference": "2028. 12. 31.",
            "items": [(1, "합계", "합계"), (2, "온라인", "온라인"), (3, "방문", "방문")],
            "rows": [[210, 145, 65]],
        },
        {
            "key": "M-V-007", "title": "연도별 서비스 처리", "management": "V-007",
            "department": "디지털운영과", "reference": "2028. 12. 31.",
            "items": [(1, "신청", "신청"), (2, "승인", "승인"), (3, "반려", "반려")],
            "rows": [[210, 175, 35]],
        },
        {
            "key": "M-V-008", "title": "부서별 인력 현황", "management": "V-008",
            "department": "조직시험과", "reference": "2028. 12. 31.",
            "items": [(0, "부서", "부서"), (1, "정원", "정원"), (2, "현원", "현원")],
            "rows": [["정책팀", 22, 21], ["운영팀", 32, 30], ["지원팀", 16, 15]],
        },
        {
            "key": "M-V-009", "title": "접수 처리 방식별 실적", "management": "V-009",
            "department": "통합운영과", "reference": "2028. 12. 31.",
            "items": [
                (0, "구분", "구분"), (1, "온라인", "접수>온라인"),
                (2, "방문", "접수>방문"), (3, "완료", "처리>완료"), (4, "대기", "처리>대기"),
            ],
            "rows": [["일반", 80, 35, 103, 12], ["긴급", 25, 12, 31, 6]],
        },
        {
            "key": "M-A-016", "title": "디지털 서비스 이용 현황", "management": "",
            "department": "디지털운영과", "reference": "2028. 12. 31.",
            "items": [(0, "채널", "채널"), (1, "이용 건수", "이용 건수")],
            "rows": [["웹", 560], ["앱", 780]],
        },
        {
            "key": "M-A-017", "title": "디지털 서비스 이용 현황", "management": "",
            "department": "디지털지원과", "reference": "2028. 12. 31.",
            "items": [(0, "채널", "채널"), (1, "이용 건수", "이용 건수")],
            "rows": [["전화", 320], ["챗봇", 450]],
        },
        {
            "key": "M-V-013", "title": "민원 유형별 건수", "management": "V-013",
            "department": "민원통계과", "reference": "2028. 12. 31.",
            "items": [(0, "민원 유형", "민원 유형"), (1, "건수", "건수")],
            "rows": [],
        },
        {
            "key": "M-V-014", "title": "월별 장애 발생", "management": "V-014",
            "department": "정보보호과", "reference": "2028. 12. 31.",
            "items": [(0, "중단 시간", "중단 시간"), (1, "중단 시간", "중단 시간")],
            "rows": [[12, 3], [8, 2]],
        },
        {
            "key": "M-V-021", "title": "신규 데이터 품질 지표", "management": "V-021",
            "department": "데이터혁신과", "reference": "2028. 12. 31.",
            "target_code": "9-5-1",
            "items": [
                (0, "구분", "구분"), (1, "처리량", "처리량"), (2, "정확 처리", "정확 처리"),
                (3, "표준합계", "표준합계"), (4, "품질지수", "품질지수"),
            ],
            "rows": [
                ["자동 처리", 100, 95, 195, 95.0],
                ["수동 처리", 80, 72, 152, 90.0],
                ["혼합 처리", 120, 114, 234, 95.0],
            ],
        },
        {
            "key": "M-V-020", "title": "교육 과정 운영", "management": "V-020",
            "department": "교육운영과", "reference": "2028. 12. 31.", "status": "삭제",
            "items": [], "rows": [],
        },
    ]


def write_increment_files() -> None:
    datasets = increment_datasets()
    info_headers = [
        "작성관리번호", "표id", "표이름", "입력상태", "자료시점", "wrttimeIdtfrId",
        "담당부서", "연보표번호",
    ]
    item_headers = [
        "STATBL_ID", "itmId", "레벨", "자료번호", "항목명", "데이터유형", "전체항목명", "표시순번",
    ]
    value_headers = [
        "STATBL_ID", "wrttimeIdtfrId", "자료번호", "데이터행번호", "데이터값", "검증여부",
    ]
    info_rows: list[list[object]] = []
    item_rows: list[list[object]] = []
    value_rows: list[list[object]] = []
    for dataset in datasets:
        key = str(dataset["key"])
        info_rows.append([
            dataset.get("management", ""), key, dataset["title"], dataset.get("status", "입력완료"),
            dataset["reference"], "W2028", dataset["department"], dataset.get("target_code", ""),
        ])
        items = list(dataset["items"])
        for order, (data_no, label, full_name) in enumerate(items, start=1):
            item_rows.append([key, f"{key}-I{data_no}", 0, data_no, label, "문자" if data_no == 0 else "숫자", full_name, order])
        for row_no, values in enumerate(dataset["rows"], start=1):
            for (data_no, _, _), value in zip(items, values):
                value_rows.append([key, "W2028", data_no, row_no, value, "Y"])

    save_xlsx(OUTPUT / "virtual_increment_2028_table_info.xlsx", info_headers, info_rows)
    save_xlsx(OUTPUT / "virtual_increment_2028_table_items.xlsx", item_headers, item_rows)
    save_xlsx(OUTPUT / "virtual_increment_2028_table_values.xlsx", value_headers, value_rows)


def write_manifest() -> None:
    cases = {
        "version": 1,
        "v1_logical_statistics": 20,
        "v2_logical_statistics": 21,
        "cases": [
            {"id": "parse-basic", "tables": ["1-1", "1-2"], "expected": "parsed"},
            {"id": "sum-error", "tables": ["1-3"], "v1": "error", "v2": "normal_after_fix"},
            {"id": "ratio-error", "tables": ["1-5"], "v1": "error", "v2": "normal_after_fix"},
            {"id": "increment-year-row", "tables": ["2-1"], "expected": "2028 row appended; 2023 removed"},
            {"id": "increment-year-column", "tables": ["2-2"], "expected": "2028 column appended; 2023 removed"},
            {"id": "increment-snapshot", "tables": ["2-3"], "expected": "snapshot values replaced"},
            {"id": "merged-header", "tables": ["2-4"], "expected": "two-level header retained"},
            {"id": "multi-part", "tables": ["2-5"], "expected": "logical statistic with table part"},
            {"id": "language-pending", "tables": ["3-1", "3-2", "3-3"], "expected": "pending without language LLM; reviewed on rerun with language LLM"},
            {"id": "outlier", "tables": ["3-4"], "expected": "outlier candidate"},
            {"id": "metadata-missing", "tables": ["3-5"], "expected": "metadata review"},
            {"id": "llm-ambiguous-mapping", "tables": ["4-1", "4-2"], "sources": ["M-A-016", "M-A-017"], "expected": "review or conservative LLM-assisted connection"},
            {"id": "changed-structure", "tables": ["4-3"], "expected": "new profile and local revalidation"},
            {"id": "unchanged-reuse", "tables": ["1-1", "1-2", "4-4"], "expected": "reuse prior checks"},
            {"id": "increment-no-values", "tables": ["3-3"], "source": "M-V-013", "expected": "increment data insufficient"},
            {"id": "increment-format-mismatch", "tables": ["3-4"], "source": "M-V-014", "expected": "format mismatch"},
            {"id": "new-statistic-profile", "tables": ["5-1"], "source": "M-V-021", "expected": "deterministic c=a+b plus optional LLM ratio profile"},
            {"id": "deleted-statistic", "tables": ["4-5"], "source": "M-V-020", "expected": "deletion proposal reflected in draft"},
        ],
    }
    for case in cases["cases"]:
        if "tables" in case:
            case["tables"] = [annual_code(code) for code in case["tables"]]
    (OUTPUT / "fixture_manifest.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_markdown(OUTPUT / "virtual_yearbook_v1_2027.md", "2027 가상 통계연보 v1", v1_tables())
    write_markdown(OUTPUT / "virtual_yearbook_v2_2028.md", "2028 가상 통계연보 v2", v2_tables())
    write_increment_files()
    write_manifest()
    print(f"generated fixtures in {OUTPUT}")


if __name__ == "__main__":
    main()
