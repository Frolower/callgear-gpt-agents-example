from fastapi import FastAPI, Request
import json

app = FastAPI()

@app.post("/agent-entrypoint")
async def agent_entrypoint(request: Request):
    payload = await request.json()
    print(f"Webhook payload: {json.dumps(payload, indent=2)}")
    return {"content": "Data successfully received"}