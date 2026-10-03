"""Orquestrador LangGraph do Delta AI.

Nós: route → forecast | leak | habits → END
O nó route usa llm_rapido para classificar a intenção.
Checkpointer MemorySaver mantém histórico de thread_id por sessão.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.graph.state import GraphState


def _route_node(state: GraphState) -> GraphState:
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.services.llms import llm_rapido

    classify = llm_rapido.invoke(
        [
            SystemMessage(
                content=(
                    "Classifique a intenção do usuário em exatamente uma das palavras: "
                    "previsao, vazamento, habitos, desconhecido. "
                    "Responda SOMENTE com a palavra, sem pontuação."
                )
            ),
            HumanMessage(content=state["question"]),
        ]
    )
    intent = classify.content.strip().lower() if hasattr(classify, "content") else "desconhecido"
    valid = {"previsao", "vazamento", "habitos"}
    return {**state, "agent_used": intent if intent in valid else "desconhecido"}


def _forecast_node(state: GraphState) -> GraphState:
    from app.agents.forecast import ForecastAgent

    agent = ForecastAgent(user_id=state["user_id"])
    result = agent.run(state["question"])
    return {**state, "response": result.response, "chart_data": result.chart_data}


def _leak_node(state: GraphState) -> GraphState:
    from app.agents.leak import LeakAgent

    agent = LeakAgent(user_id=state["user_id"])
    result = agent.run(state["question"])
    return {**state, "response": result.response, "chart_data": result.chart_data}


def _habits_node(state: GraphState) -> GraphState:
    from app.agents.habits import HabitsAgent

    agent = HabitsAgent(user_id=state["user_id"])
    result = agent.run(state["question"])
    return {**state, "response": result.response, "chart_data": result.chart_data}


def _unknown_node(state: GraphState) -> GraphState:
    return {
        **state,
        "response": (
            "Não entendi o que você gostaria de saber. Posso ajudar com "
            "previsão de consumo, detecção de vazamentos ou seus hábitos de água."
        ),
    }


def _decide(state: GraphState) -> str:
    return state.get("agent_used", "desconhecido")


_graph = StateGraph(GraphState)

_graph.add_node("route", _route_node)
_graph.add_node("forecast", _forecast_node)
_graph.add_node("leak", _leak_node)
_graph.add_node("habits", _habits_node)
_graph.add_node("unknown", _unknown_node)

_graph.set_entry_point("route")

_graph.add_conditional_edges(
    "route",
    _decide,
    {
        "previsao": "forecast",
        "vazamento": "leak",
        "habitos": "habits",
        "desconhecido": "unknown",
    },
)

_graph.add_edge("forecast", END)
_graph.add_edge("leak", END)
_graph.add_edge("habits", END)
_graph.add_edge("unknown", END)

_memory = MemorySaver()
workflow = _graph.compile(checkpointer=_memory)


def run_workflow(user_id: int, session_id: str, question: str) -> GraphState:
    initial: GraphState = {
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "response": "",
        "agent_used": "",
        "chart_data": None,
    }
    result = workflow.invoke(
        initial,
        config={"configurable": {"thread_id": session_id}},
    )
    return result
