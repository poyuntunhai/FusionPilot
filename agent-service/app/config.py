import os

from dotenv import load_dotenv


load_dotenv()

JAVA_BASE_URL = os.getenv("JAVA_BASE_URL", os.getenv("JAVA_API_BASE_URL", "http://localhost:8080")).rstrip("/")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8000"))
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "rule").strip().lower()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip()
MODEL_API_BASE_URL = os.getenv("MODEL_API_BASE_URL", "").strip()
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "").strip()
MODEL_TIMEOUT_SECONDS = float(os.getenv("MODEL_TIMEOUT_SECONDS", "45"))
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.2"))
MODEL_FALLBACK_TO_RULE = os.getenv("MODEL_FALLBACK_TO_RULE", "true").lower() == "true"
# Where the domain knowledge corpus lives. Empty means the bundled `agent-service/knowledge`.
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "").strip()
