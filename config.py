import os
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("talktodata")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://yourendpoint.net")
LLM_API_VERSION = os.getenv("LLM_API_VERSION", "2024-10-21")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge.db"))

_llm_client = None


def get_llm_client():
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    logger.info(f"Initializing LLM client: provider={LLM_PROVIDER}")

    if LLM_PROVIDER == "openai":
        import openai
        _llm_client = openai.AzureOpenAI(
            api_version=LLM_API_VERSION,
            azure_endpoint=LLM_BASE_URL,
            api_key=LLM_API_KEY,
        )
    elif LLM_PROVIDER == "gemini":
        from google import genai
        from google.genai.types import HttpOptions
        _llm_client = genai.Client(
            http_options=HttpOptions(base_url=LLM_BASE_URL),
            api_key=LLM_API_KEY,
        )
    elif LLM_PROVIDER == "ollama":
        from openai import OpenAI
        _llm_client = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")

    return _llm_client


def llm_chat(messages, system_prompt=None):
    client = get_llm_client()
    user_msg = messages[-1]["content"][:100] if messages else ""
    logger.info(f"LLM call -> provider={LLM_PROVIDER}, prompt_preview='{user_msg}...'")

    if LLM_PROVIDER in ("openai", "ollama"):
        model = OPENAI_MODEL if LLM_PROVIDER == "openai" else OLLAMA_MODEL
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)
        response = client.chat.completions.create(model=model, messages=msgs, temperature=0.3)
        usage = response.usage
        if usage:
            logger.info(f"LLM response <- tokens: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")
        else:
            logger.info("LLM response <- (no token usage reported)")
        return response.choices[0].message.content

    elif LLM_PROVIDER == "gemini":
        contents = []
        if system_prompt:
            contents.append(system_prompt + "\n\n")
        for msg in messages:
            role = "User" if msg["role"] == "user" else "Assistant"
            contents.append(f"{role}: {msg['content']}\n")
        contents.append("Assistant:")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents="".join(contents),
        )
        usage = getattr(response, "usage_metadata", None)
        if usage:
            logger.info(f"LLM response <- tokens: prompt={getattr(usage, 'prompt_token_count', '?')}, completion={getattr(usage, 'candidates_token_count', '?')}, total={getattr(usage, 'total_token_count', '?')}")
        else:
            logger.info("LLM response <- (no token usage reported)")
        return response.text
