from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from norma.database import Base

class ComplianceReport(Base):
    __tablename__ = "compliance_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    critical_issues_count = Column(Integer, default=0, nullable=False)
    agents_monitored = Column(Integer, default=0, nullable=False)
