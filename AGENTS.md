# Agent Guidelines — Exterior House Renovation System

This document specifies the operational rules, architectural constraints, and engineering conventions for all AI agents working in this codebase.

---

## 1. Core Architectural Constraints

1. **One Monolithic Process:**
   - Single FastAPI backend serving JSON endpoints under `/api/...` and static frontend files under `/`.
   - Never introduce secondary servers, microservices, background job queues (Redis/Celery), or worker daemons for this project.
2. **SQLite Database:**
   - Single database file using standard library `sqlite3` with parameterized SQL.
   - No ORMs (SQLAlchemy, Tortoise, etc.) are permitted.
   - Always enforce pragmas: `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = WAL;`, `PRAGMA busy_timeout = 5000;`.
3. **Vanilla Frontend:**
   - Pure HTML5, CSS, and vanilla ES modules in `frontend/`.
   - Never add npm, webpack, Vite, React, Vue, Tailwind CLI, or any build step.
4. **Deterministic Costing:**
   - All quantities, deductions, wastage allowances, and costs are computed strictly in Python (`cost_service.py`).
   - LLMs and AI vision models **must never** output final prices, quantities, or financial totals.
5. **Separation of AI Capabilities:**
   - Vision detection and image redesign are two distinct model invocations sharing the same `GEMINI_API_KEY`.
   - Vision detection model: configured via `GEMINI_VISION_MODEL` (`gemini-3.8-flash`).
   - Redesign model: configured via `NANO_BANANA_IMAGE_MODEL` (`gemini-3.1-flash-image`).
6. **User Protection Guarantee:**
   - Re-running AI detection must **never** overwrite user-modified or user-drawn components (`is_locked = 1`).
   - An AI estimate must never overwrite a user-entered measurement (`source = 'user'`).

---

## 2. Coding and Design Conventions

### Layered Backend Structure
- `api/` — Route handlers only: parse request, call one service, return schema. Never contain raw SQL.
- `services/` — Business logic and cross-repository coordination. Raise typed `AppError` exceptions.
- `repositories/` — Raw parameterized SQL queries mapping rows to dicts. Handle database integrity exceptions.
- `core/` — Infrastructure: database connection, atomic storage, configuration, logging, and error types.
- `schemas/` — Pydantic v2 models. Use `extra = "forbid"` on all request schemas.

### API & Error Handling
- All endpoints must adhere strictly to `docs/specs/02-api-contracts.md`.
- All errors must return the standard JSON envelope:
  ```json
  {
    "error": {
      "code": "ERROR_CODE",
      "message": "Human-readable message",
      "details": {},
      "request_id": "req_..."
    }
  }
  ```
- Every response must include security and tracing headers:
  - `X-Request-ID: req_...`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`

### File Storage Security
- All filesystem storage under `storage/` must pass through `StorageManager` in `core/storage.py`.
- Path traversal protection is strictly required: always resolve paths and verify they reside inside `STORAGE_ROOT`.

---

## 3. Verification Commands (Windows PowerShell)

Before submitting changes, always execute the following tests:

```powershell
# 1. Run all tests
python -m unittest discover -s backend/tests

# 2. Start server in development mode
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

