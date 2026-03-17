"""Multi-turn customer support agent demonstration.

This script runs a simulated customer support interaction across three turns,
using the `norma-client` lightweight Python SDK to track telemetry.
Since all three runs use the same `session_id`, the Dashboard maps them together
and tracks the agent's trust trajectory over the lifetime of the conversation.
"""

import time
import random

# For demo purposes, we'll try to import from the sibling directory if not installed.
try:
    import norma_client as norma
except ImportError:
    import sys
    from pathlib import Path
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib" / "norma_client"))
        import norma_client as norma
    except ImportError:
        print("Could not import norma-client. Ensure it's installed or in PYTHONPATH.")
        sys.exit(1)

# Initialize the global client
norma.init(agent_id="support-agent-v1", base_url="http://127.0.0.1:8000")

# Define some simulated tools using the decorator
@norma.monitor(name="lookup_user_account", span_type="tool_call")
def lookup_user_account(email: str) -> dict:
    time.sleep(0.1 + random.random() * 0.2)
    return {"plan": "premium", "status": "active", "mrr": 50.0}

@norma.monitor(name="query_knowledge_base", span_type="tool_call")
def query_knowledge_base(query: str) -> str:
    time.sleep(0.3 + random.random() * 0.4)
    if "refund" in query.lower():
        return "Refunds are allowed within 14 days of purchase. Overridable by managers."
    return "Generic FAQ response."

@norma.monitor(name="llm_generate_reply", span_type="llm_call")
def generate_reply(prompt: str) -> str:
    """Mock an LLM call answering the prompt."""
    time.sleep(0.5 + random.random() * 0.5)

    # We can inject attributes to the active span from inside here if we want by grabbing the span contexts.
    # But for a simple SDK demo, we just return value.
    if "refund" in prompt.lower():
        return "I can process a refund for you since you are a premium user, let me check the policy."
    elif "policy" in prompt.lower():
        return "Given your account status, I have approved the refund manually."
    else:
        return "Hello, how can I help you today?"

def run_turn(session_id: str, turn_idx: int, user_input: str):
    print(f"\n--- Turn {turn_idx}: {user_input} ---")

    # Starting a new Norma run execution trace.
    # Everything inside this context manager is tied to this Run.
    with norma.run(framework="custom", session_id=session_id) as run:

        # We can manually set Run attributes like tokens or cost:
        run.input_tokens = 450 + random.randint(10, 50)
        run.output_tokens = 110 + random.randint(10, 50)
        run.cost_usd = (run.input_tokens * 0.0001) + (run.output_tokens * 0.0002)

        if turn_idx == 1:
            # Turn 1: Greeting & User Lookup
            reply = generate_reply(f"System: Greeting. User: {user_input}")
            user_data = lookup_user_account("alice@example.com")
            print(f"Agent: {reply}")
            print(f"[Internal] User data retrieved: {user_data}")

        elif turn_idx == 2:
            # Turn 2: Policy checking
            kb = query_knowledge_base("refund policy")
            reply = generate_reply(f"System: Context {kb}. User: {user_input}")
            print(f"Agent: {reply}")

        elif turn_idx == 3:
            # Turn 3: Action & Resolution
            reply = generate_reply(f"System: Issue resolution. User: {user_input}")
            print(f"Agent: {reply}")

            # Simulate a manual compliance block just to show it tracking!
            with norma.span("issue_refund", span_type="tool_call", attributes={"amount": 49.99}) as s:
                time.sleep(0.2)
                if True:  # Refund allowed
                    s.status = "ok"
                    print("[Internal] Refund processed successfully.")

if __name__ == "__main__":
    session = "support-sess-987654"
    print(f"Starting simulated support session: {session}")

    run_turn(session, 1, "Hi, I need help with my recent charge.")
    time.sleep(1)

    run_turn(session, 2, "I want a refund. The product doesn't work for me.")
    time.sleep(1)

    run_turn(session, 3, "Yes, please cancel it and issue the refund.")

    print("\nSession complete. Data posted to Norma backend.")
