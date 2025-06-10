import openai
import os
import time
import json
import requests
from dotenv import load_dotenv
from db import get_additional_prompt

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

DECISION_AGENT_ID = os.getenv("DECISION_AGENT_ID")
IMMIGRATION_AGENT_ID = os.getenv("IMMIGRATION_AGENT_ID")
FINANCIAL_AGENT_ID = os.getenv("FINANCIAL_AGENT_ID")
BACKEND_URL = os.getenv("BACKEND_URL")

# defining a function schema for OpenAI function calling
FUNCTIONS = [
    {
        "function": {
            "name": "send_user_info",
            "description": "Send all collected user data as key-value pairs in the data object",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "object",
                        "description": "Any fields collected from the user based on a prompt."
                    }
                },
                "required": []
            }
        },
        "type": "function"
    }
]

# helper function to extract values from agent-created json
def extract_value(data, key):
    if key in data:
        return data[key]
    for v in data.values():
        if isinstance(v, dict) and key in v:
            return v[key]
    return None

# helper function that waits until a run is over
def wait_for_completion(thread_id, run_id):
    while True:
        run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        if run.status in ["completed", "failed", "cancelled", "requires_action"]:
            return run
        time.sleep(1)

# running agent logic like response, webhook sending process, receiving additional prompt from the db
def process_run(thread_id, run, agent_id, mode):
    system_prompt_added = False
    while True:
        run = wait_for_completion(thread_id, run.id)
        if run.status == "requires_action":
            tool_call = run.required_action.submit_tool_outputs.tool_calls[0]
            args = json.loads(tool_call.function.arguments)

            # assembling a webhook
            payload = {
                "meta": {
                    "run_id": run.id,
                    "thread_id": thread_id,
                    "tool_call_id": tool_call.id,
                    "assistant_id": agent_id,
                    "model": run.model,
                    "mode": mode
                },
                "body": args
            }
            response = requests.post(BACKEND_URL, json=payload)
            system_reply = response.json()
            content = system_reply.get("content", "")

            openai.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=[{
                    "tool_call_id": tool_call.id,
                    "output": content
                }]
            )
            wait_for_completion(thread_id, run.id)

            # going to db for an extra prompt
            value = None

            if mode == "immigration":
                value = extract_value(args, "age")
            elif mode == "financial":
                value = extract_value(args, "salary")
            if value is not None and not system_prompt_added:
                try:
                    prompt = get_additional_prompt(int(value), mode)
                    if prompt and "does not exist" not in prompt.lower():
                        openai.beta.threads.messages.create(
                            thread_id=thread_id,
                            role="assistant",
                            content=f"CONSIDER THESE INSTRUCTIONS TO FURTHER ASSIST THE USER {prompt}"
                        )
                        print(f"\nsystem prompt added to thread:\n{prompt}\n")
                        system_prompt_added = True
                        run = openai.beta.threads.runs.create(
                            thread_id=thread_id,
                            assistant_id=agent_id,
                            tools=FUNCTIONS,
                            tool_choice="auto",
                            response_format="auto"
                        )
                        continue  # starting a new run with an extra prompt
                except Exception as e:
                    print("DB Error:", e)
            # if no custom prompt found in the DB or already added, continue the normal agent run
            run = openai.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=agent_id,
                tools=FUNCTIONS,
                tool_choice="auto",
                response_format="auto"
            )
        else:
            break

    # printing last response
    messages = openai.beta.threads.messages.list(thread_id=thread_id)
    latest = messages.data[0]
    print(f"{latest.role.capitalize()}: {latest.content[0].text.value}")

# running main chat starting with decision agent
def start_chat():
    thread = openai.beta.threads.create()
    print("Hello! How can I help you today?")

    decision_confirmed = False
    seen = set()

    # running decision agent until user is routed to the appropriate specialized agent
    while not decision_confirmed:
        user_input = input("User: ")
        openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_input
        )
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=DECISION_AGENT_ID,
            tools=FUNCTIONS,
            tool_choice="auto",
            response_format="auto"
        )
        wait_for_completion(thread.id, run.id)

        # checking if decision has been made
        for msg in openai.beta.threads.messages.list(thread_id=thread.id).data:
            if msg.id in seen:
                continue
            seen.add(msg.id)
            if msg.role == "assistant" and msg.content:
                text = msg.content[0].text.value.strip().lower()
                print(f"Decision Agent: {msg.content[0].text.value.strip()}")
                if "route_to: immigration" in text:
                    agent_id, mode = IMMIGRATION_AGENT_ID, "immigration"
                    decision_confirmed = True
                    break
                if "route_to: financial" in text:
                    agent_id, mode = FINANCIAL_AGENT_ID, "financial"
                    decision_confirmed = True
                    break

    # triggering a correct agent
    openai.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content="..."
    )
    run = openai.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=agent_id,
        tools=FUNCTIONS,
        tool_choice="auto",
        response_format="auto"
    )
    process_run(thread.id, run, agent_id, mode)

    # collecting appropriate data with a specialized agent
    while True:
        user_input = input("User: ")
        if user_input.strip().lower() == "exit":
            break

        openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_input
        )
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=agent_id,
            tools=FUNCTIONS,
            tool_choice="auto",
            response_format="auto"
        )
        process_run(thread.id, run, agent_id, mode)

if __name__ == "__main__":
    start_chat()