from fastapi import FastAPI

app = FastAPI(title="MermIA API")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for Render and uptime monitors."""
    return {"status": "ok"}
