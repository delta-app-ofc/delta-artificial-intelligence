"""Runner manual do chat com guardrails e Agente Juiz.

Uso: python manual_chat_judge.py [--user-id ID] [--session-id ID] [--no-history]
Requer as dependências do projeto, credenciais dos provedores e dados reais acessíveis.
--no-history pula gravações Mongo; leituras de contexto e tools continuam no fluxo.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app.agents.judge import SAFE_RESPONSE
from app.config import get_settings
from app.guardrails.input import validate_input
from app.guardrails.output import validate_output
from app.graph.workflow import run_workflow
from app.memory.session import append_turn


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conversa manual com o Delta e o Agente Juiz.")
    parser.add_argument("--user-id", type=int, help="ID do usuário; sem a opção, o runner pergunta.")
    parser.add_argument("--session-id", help="Reutiliza uma sessão deste usuário; o padrão cria uma nova.")
    parser.add_argument("--no-history", action="store_true", help="Não grava turnos no MongoDB.")
    return parser.parse_args()


def _read_user_id(value: int | None) -> int:
    while value is None or value <= 0:
        try:
            value = int(input("ID do usuário Delta: ").strip())
        except ValueError:
            print("Digite um número inteiro positivo.")
            value = None
    return value


def _run_question(user_id: int, session_id: str, question: str, no_history: bool) -> None:
    guard = validate_input(user_id, question)
    if not guard["ok"]:
        print("Entrada bloqueada: " + guard["reason"])
        return

    try:
        state = run_workflow(user_id, session_id, guard["message"], persist_session=False)
    except Exception:
        print("Fluxo indisponível. Resposta segura: " + SAFE_RESPONSE)
        return

    history = state.get("judge_history", [])
    approved = False
    if history:
        print("\n=== Julgamento ===")
        for number, entry in enumerate(history, start=1):
            judge = entry["judge"]
            confidence = judge["confidence"]
            confidence_text = f"{confidence:.0%}" if confidence is not None else "não disponível"
            print(
                f"{number}. decisão={judge['decision']}; status={judge['status']}; "
                f"confiança da gravidade={confidence_text}; gravidade={judge['severity']}"
            )
            diagnostics = judge.get("assessment", {}).get("diagnostics", {})
            if diagnostics:
                checks = diagnostics["checks"]
                quality = diagnostics["quality"]
                quality_label = quality["legend"].get(
                    str(int(quality["score"])), str(quality["score"])
                )
                print(
                    "   Subcritérios Jev: "
                    f"suporte factual={diagnostics['facts_supported']:.0%} "
                    f"({'passou' if checks['facts_supported'] else 'falhou'}); "
                    f"relevância={diagnostics['relevant']:.0%} "
                    f"({'passou' if checks['relevant'] else 'falhou'}); "
                    f"qualidade={quality_label} "
                    f"({'passou' if checks['quality'] else 'falhou'})"
                )
            elif judge.get("status") == "evaluated":
                print("   Noul/Score não consultados: o gate principal não passou.")
            print("   Códigos Python: " + ", ".join(judge["reason_codes"]))
            print("   Justificativa Python: " + judge["justification"])
        final_judge = history[-1]["judge"]
        approved = final_judge["status"] == "evaluated" and final_judge["decision"] == "approve"
    elif state.get("composition_status") in {"no_agents", "no_success"}:
        print("Sem candidata para julgar; usando a resposta segura do fluxo.")

    print(f"Agente(s): {', '.join(state.get('selected_agents', [])) or 'nenhum'}")
    print(f"Revisões: {state.get('revision_count', 0)}")

    output = validate_output(state.get("response", ""), guard.get("pii_map", {}))
    fallback = state.get("composition_status") in {"no_agents", "no_success"} and not history
    if not output["ok"]:
        print("Guardrail de saída bloqueou o texto.")
        response, may_save = SAFE_RESPONSE, False
    elif approved or fallback:
        response, may_save = output["response"], True
    else:
        response, may_save = SAFE_RESPONSE, False

    if may_save and not no_history:
        try:
            append_turn(session_id, user_id, "human", question)
            append_turn(session_id, user_id, "assistant", response)
        except Exception:
            print("Aviso: não foi possível salvar o histórico MongoDB desta sessão.")
    elif may_save:
        print("Histórico não gravado (--no-history).")

    print("\n=== Resposta final ===")
    print(response)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()  # APP_ENV=test faz o settings ignorar o arquivo .env.
    args = _parse_args()
    user_id = _read_user_id(args.user_id)
    session_id = args.session_id or str(uuid.uuid4())

    print(f"Ambiente: {settings.app_env} | Sessão: {session_id}")
    print("Digite perguntas sobre o Delta; Enter vazio encerra.")
    while True:
        try:
            question = input("\nVocê: ")
        except (EOFError, KeyboardInterrupt):
            print("\nRunner encerrado.")
            break
        if not question.strip():
            break
        _run_question(user_id, session_id, question, args.no_history)


if __name__ == "__main__":
    main()
