from fastapi import FastAPI

app = FastAPI(title="character_chat_local")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
