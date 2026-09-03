"""
Modelos de IA generativa usados pelos agentes.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import GEMINI_API_KEY, GROQ_API_KEY

# Especialista — usado por agentes que precisam de mais raciocínio. 
# Gemini como principal;
# Groq como fallback gratuito caso o Gemini falhe ou estoure a cota do dia.
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

# Rápido — usado para tarefas curtas e baratas: roteamento auxiliar,
# extração de intenção, formatação de saída.
llm_rapido = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.0,
    api_key=GROQ_API_KEY,
)

# Embedding — usado pelo Agente RAG para indexar a fonte externa.
EMBEDDING_MODEL_NAME = "gemini-embedding-2-preview"