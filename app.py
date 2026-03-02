"""Agentic Day2 Routing - Main application entry point."""

from typing import TypedDict, Annotated
from operator import add
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


class SupportState(TypedDict):
    # Required fields
    messages: Annotated[list[BaseMessage], add]
    should_escalate: bool
    issue_type: str
    user_tier: str  # "vip" or "standard"
    # Extra fields
    priority: str  # "high", "medium", "low"
    resolution_status: str  # "pending", "resolved", "escalated"
    agent_notes: str  # internal notes from agent


def route_by_tier(state: SupportState) -> str:
    """Route based on user tier."""
    if state.get("user_tier") == "vip":
        return "vip_path"
    return "standard_path"


def check_user_tier_node(state: SupportState) -> dict:
    """Decide if user is VIP or standard. Also infers issue_type and priority."""
    first_message = state["messages"][0].content.lower()
    # Keyword-based mock for tier
    if "vip" in first_message or "premium" in first_message:
        tier = "vip"
    else:
        response = llm.invoke([
            SystemMessage(content="""Classify the customer tier from this message.
Return ONLY 'vip' or 'standard'. VIP = premium/long-time/paying/enterprise. Standard = everyone else."""),
            HumanMessage(content=first_message),
        ])
        tier = response.content.strip().lower()
        tier = "vip" if tier == "vip" else "standard"

    # Infer issue_type and priority in one call
    classify_resp = llm.invoke([
        SystemMessage(content="""From this support message, return EXACTLY two words separated by space:
1) issue type: shipping, billing, technical, general, or other
2) priority: high, medium, or low
Example: shipping medium"""),
        HumanMessage(content=first_message),
    ])
    parts = (classify_resp.content or "general medium").strip().lower().split()
    issue_type = parts[0] if parts else "general"
    priority = parts[1] if len(parts) > 1 else "medium"
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    return {
        "user_tier": tier,
        "issue_type": issue_type,
        "priority": priority,
        "resolution_status": "pending",
    }


def vip_agent_node(state: SupportState) -> dict:
    """VIP path: fast lane, no escalation. LLM generates personalized response."""
    user_msg = state["messages"][-1].content
    response_messages = [
        SystemMessage(content="""You are a senior VIP support agent. Be warm, personalized, and efficient.
You handle premium customers with priority. No escalation needed. Keep response to 2-3 sentences."""),
        HumanMessage(content=user_msg),
    ]
    response = llm.invoke(response_messages)
    return {
        "should_escalate": True,
        "messages": [AIMessage(content=response.content)],
        "resolution_status": "escalated",
        "agent_notes": f"VIP handled. Issue: {state.get('issue_type', 'general')}. Priority: {state.get('priority', 'medium')}.",
    }


def standard_agent_node(state: SupportState) -> dict:
    """Standard path: may escalate. LLM generates response and decides escalation."""
    user_msg = state["messages"][-1].content
    # LLM decides escalation from message content
    escalation_prompt = [
        SystemMessage(content="""Decide if this support request needs escalation.
Return ONLY 'yes' or 'no'. Escalate for: legal threats, manager request, repeated failures, urgent/critical."""),
        HumanMessage(content=user_msg),
    ]
    escalation_resp = llm.invoke(escalation_prompt)
    should_escalate = escalation_resp.content.strip().lower().startswith("y")

    response_messages = [
        SystemMessage(content="""You are a customer support agent. Be helpful and professional.
If escalating, mention a specialist will follow up. Keep response to 2-3 sentences."""),
        HumanMessage(content=user_msg),
    ]
    response = llm.invoke(response_messages)
    resolution_status = "escalated" if should_escalate else "pending"
    agent_notes = f"Standard path. Issue: {state.get('issue_type', 'general')}. Escalation: {should_escalate}."
    return {
        "should_escalate": should_escalate,
        "messages": [AIMessage(content=response.content)],
        "resolution_status": resolution_status,
        "agent_notes": agent_notes,
    }


def build_graph():
    """Build and return the compiled StateGraph workflow."""
    workflow = StateGraph(SupportState)
    workflow.add_node("check_tier", check_user_tier_node)
    workflow.add_node("vip_agent", vip_agent_node)
    workflow.add_node("standard_agent", standard_agent_node)
    workflow.set_entry_point("check_tier")
    workflow.add_conditional_edges(
        "check_tier",
        route_by_tier,
        {
            "vip_path": "vip_agent",
            "standard_path": "standard_agent",
        },
    )
    workflow.add_edge("vip_agent", END)
    workflow.add_edge("standard_agent", END)
    return workflow.compile()


def main() -> None:
    graph = build_graph()

    vip_result = graph.invoke({
        "messages": [HumanMessage(content="I'm a VIP customer, please check my order")],
        "should_escalate": False,
        "issue_type": "",
        "user_tier": "",
        "priority": "",
        "resolution_status": "",
        "agent_notes": "",
    })
    print("VIP result:", vip_result.get("user_tier"), vip_result.get("should_escalate"))

    standard_result = graph.invoke({
        "messages": [HumanMessage(content="Check my order status")],
        "should_escalate": False,
        "issue_type": "",
        "user_tier": "",
        "priority": "",
        "resolution_status": "",
        "agent_notes": "",
    })
    print("Standard result:", standard_result.get("user_tier"), standard_result.get("should_escalate"))


if __name__ == "__main__":
    main()
