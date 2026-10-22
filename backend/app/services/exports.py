import io
import re

from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.models import WeeklyReport

_REPL = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "•": "-", "→": "->"}


def _latin(s: str) -> str:
    for a, b in _REPL.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _inline(s: str) -> str:
    s = s.replace("`", "").replace("\\|", "|")
    s = re.sub(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)", r"\1", s)  # single *italic* -> plain
    s = re.sub(r"(?<![A-Za-z0-9])_([^_]+)_(?![A-Za-z0-9])", r"\1", s)  # _italic_ -> plain
    s = s.replace("--", "-")  # '--' means strike-through in fpdf2 markdown
    return _latin(s)


def report_filename(report: WeeklyReport, ext: str) -> str:
    who = report.employee.full_name if report.employee else (report.team.name if report.team else "team")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", who).strip("-").lower()
    return f"weekly-report-{slug}-{report.week_start.isoformat()}.{ext}"


def to_pdf(report: WeeklyReport) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    width = pdf.w - pdf.l_margin - pdf.r_margin
    lines = report.content_markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip())[1:-1]]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append([_inline(c) for c in cells])
                i += 1
            if rows:
                pdf.set_font("Helvetica", size=8)
                with pdf.table(text_align="LEFT", line_height=4.5, first_row_as_headings=True) as table:
                    for r in rows:
                        row = table.row()
                        for c in r:
                            row.cell(c)
                pdf.set_font("Helvetica", size=10)
                pdf.ln(2)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(width, 8, _inline(line[2:]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            pdf.ln(1)
        elif line.startswith("### ") or line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(width, 6, _inline(line.lstrip("# ")), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("> "):
            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(width, 4.5, _inline(line[2:]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("- "):
            pdf.multi_cell(width, 5, "  - " + _inline(line[2:]), markdown=True, new_x="LMARGIN", new_y="NEXT")
        elif not line.strip():
            pdf.ln(2)
        else:
            pdf.multi_cell(width, 5, _inline(line), markdown=True, new_x="LMARGIN", new_y="NEXT")
        i += 1
    return bytes(pdf.output())


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list]) -> None:
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="4F46E5")
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(60, max(10, width + 2))
        for c in col:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def to_xlsx(report: WeeklyReport) -> bytes:
    f = report.facts or {}
    wb = Workbook()
    summary = wb.active
    summary.title = "Report"
    summary.column_dimensions["A"].width = 120
    for line in report.content_markdown.splitlines():
        summary.append([line.replace("`", "")])
        if line.startswith("#"):
            summary.cell(summary.max_row, 1).font = Font(bold=True, size=13)

    if f.get("members"):
        _sheet(
            wb,
            "Members",
            ["Employee", "Goals", "Completed", "In progress", "Blocked", "Updates", "Expected", "Hours reported"],
            [
                [m["name"], m["goals_total"], m["goals_completed"], m["goals_in_progress"], m["goals_blocked"],
                 m["reporting"]["reported_days"], m["reporting"]["expected_days"], m["time"]["total_reported_hours"]]
                for m in f["members"]
            ],
        )
    _sheet(
        wb,
        "Goals",
        ["Ref", "Owner", "Title", "Expected outcome", "Status", "Progress %", "Health", "Deadline", "Carried from"],
        [
            [g["ref"], g.get("owner"), g["title"], g.get("expected_outcome"), g["status"], g["progress_percent"],
             g["health"], g.get("deadline"), g.get("carried_from")]
            for g in f.get("goals", [])
        ],
    )
    _sheet(
        wb,
        "Work items",
        ["Ref", "Date", "Project", "Goal", "Task", "Title", "Status", "Type", "Hours", "Unplanned"],
        [
            [i["ref"], i["date"], i.get("project"), i.get("goal"), i.get("task"), i["title"], i["status"], i["kind"],
             i.get("hours"), "yes" if i.get("unplanned") else ""]
            for i in f.get("work_items", [])
        ],
    )
    _sheet(wb, "Blockers", ["Ref", "Date", "Blocker"], [[b["ref"], b["date"], b["text"]] for b in f.get("blockers", [])])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
