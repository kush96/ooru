# ooru_backend

Local PostgreSQL/PostGIS backend in `Documents/Projects/ooru/ooru_be`.
The frontend lives alongside it in `../ooru_fe`.

## Chat API (local prototype)

Add `GROQ_API_KEY` to your existing `.env`; keep its database settings. Optional
`LLM_BASE_URL` and `LLM_MODEL` are shown in `.env.example` (replaces `GROQ_MODEL`).
Default: Groq `openai/gpt-oss-120b`, low reasoning effort. Listed price checked
9 October 2026: $0.15 input / $0.60 output per million tokens
([Groq models](https://console.groq.com/docs/models)). This is a starting choice,
not a measured accuracy claim. Get a key from [Groq](https://console.groq.com/keys).
Keys stay in `.env`. Model calls send the supplied prompt/context, not local documents.

From this backend folder:

```sh
uv sync --locked
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs in Chrome and choose **Try it out**:

- `POST /api/chat/authority-intent`: `{"prompt": "Who maintains the road outside my house?"}`.
  Returns `needs_authority_lookup` (boolean) and a short `reason`. One model call;
  no authority names or document search. It classifies this prompt alone, not chat history.
- `POST /api/chat`: `{"message": "What is a ward?", "history": []}`.
  Existing model-only chat, kept separate; it does not automatically run the classifier yet.

Stop with Control+C; rerun the same command to restart (also after editing `.env`).
No database is needed for chat. `GET /health` checks only that the server is alive.

### Code map

- `app/config.py`: typed settings, loaded once from this backend's `.env`.
- `app/clients/llm.py`: `LLMClient(settings)` sends requests and validates model JSON.
- `app/modules/chat/route.py` → `chat_service.py` → `tools/authority_intent.py`: endpoint,
  workflow, then classification instructions. The tool calls the shared client.
- `app/dependencies.py`: all service/repository/client wiring. Routes use its
  factories through FastAPI `Depends`; the import runner passes its DB session.
- Routes unpack request models; `ChatService` receives `message`, `history`,
  `location_name`, or just `prompt` for classification. No HTTP request object.
- `app/modules/chat/schemas.py`: chat request/response shapes.
- `app/main.py`: startup, routes and shared HTTP error handling.

There is no chat repository: no stored data is being read or written yet.
Existing database repositories stay in their own modules. A positive intent is not
proof that our resources contain an answer.

### Configuration

Pydantic Settings validates URLs, output mode and numeric limits at startup.
Environment variables override `.env`; missing optional values use the defaults in
`app/config.py`. API keys and the database URL are masked in settings displays.
Chat can start without a database or API key; model calls need the key.
`DATABASE_URL` is required only when running the import/map scripts.
Restart after changing `.env`. See `.env.example` for available settings.

**Self-host later:** change `LLM_BASE_URL`, `LLM_MODEL`, and optionally `LLM_API_KEY`
to your OpenAI-compatible server. A Groq key is never automatically sent to another host.
For servers without JSON-schema support, set `LLM_JSON_MODE=json_object`; Pydantic
still validates the output. Compatibility must be tested with your chosen server/model.

**Not yet grounded:** responses have `mode: "model_only"` and empty `sources`.
No RAG, live contacts, web search, saved conversations or frontend integration yet.
History is supplied by the caller; max 20 messages, 4,000 characters per message and
24,000 combined. Prompt rules are not a guarantee of factual accuracy.

Malformed settings stop startup with a validation error. Missing model credentials,
provider access problems or rate limits return 503, timeouts 504, invalid provider
responses 502, and invalid requests 422. Test without model calls: `uv run pytest -q`.
Opt-in quality check (16 real calls, may cost money):
`RUN_LIVE_LLM_TESTS=1 uv run pytest tests/test_authority_intent_live.py -q`.
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

`app/import_all.py` gets `BoundaryService` and `RoadService` from `app/dependencies.py`, then calls
their `import_data()` methods. They live in `commons/boundary_service.py` and
`roads/road_service.py` under `app/modules`. Repositories receive a database session
in their constructors; services receive those repositories. `RoadService` also
receives the session for batch transactions and an `OsmClient` for fetching roads.
No generic CRUD base or extra dependency-injection framework is needed.
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
