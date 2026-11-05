import os

from fastapi import FastAPI

from mermia_api.agent import llm

llm.setup_tracing(os.environ)  # Langfuse traces of LLM calls; off when its variables are missing

app = FastAPI(title="MermIA API")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for Render and uptime monitors."""
    return {"status": "ok"}
