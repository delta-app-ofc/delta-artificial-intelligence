"""
Fábrica de modelos de IA generativa usados pelos agentes do Projeto Delta.

Diretriz do projeto: a escola NÃO custeia nenhuma API de IA generativa paga.
Por isso, priorizamos modelos com camada gratuita (Gemini free tier, Groq
free tier). Cada papel (agente rápido / agente especialista) tem seu próprio
modelo, com fallback automático caso o provedor principal falhe ou estoure
cota gratuita — ver `with_fallbacks` abaixo.

Este arquivo só monta os clientes LLM. Prompts ficam em prompts.py. Cada
agente (app/agents/*.py) importa daqui o modelo que precisa.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import GEMINI_API_KEY, GROQ_API_KEY

# ==============================================================================
# MODELO "ESPECIALISTA" — usado por agentes que precisam de mais raciocínio
# (ex.: Vazamento, Previsão, RAG, Juiz). Gemini como principal, Groq como
# fallback gratuito caso o Gemini falhe ou estoure a cota do dia.
# ==============================================================================
llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    top_p=0.95,
    api_key=GEMINI_API_KEY,
)

llm_groq_especialista = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.3,
    api_key=GROQ_API_KEY,
)

llm_especialista = llm_gemini.with_fallbacks([llm_groq_especialista])

# ==============================================================================
# MODELO "RÁPIDO" — usado para tarefas curtas e baratas: roteamento auxiliar,
# extração de intenção, formatação de saída (ex.: Agente Consumo, que faz
# poucas consultas estruturadas e não precisa de muito raciocínio).
# ==============================================================================
llm_rapido = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.0,
    api_key=GROQ_API_KEY,
)

# ==============================================================================
# MODELO DE EMBEDDINGS — usado pelo Agente RAG para indexar/consultar a fonte
# externa (ver app/tools/rag_retriever.py). Mantido separado dos LLMs de chat.
# ==============================================================================
EMBEDDING_MODEL_NAME = "gemini-embedding-2-preview"

# ==============================================================================
# PENDENTE DE DECISÃO (ver documentação de arquitetura, seção 20 e 24):
# - Qual modelo será usado pelo Agente Juiz: pode valer a pena usar o mesmo
#   `llm_especialista` com temperature=0 para reduzir variância na revisão.
# - Se o time optar por outro provedor gratuito (ex.: DeepSeek, modelo local
#   via Ollama), adicionar aqui como mais uma opção de fallback.
# ==============================================================================
