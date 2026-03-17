"""Human-in-the-loop approval showcase agent.

This agent attempts a high-risk action (like transferring funds or dropping a database table).
To demonstrate norma's AgentPausedError, the tool pauses the agent by setting `enabled = False` in the database,
then raises `AgentPausedError`.

The norma dashboard UI will then allow a human to resume or abort the pending action by re-enabling the agent.
"""

import time
import sqlite3
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# We use the local norma backend imports to manipulate the agent state and raise the error.
from norma.integrations.session_core import AgentPausedError
from norma.models.agent import Agent

# For this demo, we'll talk directly to the SQLite DB to pause the agent mid-execution.
# In a real app, this might be a dashboard API call or a framework-level feature.
DB_URL = "sqlite:///backend/test.db"

class HighRiskTransferInput(BaseModel):
    amount: float = Field(..., description="Amount to transfer")
    destination: str = Field(..., description="Destination account")

@tool("transfer_funds", args_schema=HighRiskTransferInput)
def transfer_funds(amount: float, destination: str) -> str:
    """Transfer funds to a destination account. A high-risk action requiring human approval."""

    agent_id = "approval-showcase-v1"

    # Check if the agent is currently enabled. If it is enabled, we pause it to request approval.
    import sqlalchemy
    from sqlalchemy.orm import sessionmaker

    # We strip the sqlite:/// prefix for standard sqlite3 connections, or just use SQLAlchemy
    engine = sqlalchemy.create_engine("sqlite:///test.db") # using typical path
    Session = sessionmaker(bind=engine)

    with Session() as db:
        agent = db.get(Agent, agent_id)
        if not agent:
            return "Error: Agent not found in DB."

        if agent.enabled:
            # First time running: pause the agent and throw AgentPausedError
            agent.enabled = False
            db.commit()
            print(f"[Agent] High-risk action detected. Pausing agent '{agent_id}' for human approval.")
            raise AgentPausedError(agent_id=agent_id)
        else:
            # We are here but enabled is False? Wait, if we are here and enabled=True -> we pause.
            pass

    # If we get past the session_core enabled check, it means a human has re-enabled the agent
    # to approve the action. We can process the transfer.
    time.sleep(1)
    return f"Successfully transferred ${amount:.2f} to {destination}."

# The ALL_TOOLS list is discovered by norma when executing the agent via the dashboard.
ALL_TOOLS = [transfer_funds]

# Simple contract that allows the tool but doesn't block it (so we hit the tool code).
CONTRACT_YAML = """
name: "Human-in-the-Loop Contract"
version: "1.0"
authorities:
  tools:
    allow:
      - "transfer_funds"
"""
