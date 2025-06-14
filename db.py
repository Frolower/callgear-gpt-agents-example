import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_initial_prompt(agent_mode: str) -> str:
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )
    cur = conn.cursor()
    query = "SELECT prompt FROM agent_prompts WHERE agent_mode = %s"
    cur.execute(query, (agent_mode,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else "Initial prompt not found"

def get_additional_prompt(value: int, mode: str) -> str:
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )
    cur = conn.cursor()
    if mode == "immigration":
        query = "SELECT prompt FROM prompts WHERE %s BETWEEN age_min AND age_max"
    elif mode == "financial":
        query = "SELECT prompt FROM prompts WHERE %s BETWEEN salary_min AND salary_max"
    cur.execute(query, (value,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else "Additional prompt not found"