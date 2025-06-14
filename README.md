To run this project: 
1. Download requiered libraries using pip3 install -r requirements.txt
2. Create a .env file with the following fields:

OPENAI_API_KEY=
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
BACKEND_URL=
AGENT_ID=

3. Configure your db
4. Start a webhook server using uvicorn webhook_server:app --port 8000
5. Start a client server using uvicorn client_server:app --port 9000