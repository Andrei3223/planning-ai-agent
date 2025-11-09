from pprint import pprint

from langchain.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage

from agent.agentkit.graph import agent
if __name__ == "__main__":

    agent.invoke(
        {
            "messages": [HumanMessage(content="(system cron) please refresh the events catalog")],
            "user_id": "system",
            "llm_calls": 0,
        },
    )

    # Alex: send preferences and availability
    out1 = agent.invoke(
        {
            "messages": [
                HumanMessage(content="Hey! I like sport and tech meetups. I'm free on 2025-11-10 from 18:00 to 21:00.")
            ],
            "user_id": "telegram_id",
            "llm_calls": 0,
        },
    )

    pprint(out1['messages'][-1].content)  # check the suggested events