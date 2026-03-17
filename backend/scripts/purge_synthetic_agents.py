"""One-shot script to purge the 3 seeded synthetic agents from the DB."""
import asyncio
from norma.database import AsyncSessionLocal
from sqlalchemy import text

SYNTHETIC_IDS = [
    "financial-report-agent-v1",
    "research-pipeline-v1",
    "support-triage-v1",
]


async def purge() -> None:
    async with AsyncSessionLocal() as db:
        for agent_id in SYNTHETIC_IDS:
            await db.execute(
                text("DELETE FROM violations WHERE run_id IN (SELECT id FROM runs WHERE agent_id = :aid)"),
                {"aid": agent_id},
            )
            await db.execute(
                text("DELETE FROM violations WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
            await db.execute(
                text("DELETE FROM contracts WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
            await db.execute(
                text("DELETE FROM runs WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
            result = await db.execute(
                text("DELETE FROM agents WHERE agent_id = :aid"),
                {"aid": agent_id},
            )
            print(f"{agent_id}: deleted {result.rowcount} agent row(s)")
        await db.commit()
    print("Purge complete.")


asyncio.run(purge())
