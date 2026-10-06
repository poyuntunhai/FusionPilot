import os


JAVA_BASE_URL = os.getenv("JAVA_BASE_URL", "http://localhost:8080").rstrip("/")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8000"))