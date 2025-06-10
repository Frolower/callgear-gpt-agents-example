import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_additional_prompt(value: int, mode: str):

    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )
    cur = conn.cursor()

    if mode == "immigration":
        query = """
            SELECT prompt FROM prompts
            WHERE %s BETWEEN age_min AND age_max
        """
    elif mode == "financial":
        query = """
            SELECT prompt FROM prompts
            WHERE %s BETWEEN salary_min AND salary_max
        """
    else:
        conn.close()
        return "Unknown agent type"

    cur.execute(query, (value,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    return result[0] if result else "Corresponding prompt does not exist"