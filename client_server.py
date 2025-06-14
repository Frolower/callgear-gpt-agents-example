import os
import json
import requests
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import openai
from db import get_initial_prompt, get_additional_prompt

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
AGENT_ID = os.getenv("AGENT_ID")
WEBHOOK_URL = os.getenv("BACKEND_URL")

app = FastAPI()

# Storing thread mode in memory (not a production level option)
THREAD_MODE = {}

# This class represents user input
class ChatRequest(BaseModel):
    thread_id: str | None = None
    content: str

# This class represents Assistant answer
class ChatResponse(BaseModel):
    thread_id: str
    reply: str

# Tool definitions for each agent
decision_tools = [
    {
        "type": "function",
        "function": {
            "name": "send_agent_mode",
            "parameters": {
                "type": "object",
                "required": ["agent_mode"],
                "properties": {
                    "agent_mode": {"type": "string", "enum": ["financial", "immigration"]}
                }
            }
        }
    }
]
immigration_tools = [
    {
        "type": "function",
        "function": {
            "name": "send_immigration_data",
            "parameters": {
                "type": "object",
                "required": ["name", "age", "country"],
                "properties": {
                    "name":    {"type": "string"},
                    "age":     {"type": "number"},
                    "country": {"type": "string"}
                }
            }
        }
    }
]
financial_tools = [
    {
        "type": "function",
        "function": {
            "name": "send_financial_data",
            "parameters": {
                "type": "object",
                "required": ["name", "position", "salary", "company"],
                "properties": {
                    "name":     {"type": "string"},
                    "position": {"type": "string"},
                    "salary":   {"type": "number"},
                    "company":  {"type": "string"}
                }
            }
        }
    }
]

# Extracts Agents response
def extract_assistant_text(msg):
    if not hasattr(msg, "content") or not msg.content:
        return ""
    for part in msg.content:
        if getattr(part, "type", "") == "text":
            return part.text.value
    return ""

# Helper function for get_latest_message_by_role
def get_created_at(msg):
    return msg.created_at

# Returns the latest message from the Agent
def get_latest_message_by_role(thread_id, roles=("assistant",)):
    msgs = openai.beta.threads.messages.list(thread_id=thread_id, limit=10).data
    msgs = sorted(msgs, key=get_created_at, reverse=True)
    for msg in msgs:
        if msg.role in roles:
            return msg
    return None

# Waits for OpenAI run to reach a final state
async def wait_for_run(thread_id, run_id, timeout=60):
    for _ in range(timeout):
        run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        if run.status in ("completed", "requires_action", "failed", "cancelled"):
            return run
        await asyncio.sleep(1)
    raise Exception("Run timeout")

# Returns tools for selected mode
def choose_tools(mode):
    if mode == "immigration":
        return immigration_tools
    if mode == "financial":
        return financial_tools
    return decision_tools

# Main API entrypoint
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        thread_id = req.thread_id or openai.beta.threads.create().id

        # Add user message to thread
        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=req.content
        )

        # Use mode from memory, if available
        mode = THREAD_MODE.get(thread_id)

        # If mode not set, run decision agent first
        if not mode:
            run = openai.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=AGENT_ID,
                tools=decision_tools,
                tool_choice="auto"
            )
            while True:
                run = await wait_for_run(thread_id, run.id)
                if run.status == "completed":
                    msg = get_latest_message_by_role(thread_id, roles=("assistant",))
                    return ChatResponse(
                        thread_id=thread_id,
                        reply=extract_assistant_text(msg) or "No reply"
                    )
                
                # Handling Agent function calls
                if run.status == "requires_action":
                    actions = run.required_action.submit_tool_outputs.tool_calls
                    outputs = []
                    for act in actions:
                        func = act.function.name
                        args = json.loads(act.function.arguments)
                        if func == "send_agent_mode":
                            mode = args.get("agent_mode")
                            THREAD_MODE[thread_id] = mode
                            prompt = get_initial_prompt(mode)
                            outputs.append({"tool_call_id": act.id, "output": json.dumps({"prompt": prompt})})
                        else:
                            outputs.append({"tool_call_id": act.id, "output": json.dumps({"prompt": "Unknown function called."})})
                    run = openai.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_outputs=outputs
                    )
                    continue

        # Mode is set, using specialized tools for that mode
        tools = choose_tools(mode)
        run = openai.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=AGENT_ID,
            tools=tools,
            tool_choice="auto"
        )
        while True:
            run = await wait_for_run(thread_id, run.id)
            if run.status == "completed":
                msg = get_latest_message_by_role(thread_id, roles=("assistant",))
                return ChatResponse(
                    thread_id=thread_id,
                    reply=extract_assistant_text(msg) or "No reply"
                )
            if run.status == "requires_action":
                actions = run.required_action.submit_tool_outputs.tool_calls
                outputs = []
                for act in actions:
                    func = act.function.name
                    args = json.loads(act.function.arguments)
                    if func == "send_immigration_data":
                        # Calling backend webhook
                        try:
                            requests.post(WEBHOOK_URL, json={
                                "agent_id": AGENT_ID,
                                "thread_id": thread_id,
                                "model": run.model,
                                "function": func,
                                "arguments": args
                            })
                        except Exception:
                            pass
                        prompt = get_additional_prompt(args.get("age"), "immigration")
                        outputs.append({"tool_call_id": act.id, "output": json.dumps({"prompt": prompt})})
                    elif func == "send_financial_data":
                        # Calling backend webhook
                        try:
                            requests.post(WEBHOOK_URL, json={
                                "agent_id": AGENT_ID,
                                "thread_id": thread_id,
                                "model": run.model,
                                "function": func,
                                "arguments": args
                            })
                        except Exception:
                            pass
                        prompt = get_additional_prompt(args.get("salary"), "financial")
                        outputs.append({"tool_call_id": act.id, "output": json.dumps({"prompt": prompt})})
                    else:
                        outputs.append({"tool_call_id": act.id, "output": json.dumps({"prompt": "Unknown function called."})})
                run = openai.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=outputs
                )
                continue

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))