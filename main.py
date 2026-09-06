from app.api.application import app


@app.get("/health")
def health():
    return {"status": "ok"}
