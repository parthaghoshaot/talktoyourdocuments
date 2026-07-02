import os
import logging
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TALKTODATA_HOME = os.getenv("TALKTODATA_HOME", "").strip()


def resolve_env_path():
    if TALKTODATA_HOME:
        return os.path.join(TALKTODATA_HOME, ".env")
    return os.path.join(PROJECT_ROOT, ".env")


def resolve_documents_dir():
    explicit = os.getenv("DOCUMENTS_DIR", "").strip()
    if explicit:
        return explicit
    if TALKTODATA_HOME:
        return os.path.join(TALKTODATA_HOME, "documents")
    return PROJECT_ROOT


def resolve_db_path():
    explicit = os.getenv("DB_PATH", "").strip()
    if explicit:
        return explicit
    if TALKTODATA_HOME:
        return os.path.join(TALKTODATA_HOME, "knowledge.db")
    return os.path.join(PROJECT_ROOT, "knowledge.db")


def ensure_runtime_paths(documents_dir, db_path):
    os.makedirs(documents_dir, exist_ok=True)
    db_parent = os.path.dirname(db_path)
    if db_parent:
        os.makedirs(db_parent, exist_ok=True)


ENV_PATH = resolve_env_path()
load_dotenv(ENV_PATH)

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

DOCUMENTS_DIR = resolve_documents_dir()
DB_PATH = resolve_db_path()
ensure_runtime_paths(DOCUMENTS_DIR, DB_PATH)
logger.info(f"Runtime paths: env={ENV_PATH}, documents={DOCUMENTS_DIR}, db={DB_PATH}")

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


def llm_describe_image(image_bytes, mime_type="image/png", context=""):
    import base64
    client = get_llm_client()
    prompt = (
        "Describe this image in detail for knowledge extraction. "
        "Include all text, labels, data, relationships, and visual structure. "
        "If it's a diagram or chart, describe the entities and connections."
    )
    if context:
        prompt += f" Context from surrounding document: {context[:500]}"

    logger.info(f"Vision LLM call -> provider={LLM_PROVIDER}")

    if LLM_PROVIDER in ("openai", "ollama"):
        model = OPENAI_MODEL if LLM_PROVIDER == "openai" else OLLAMA_MODEL
        b64 = base64.b64encode(image_bytes).decode()
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ]}]
        response = client.chat.completions.create(model=model, messages=msgs, temperature=0.2, max_tokens=1000)
        return response.choices[0].message.content

    elif LLM_PROVIDER == "gemini":
        from google.genai.types import Part
        b64 = base64.b64encode(image_bytes).decode()
        parts = [prompt, Part(inline_data={"mime_type": mime_type, "data": b64})]
        response = client.models.generate_content(model=GEMINI_MODEL, contents=parts)
        return response.text

    return ""
