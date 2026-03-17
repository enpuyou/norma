"""Three demo workflows — each tests a primary norma.ai capability."""

from norma.workflows.workflow1_financial import FinancialReportAgent
from norma.workflows.workflow2_research import ResearchPipeline
from norma.workflows.workflow3_support import SupportTriagePipeline

__all__ = ["FinancialReportAgent", "ResearchPipeline", "SupportTriagePipeline"]
