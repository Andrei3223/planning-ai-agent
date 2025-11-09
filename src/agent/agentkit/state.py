import operator

from typing import List
from typing_extensions import TypedDict, Annotated

# LangChain / LangGraph
from langchain.messages import AnyMessage

class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], operator.add]
    user_id: str
    llm_calls: int