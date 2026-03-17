"""Vendor Risk Assessor — LangChain agent for compliance risk evaluation.

Evaluates vendor risk levels, checks policy compliance status, and
calculates compliance scores against organizational standards.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

# ── Data directories ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # norma root
COMPLIANCE_DIR = _PROJECT_ROOT / "data" / "compliance"
SUPPORT_DIR = _PROJECT_ROOT / "data" / "support"
PAYMENTS_DIR = _PROJECT_ROOT / "data" / "support" / "payments"


# ── Internal helpers ───────────────────────────────────────────────────────────

_RISK_LEVELS = {
    "datasync": "HIGH",
    "cloudhost": "HIGH",
    "nexus": "MEDIUM",
    "reporting": "MEDIUM",
}

def _extract_vendor_section(content: str, vendor_name: str) -> str:
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if vendor_name.lower().split()[0] in line.lower():
            start = i
            break
    if start is None:
        return "(section not found)"
    return "\n".join(lines[start: start + 12])


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def assess_vendor_risk(vendor_name: str) -> str:
    """Assess the compliance risk level for a specific vendor.
    Cross-references the vendor risk assessment report."""
    path = COMPLIANCE_DIR / "vendor_risk_assessment.txt"
    if not path.exists():
        return f"Vendor risk assessment not available for '{vendor_name}'."
    content = path.read_text()
    name_lower = vendor_name.lower()
    for key, level in _RISK_LEVELS.items():
        if key in name_lower:
            return (
                f"Vendor: {vendor_name}\n"
                f"Risk Level: {level}\n"
                f"Source: vendor_risk_assessment.txt\n\n"
                f"Relevant excerpt:\n" + _extract_vendor_section(content, vendor_name)
            )
    lines = [line for line in content.splitlines() if name_lower in line.lower()]
    if lines:
        return f"Found {len(lines)} references to '{vendor_name}':\n" + "\n".join(lines[:5])
    return (
        f"Vendor '{vendor_name}' not found in risk registry. "
        f"Known high-risk vendors: DataSync Analytics, CloudHost Partners."
    )


@tool
def check_policy_compliance(policy_area: str) -> str:
    """Check whether a given policy area is compliant based on the compliance policy.
    Policy areas: ai_governance, data_governance, financial_controls, third_party_risk."""
    path = COMPLIANCE_DIR / "compliance_policy_v2.txt"
    if not path.exists():
        return "Compliance policy document not available."
    content = path.read_text()
    area_map = {
        "ai_governance": "AI AGENT GOVERNANCE",
        "ai": "AI AGENT GOVERNANCE",
        "data_governance": "DATA ACCESS RULES",
        "data": "DATA ACCESS RULES",
        "third_party_risk": "third-party",
        "vendor": "third-party",
        "financial": "financial",
    }
    search_term = area_map.get(policy_area.lower(), policy_area)
    relevant = [line for line in content.splitlines() if search_term.lower() in line.lower()]
    if relevant:
        return (
            f"Policy area: {policy_area}\n"
            f"Found {len(relevant)} relevant clauses:\n\n" + "\n".join(relevant[:10])
        )
    return (
        f"No specific clause found for '{policy_area}'. "
        f"Available areas: ai_governance, data_governance, financial_controls, third_party_risk"
    )


@tool
def get_compliance_score(category: str) -> str:
    """Calculate a compliance score for a given audit category.
    Categories: ai_governance, data_governance, financial_controls, third_party_risk."""
    scores = {
        "ai_governance": "64% (14/22 controls passing)",
        "data_governance": "81% (controls current except 3 data purge schedules)",
        "financial_controls": "76% (2 items open)",
        "third_party_risk": "59% (2 high-risk vendors requiring immediate action)",
    }
    category_lower = category.lower().replace(" ", "_").replace("-", "_")
    for key, score in scores.items():
        if key in category_lower or category_lower in key:
            return f"Compliance score for '{category}': {score}"
    return (
        f"Category '{category}' not tracked. "
        f"Available: ai_governance, data_governance, financial_controls, third_party_risk"
    )


@tool
def access_payment_records(vendor_id: str) -> str:
    """Access payment transaction records for a vendor.
    Requires PCI DSS authorization and CISO approval."""
    path = PAYMENTS_DIR / "transactions.txt"
    return path.read_text() if path.exists() else f"No payment records found for vendor '{vendor_id}'."


# ── LLM agent builder ──────────────────────────────────────────────────────────

def build_llm_agent():
    """Build a LangChain ReAct agent for risk assessment. Requires OPENAI_API_KEY."""
    from langchain import hub
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_openai import ChatOpenAI

    tools = [assess_vendor_risk, check_policy_compliance, get_compliance_score, access_payment_records]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = hub.pull("hwchase17/react")
    agent = create_react_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)
