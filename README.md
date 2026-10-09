# ooru_backend

Local PostgreSQL/PostGIS backend in `Documents/Projects/ooru/ooru_be`.
The frontend lives alongside it in `../ooru_fe`.

## Chat API (local prototype)

Add `GROQ_API_KEY` and `GROQ_MODEL` from `.env.example` to your existing `.env`.
Keep its database settings. Get a key from [Groq](https://console.groq.com/keys);
do not paste it into source code or chat. Requests send the message, supplied history
and location to Groq. No documents or database records are sent by this version.

From this backend folder:

```sh
uv sync --locked
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs in Chrome. Expand `POST /api/chat`, choose
**Try it out**, and send `{"message": "What is a ward?", "history": []}`.
Stop with Control+C; rerun the same command to restart (also after editing `.env`).
No database is needed for chat. `GET /health` checks only that the server is alive.

Read `app/modules/chat/schemas.py` → `route.py` → `service.py`.
The route delegates to `answer_chat()`, which makes one async model call and validates
the JSON answer and up to 3 follow-up questions. `llama-3.3-70b-versatile` is the initial
configurable model ([Groq example](https://console.groq.com/docs/quickstart)).

**Not yet grounded:** responses have `mode: "model_only"` and empty `sources`.
No RAG, live contacts, web search, saved conversations or frontend integration yet.
History is supplied by the caller; max 20 messages, 4,000 characters per message and
24,000 combined. Prompt rules are not a guarantee of factual accuracy.

Missing config/provider access/rate limits return 503, timeouts 504, invalid provider
responses 502, and invalid requests 422. Test without model calls: `uv run pytest -q`.
Local development only: add authentication and request rate limits before exposing it.

## Run

```sh
uv sync --locked
docker compose up -d
uv run python -m app.import_all
```

The runner imports corporations and wards, fetches roads only when
`resources/datasets/roads/bengaluru_roads.csv` is absent, then upserts roads in batches of 1,000.
Existing records are updated on reruns. Connection settings are in the local `.env`.

Models and importers live under `app/modules/commons` and `app/modules/roads`.
Alembic is not currently used. `create_all` creates missing tables but does not alter existing schemas.

## Existing database

Compose retains the `civic-backend` project identity and the external volume
`civic-backend_postgres_data` to preserve the existing database across the directory rename.
The existing volume must be present.

PostgreSQL is available on `localhost:55432`, database/user `ooru`.
Use the password from `.env` in PyCharm.

Open this folder in PyCharm and use `.venv/bin/python` as its interpreter.

## Ward map playground

```sh
uv run python -m playground.wards_map
uv run python -m http.server 8766 --bind 127.0.0.1 --directory playground
```

Open `http://127.0.0.1:8766/wards_map.html`.
