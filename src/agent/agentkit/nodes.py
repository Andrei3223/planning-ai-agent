import json
from typing import List, Literal

from pydantic import ValidationError

# LangChain / LangGraph
from langchain.messages import SystemMessage, ToolMessage, AIMessage
from langgraph.graph import END

# custom imports 
from .state import AgentState
from .model import llm 
from .tools import TOOLS, TOOLS_BY_NAME
from .debug_logger import log_state

# Model Setup 
llm_with_tools = llm.bind_tools(TOOLS)

ASSISTANT_SYSTEM_PROMPT = (
    "You are an event planning assistant.\n"
    "Your responsibilities:\n"
    "- Extract user preferences about events (e.g. sport, music, meetups, tech).\n"
    "- Extract the user's busy dates and durations.\n"
    "- Keep the data in sync by calling tools that update the database.\n"
    "- Suggest events that match a single user's profile when asked.\n"
    "- Suggest events that multiple users can join together when asked.\n"
    "- Allow casual small talk and conversation when the user just chats.\n\n"
    "TOOLS USAGE GUIDELINES:\n"
    "- When the user tells you about what they like and when they are free,\n"
    "  call `update_user_profile_db` with the active telegram_id and the extracted data.\n"
    "- When they ask for events for themselves, call `get_personal_event_suggestions_db`.\n"
    "- When they ask for events with someone else (e.g. \"me and u_alex\"),\n"
    "  call `get_joint_event_suggestions_db` with a list of all relevant telegram_ids.\n"
    "- Use `refresh_events_catalog` if the user asks you to refresh the events.\n"
    "- If the user only wants a casual chat, you can reply directly without calling tools.\n\n"
    "IMPORTANT:\n"
    "- The active telegram_id for this conversation is provided separately; you are told it explicitly.\n"
    "- When you call tools that require a telegram_id for the current user, ALWAYS use that exact string.\n"
)


async def assistant_node(state: AgentState):
    """Main LLM reasoning step: decides whether to call tools or just chat."""
    telegram_id = state["telegram_id"]

    system = SystemMessage(
        content=ASSISTANT_SYSTEM_PROMPT
        + f"\nThe active telegram_id for this conversation is '{telegram_id}'."
    )

    conversation = [system] + state["messages"]

    log_state("ASSISTANT_NODE INPUT", {"telegram_id": telegram_id, "messages_count": len(state["messages"])})

    ai_msg: AIMessage = await llm_with_tools.ainvoke(conversation)  # ✅ Use ainvoke

    log_state("ASSISTANT_NODE OUTPUT", {"content": ai_msg.content, "tool_calls": getattr(ai_msg, "tool_calls", None)})

    return {
        "messages": [ai_msg],
        "llm_calls": state["llm_calls"] + 1,
    }


# Change tool_node to async and await the tools
async def tool_node(state: AgentState):
    """Executes any tools requested by the last AIMessage."""
    last = state["messages"][-1]
    log_state("TOOL_NODE INPUT", {"last_message_type": type(last).__name__})

    tool_messages: List[ToolMessage] = []

    for tc in getattr(last, "tool_calls", []) or []:
        tool = TOOLS_BY_NAME[tc["name"]]
        try:
            result = await tool.ainvoke(tc["args"])  # ✅ CORRECT
        except ValidationError as e:
            result = {"error": str(e)}
        except Exception as e:
            result = {"error": f"Tool {tc['name']} failed: {e}"}

        content = json.dumps(result, ensure_ascii=False)
        tm = ToolMessage(content=content, tool_call_id=tc["id"])
        tool_messages.append(tm)

    log_state("TOOL_NODE OUTPUT", {"tool_messages_count": len(tool_messages)})

    return {"messages": tool_messages}


def should_continue(state: AgentState) -> Literal["tools", END]:
    """If the last AI message has tool calls, go to tool node; otherwise, end."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END

