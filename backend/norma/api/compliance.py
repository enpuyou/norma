from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from norma.core.compliance.engine import ComplianceEngine
from norma.core.compliance.rule import ComplianceContext
from norma.database import get_db
from norma.models.agent import Agent
from norma.models.contract import Contract
from norma.models.run import Run
from norma.models.span import Span
from norma.models.compliance_report import ComplianceReport
from pydantic import BaseModel

router = APIRouter()


def _pdf_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.encode("latin-1", "replace").decode("latin-1")


async def _load_context(agent_id: str, db: AsyncSession, run_id: int | None = None) -> ComplianceContext:
    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run_stmt = select(Run).where(Run.agent_id == agent_id).order_by(Run.id.desc()).limit(100)
    if run_id is not None:
        run_stmt = select(Run).where(Run.id == run_id, Run.agent_id == agent_id)
    runs_result = await db.execute(run_stmt)
    runs = list(runs_result.scalars().all())

    if run_id is not None and not runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run_ids = [r.id for r in runs]
    spans: list[Span] = []
    if run_ids:
        spans_result = await db.execute(select(Span).where(Span.trace_id.in_(run_ids)).order_by(Span.id.asc()))
        spans = list(spans_result.scalars().all())

    contract_result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id, Contract.is_active == True)  # noqa: E712
        .order_by(Contract.id.desc())
    )
    active_contract = contract_result.scalar_one_or_none()

    return ComplianceContext(
        agent_id=agent_id,
        runs=runs,
        spans=spans,
        active_contract=active_contract,
    )


@router.post("/evaluate")
async def evaluate_compliance(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    agent_id = payload.get("agent_id")
    run_id = payload.get("run_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="agent_id is required")

    ctx = await _load_context(agent_id=agent_id, db=db, run_id=run_id)
    result = ComplianceEngine().evaluate(ctx)
    out = result.to_dict()
    out["scope"] = "run" if run_id is not None else "agent"
    out["run_id"] = run_id
    return out


@router.get("/{agent_id}/posture")
async def get_compliance_posture(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    ctx = await _load_context(agent_id=agent_id, db=db, run_id=None)
    result = ComplianceEngine().evaluate(ctx)
    payload = result.to_dict()

    by_standard: dict[str, dict] = {}
    for f in payload["findings"]:
        row = by_standard.setdefault(
            f["standard"],
            {"total": 0, "passed": 0, "failed": 0},
        )
        row["total"] += 1
        if f["passed"]:
            row["passed"] += 1
        else:
            row["failed"] += 1

    return {
        "agent_id": agent_id,
        "passed": payload["passed"],
        "summary": payload["summary"],
        "by_standard": by_standard,
        "findings": payload["findings"],
    }


@router.get("/{agent_id}/export/pdf")
async def export_compliance_pdf(agent_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    """Export a compliance posture report in PDF format."""
    posture = await get_compliance_posture(agent_id=agent_id, db=db)

    try:
        from fpdf import FPDF  # type: ignore
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="PDF export requires fpdf2 dependency",
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, _pdf_text(f"norma.ai Compliance Report - {agent_id}"), ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 7, _pdf_text(f"Overall status: {'PASS' if posture.get('passed') else 'FAIL'}"), ln=True)
    pdf.cell(0, 7, _pdf_text(f"Summary: {posture.get('summary', '')}"), ln=True)
    pdf.ln(2)

    by_standard = posture.get("by_standard", {}) or {}
    if by_standard:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Standards Overview", ln=True)
        pdf.set_font("Helvetica", size=10)
        for standard, row in by_standard.items():
            pdf.cell(
                0,
                6,
                _pdf_text(
                    f"{standard}: {row.get('passed', 0)}/{row.get('total', 0)} passed, {row.get('failed', 0)} failed"
                ),
                ln=True,
            )
        pdf.ln(2)

    findings = posture.get("findings", []) or []
    if findings:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Rule Findings", ln=True)
        pdf.set_font("Helvetica", size=9)
        for finding in findings:
            status = "PASS" if finding.get("passed") else "FAIL"
            line = f"[{status}] {finding.get('standard', 'N/A')} {finding.get('rule_id', '')} - {finding.get('message', '')}"
            pdf.multi_cell(0, 5, _pdf_text(line))
            pdf.ln(1)

    pdf_bytes = bytes(pdf.output(dest="S"))
    filename = f"{agent_id}-eu-ai-act-compliance.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

class ReportPayload(BaseModel):
    report_text: str
    critical_issues_count: int
    agents_monitored: int

@router.post("/reports")
async def save_fleet_report(payload: ReportPayload, db: AsyncSession = Depends(get_db)):
    """Save a new Sentinel compliance report."""
    report = ComplianceReport(
        report_text=payload.report_text,
        critical_issues_count=payload.critical_issues_count,
        agents_monitored=payload.agents_monitored,
    )
    db.add(report)
    await db.commit()
    return {"status": "ok", "id": report.id}

@router.get("/reports")
async def get_fleet_reports(db: AsyncSession = Depends(get_db)):
    """Get the latest 20 Sentinel compliance reports."""
    result = await db.execute(
        select(ComplianceReport).order_by(ComplianceReport.id.desc()).limit(20)
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "report_text": r.report_text,
            "timestamp": r.timestamp.isoformat() + "Z",
            "critical_issues_count": r.critical_issues_count,
            "agents_monitored": r.agents_monitored,
        }
        for r in reports
    ]
