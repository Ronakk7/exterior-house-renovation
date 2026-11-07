# 05 - AI Integration

**Purpose:** everything specific to the two Google Gemini integrations: the Vision integration (component detection, and later AI-assisted dimension estimates) and the Image-generation integration "Nano Banana" (redesign). Both use the **same Google Gemini API account and the same `GEMINI_API_KEY`**, but are separate model calls with separate model identifiers, interfaces, timeouts and failure behaviour.
**Depends on:** `02-api-contracts.md` (error codes), `04-backend-foundation.md` (config, errors, logging, layout).
**Used by:** `07` (detection), `10` (redesign), `11` (AI-assisted estimate).
**Does not define:** what is asked of the models. Detection prompts are in `07`; redesign prompts in `10`; estimate prompts in `11`. This file defines how calls are made, validated, retried and failed.

---

## 1. Two integrations, one shared foundation

| | Vision integration | Image-generation integration (Nano Banana) |
|---|---|---|
| Purpose | Read an image, return **structured JSON** | Take an image and instructions, return an **edited image** |
| Used for | Detection (`07`), AI-assisted estimates (`11`) | Redesign (`10`) |
| Model setting | `GEMINI_VISION_MODEL` | `NANO_BANANA_IMAGE_MODEL` |
| Model identifiers chosen by the team | `gemini-3.8-flash` | `gemini-3.1-flash-image` |
| Timeout setting | `AI_DETECTION_TIMEOUT_S` (default 60) | `AI_IMAGE_TIMEOUT_S` (default 120) |
| Output | Parsed and schema-validated JSON | Image bytes plus MIME type |
| Retries | Yes (section 6) | No automatic retry (section 6) |
| Shared | API key, error mapping, working-image preparation, logging, mock mode, concurrency cap | same |

**Model identifiers are configuration, never code.** `.env.example` ships with the two identifiers above as values. Google's current model documentation lists both identifiers, but M0 (section 12) must verify that the configured key can call them and that the required request and response behavior works before any feature depends on them. If a model is renamed or unavailable, only the environment value changes.

**SDK and API surface.** Use the official Python Google GenAI SDK (`google-genai`) and its `google.genai.Client` / `client.models.generate_content(...)` API for both integrations. Do not mix in the Interactions API or a hand-built REST request. Both clients use the same configured API key and the same GenerateContent request/response model; only the model and generation config differ. The official SDK reference is <https://googleapis.github.io/python-genai/>.

Import the SDK as `from google import genai` and `from google.genai import types`. `types.Part.from_bytes(...)` creates the inline image input part; the SDK handles encoding for the GenerateContent request.

## 2. Module layout (inside `services/ai/`, per `04` section 2)

| Module | Responsibility |
|--------|----------------|
| `provider.py` | Builds the authenticated provider client from settings; maps provider failures to `AIError` codes; applies the concurrency cap and deadline logic |
| `image_prep.py` | Creates the in-memory **working image** sent to models (section 4) |
| `vision.py` | The Vision interface (section 5.1) |
| `image_gen.py` | The Image-generation interface (section 5.2) |
| `json_validation.py` | Parses the SDK's JSON response text and validates it against the top-level Pydantic model |
| `mock.py` | Mock implementations of both interfaces (section 9) |
| `__init__.py` | `get_vision_client(settings)` and `get_image_client(settings)` factories: return the mock when `AI_MOCK_MODE` is true, otherwise the real client |

Feature services depend only on the two interfaces below, never on provider objects. Replacing the provider or the model touches only this package.

## 3. Configuration (all from `04` section 4)

Used here: `GEMINI_API_KEY`, `GEMINI_VISION_MODEL`, `NANO_BANANA_IMAGE_MODEL`, `AI_MOCK_MODE`, `AI_WORKING_IMAGE_MAX_PX`, `AI_DETECTION_TIMEOUT_S`, `AI_IMAGE_TIMEOUT_S`, `AI_MAX_RETRIES`, `LOG_LEVEL`.

**Readiness rule.** `ai_configured` (reported by `/api/health`) is true when mock mode is on, or when the key and both model identifiers are non-empty. No live provider call is made by health checks. When not configured, each factory returns a client whose methods raise `AI_NOT_CONFIGURED` immediately.

**Fixed constants (code, not configuration):**

| Constant | Value | Meaning |
|----------|-------|---------|
| `MAX_CONCURRENT_AI_CALLS` | 4 | Process-wide cap on simultaneous provider calls (semaphore). Extra calls wait for a slot; waiting counts against the call's deadline. |
| `RETRY_MIN_REMAINING_S` | 15 | A retry starts only if at least this much of the deadline remains |
| `WORKING_JPEG_QUALITY` | 85 | Quality for JPEG working images |

## 4. Working image preparation (`image_prep.py`)

Original photos are never sent as stored. Each AI call receives a **working image** built in memory from the stored original.

| Step | Rule |
|------|------|
| 1 | Read the original bytes via the storage helper (`04` section 6) |
| 2 | Decode; apply EXIF orientation so the image is upright |
| 3 | Convert to RGB (flatten transparency onto white) |
| 4 | If the longest side exceeds `AI_WORKING_IMAGE_MAX_PX`, downscale proportionally (high-quality resampling). Never upscale. |
| 5 | Encode as JPEG at `WORKING_JPEG_QUALITY` with **no metadata** (EXIF, GPS removed) |

Returns: `{ bytes, mime_type: "image/jpeg", width_px, height_px, scale_factor }`.

Guarantees:
- Aspect ratio is preserved exactly (rounded to whole pixels).
- All box coordinates in this project are **normalized**, so a model working on the downscaled image yields coordinates that apply unchanged to the original and to the browser display.
- Working images are not stored on disk. Only their size and byte count are logged.
- Failure to decode raises an internal error (the file was validated at upload, so this indicates a corrupted store) and surfaces as `INTERNAL_ERROR`.

## 5. Interfaces

### 5.1 Vision interface

Conceptual signature:

```
analyze_image(
    image:        WorkingImage,
    instructions: text            # the full prompt, assembled by the calling feature
    schema:       validation model # the expected JSON shape
    prompt_version: text          # e.g. "det-v2", recorded in logs and stage runs
    timeout_s:    number          # defaults to AI_DETECTION_TIMEOUT_S
) -> VisionResult
```

`VisionResult` contains:

| Field | Meaning |
|-------|---------|
| `data` | The parsed, schema-validated object |
| `attempts` | 1 or 2 |
| `duration_ms` | Total wall time including retry |
| `model_name` | The identifier used |
| `raw_text_excerpt` | First 1000 characters of the final raw model text, for debugging only (never returned to clients) |

Behaviour:
1. For each attempt, after acquiring a concurrency slot, calculate the remaining deadline in milliseconds and create/use an authenticated `genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=remaining_ms))`. Call `client.models.generate_content(model=GEMINI_VISION_MODEL, contents=[types.Part.from_bytes(data=image.bytes, mime_type=image.mime_type), instructions], config=types.GenerateContentConfig(response_mime_type="application/json"))`. This SDK call uses the Gemini `models/{model}:generateContent` API. Do not send a `response_schema`: detection must allow unvalidated values in `components` so one malformed component does not invalidate the envelope (`07` section 7). The `schema` argument is enforced locally after JSON parsing.
2. Do not set `temperature`, `top_p`, `top_k`, or other sampling parameters. In particular, [Gemini 3.8 Flash migration guidance](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8) requires deprecated sampling parameters such as `temperature` to be removed.
3. Parse `response.prompt_feedback.block_reason` and the first candidate's `finish_reason` before content. Map a prompt block or safety/prohibited-content finish reason to `AI_CONTENT_BLOCKED`; absent candidates without a block, missing text, or other unusable response content is `AI_INVALID_RESPONSE`. For a valid candidate, concatenate its text parts in order, parse that text directly as JSON (the request asked for JSON MIME; do not strip prose or code fences), then validate the top-level object against `schema` with extra fields forbidden.
4. On JSON parsing or top-level schema validation failure, apply the retry rule (section 6) once with a corrective suffix appended to the instructions: *"Your previous reply was not valid JSON matching the required schema. Reply again with only the JSON object."* Domain-specific per-item validation is owned by the feature spec and does not trigger a retry when the envelope is valid.
5. Apply the remaining call deadline to the SDK HTTP timeout; time spent waiting for a concurrency slot and parsing/validation remains inside the overall deadline.
6. Raise `AIError` per section 7 on any other failure.

### 5.2 Image-generation interface

Conceptual signature:

```
edit_image(
    image:        WorkingImage,
    instructions: text            # the full prompt, assembled by spec 10
    prompt_version: text
    timeout_s:    number          # defaults to AI_IMAGE_TIMEOUT_S
) -> ImageResult
```

`ImageResult`:

| Field | Meaning |
|-------|---------|
| `image_bytes` | The generated image |
| `mime_type` | Reported or sniffed type |
| `width_px`, `height_px` | Decoded dimensions |
| `duration_ms` | Wall time |
| `model_name` | Identifier used |
| `text_note` | Any accompanying text the model returned (truncated to 500 chars), for debugging |

Behaviour:
1. Calculate the remaining deadline in milliseconds and create/use an authenticated `genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=remaining_ms))`. Call the same `client.models.generate_content(...)` API with `model=NANO_BANANA_IMAGE_MODEL`, `contents=[instructions, types.Part.from_bytes(data=image.bytes, mime_type=image.mime_type)]`, and `config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"], image_config=types.ImageConfig(image_size="1K"))`. The explicit response modalities allow the image model to return the image and optional explanatory text; `1K` is the required initial output resolution. This selects the documented default 1K tier explicitly and does not make the output dimensions a guarantee ([model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)).
2. Parse `response.prompt_feedback.block_reason` and the first candidate's `finish_reason` before its parts. Map a prompt block or safety/prohibited/image-safety finish reason to `AI_CONTENT_BLOCKED`; no candidate or no image without a block or refusal text is `AI_INVALID_RESPONSE`.
3. Iterate the candidate's `content.parts` in order. Retain the first part with `inline_data` whose MIME type is an image as `image_bytes` and `mime_type`; `inline_data.data` is already decoded by the SDK and must not be base64-decoded again. Collect text parts in order and truncate their joined text to 500 characters for `text_note`. Ignore subsequent image parts. If text indicates a refusal, map it to `AI_CONTENT_BLOCKED`.
4. Verify the selected bytes decode as an image with both sides at least 256 px; otherwise raise `AI_INVALID_RESPONSE`.
5. Do **not** crop, resize or convert the result. Aspect-ratio restoration and PNG storage belong to `10`.
6. Do not retry automatically (section 6).

For either integration, map SDK transport timeouts to `AI_TIMEOUT`. For `google.genai.errors.APIError`, inspect its HTTP status/code: 429 maps to `AI_RATE_LIMITED`, 5xx and network failures to `AI_UPSTREAM_ERROR`, and authentication/permission failures (401/403) to `AI_UPSTREAM_ERROR`. Do not expose the SDK exception message to the client; log only the bounded provider detail allowed by section 8.

The prompt content, structure-preservation wording, handling of unsupported components and the generation record belong to `10`.

## 6. Retry, timeout and deadline rules

Each operation has a **deadline** equal to its timeout setting, measured from the moment the call is requested. The deadline includes waiting for a concurrency slot, all attempts and validation. Server deadlines are below the frontend timeouts in `03` section 7 by 15 seconds.

| Failure | Vision | Image generation |
|---------|--------|------------------|
| Invalid JSON or schema violation | Retry once (with corrective suffix) if `AI_MAX_RETRIES` >= 1 and `RETRY_MIN_REMAINING_S` remains, else `AI_INVALID_RESPONSE` | n/a |
| Provider 5xx or network error | Retry once, same conditions; else `AI_UPSTREAM_ERROR` | No retry; `AI_UPSTREAM_ERROR` |
| Rate limit or quota (HTTP 429 or equivalent) | No retry; `AI_RATE_LIMITED` | No retry; `AI_RATE_LIMITED` |
| Deadline exceeded | `AI_TIMEOUT` (no retry) | `AI_TIMEOUT` (no retry) |
| Authentication or permission rejected (invalid key, model not accessible) | No retry; `AI_UPSTREAM_ERROR` and an `ERROR` log naming the cause | same |
| Safety block, prompt rejected, or no usable candidate | No retry; `AI_CONTENT_BLOCKED` | No retry; `AI_CONTENT_BLOCKED` |

Why image generation is never retried automatically: calls are slow and costly, results vary between runs, and the user already has a "regenerate" action that is an explicit retry.

**Retries never stack with the user's retries:** the user pressing "try again" is a new operation with a new deadline.

## 7. Error mapping and user-facing messages

All provider details are logged (truncated) and never returned (`04` section 8). `AIError` carries the code, the message below and `http_status` from `02`.

| Code | HTTP | Message (vision operations) | Message (image generation) |
|------|------|-----------------------------|----------------------------|
| `AI_NOT_CONFIGURED` | 503 | AI features are not set up on this server yet. | same |
| `AI_TIMEOUT` | 504 | The AI service took too long to respond. Please try again. | same |
| `AI_RATE_LIMITED` | 429 | The AI service is busy or its usage limit was reached. Please wait a minute and try again. | same |
| `AI_UPSTREAM_ERROR` | 502 | The AI service is temporarily unavailable. Please try again. | same |
| `AI_INVALID_RESPONSE` | 502 | The AI returned an answer we could not use. Please try again. | The AI did not return a usable image. Please try again. |
| `AI_CONTENT_BLOCKED` | 422 | The AI service declined to analyse this photo. Try a different photo. | The AI service declined to generate this design. Try different materials or a different photo. |

`details` for AI errors contains only `{ "operation": "detection" | "redesign" | "ai_estimate", "attempts": n }`.

## 8. Logging and stage-run detail

Per call, the calling service writes the stage run (`04` section 12.3). This package supplies the fields for `stage_runs.detail_json`:

```
{
  "model": "<identifier>",
  "prompt_version": "det-v2",
  "attempts": 1,
  "image_sent": { "width_px": 1600, "height_px": 1067, "bytes": 412345 },
  "duration_ms": 6200,
  "response_excerpt": "<first 500 chars of raw text, vision only>",
  "text_note": "<image generation only, max 500 chars>"
}
```

Rules:
- The API key, image bytes, base64 data and full prompts are never logged. The prompt text above 500 characters is truncated in logs; the full redesign prompt is stored in `generations.prompt_text` by `10`.
- `INFO` log per call: operation, model, attempts, duration, outcome. `WARNING` on each retry with the reason. `ERROR` on final failure with a truncated provider message.
- Provider error text is truncated to 300 characters before logging.

## 9. Mock mode

When `AI_MOCK_MODE=true`, both factories return mock clients. Purpose: develop and test the full app, run acceptance tests, and keep the demo alive when the network or quota fails.

**Mock Vision.** Waits 1 second (simulating latency) and returns data matching the detection schema of `07` when called for detection: a fixed set of about 10 components positioned for a typical front-facing house (walls, windows, a door, a balcony, a railing, two pillars, a roof edge, a gate, one `other` item). For the estimate operation of `11` it returns plausible fixed dimensions per component type. Mock output is the same for every photo.

**Mock Image generation.** Waits 3 seconds, then returns the working image with a visible tint and a "DEMO - simulated redesign" banner drawn on it, so it is never mistaken for real output.

**Scenarios** (`AI_MOCK_SCENARIO`):

| Value | Behaviour |
|-------|-----------|
| `ok` | Normal successful responses |
| `unusable` | Vision detection returns `usable: false` with a guidance reason and no components |
| `no_components` | Vision detection returns `usable: true` with no components |
| `invalid_json` | Vision returns malformed JSON or an invalid top-level envelope on every attempt (leads to `AI_INVALID_RESPONSE` after the retry) |
| `blocked` | Both interfaces raise `AI_CONTENT_BLOCKED` |
| `timeout` | Both interfaces raise `AI_TIMEOUT` |
| `rate_limited` | Both interfaces raise `AI_RATE_LIMITED` |

Mock mode shows a banner in the UI (`03` section 12) and `/api/health` reports `ai_mock_mode: true`.

## 10. Concurrency and safety

- AI calls run in worker threads (handlers are plain functions, `04` section 1). Provider clients must be safe for concurrent use or created per call.
- `MAX_CONCURRENT_AI_CALLS` protects quota and memory. Large images are processed one call at a time per thread; no image is held beyond the call.
- **Prompt safety.** Prompts are assembled in code from fixed templates. User text (labels, notes, extra instructions) is inserted only inside clearly delimited, quoted sections and is described to the model as untrusted description text, never as instructions. Details are in the feature specs.
- **Privacy.** Photos are sent to the provider only for the user-triggered operations of `07`, `10` and `11`. This is stated in the README (`13`) and on the upload screen ("Your photo is sent to Google's Gemini service to analyse it").

## 11. Validation of model output (shared rules)

| Rule | Detail |
|------|--------|
| Schema first | Vision output passes the feature-supplied top-level response schema. Feature specs may define array entries as unvalidated values and validate each entry independently after envelope validation. |
| Top-level fields | Required top-level fields and their types must validate; extra top-level fields are rejected. A failure is eligible for the Vision retry. |
| Array entries | Entry validation and drop/retain behavior are owned by the feature spec. An invalid entry in an otherwise valid envelope is not a response-schema failure and does not trigger a retry. |
| Numbers | NaN or infinity is a validation failure; coercion and clamping are defined by the feature spec. |
| Text | Trimming, control-character handling and length limits are defined by the feature spec. |
| Semantic checks | Done by the feature service after envelope validation (e.g. box normalization in `07`); this package does not interpret domain meaning. |

## 12. M0 spike checklist (before building on these integrations)

Run from a throwaway script on 6 or more real photos. Record results in `13`.

1. Both model identifiers work with the key (a trivial request to each succeeds).
2. The Vision model returns JSON that passes the detection schema of `07` in at least 5 of 6 photos.
3. **Box convention check:** draw the returned boxes on a photo and confirm they land on the right objects with the convention in `07` section 5 (`box_2d` as `[ymin, xmin, ymax, xmax]` on a 0-1000 scale). If not, adjust the prompt wording and the single conversion function in `07`; nothing else changes.
4. The Image model accepts `response_modalities=["TEXT", "IMAGE"]` with `image_size="1K"` and returns a parseable image part; record its output dimensions and aspect ratio relative to the input, and typical latency.
5. Measure typical latency of each call and confirm it is inside the configured timeouts; adjust the settings if not.
6. Confirm how each model reports a blocked or empty result so section 7 mapping is correct.

## 13. Acceptance criteria

- With the key unset and mock mode off, the server starts and every AI endpoint returns `503 AI_NOT_CONFIGURED`.
- With `AI_MOCK_MODE=true`, detection and redesign complete without network access.
- Each `AI_MOCK_SCENARIO` value produces its specified success or error outcome, and none leaves a stage run or generation in `running`.
- A working image for a 4000 x 3000 photo has its long side equal to `AI_WORKING_IMAGE_MAX_PX`, the same aspect ratio, and contains no EXIF data.
- The Vision request uses JSON response MIME and no deprecated sampling parameters; malformed JSON or invalid top-level schema is retried once, while invalid individual component entries are dropped by `07` without a retry.
- The image-generation request explicitly asks for `TEXT` and `IMAGE` modalities at initial `1K` resolution.
- Malformed vision output is retried once; if it fails again the response is `502 AI_INVALID_RESPONSE`.
- No log line, error body or stage-run record contains the API key.
- Changing `GEMINI_VISION_MODEL` or `NANO_BANANA_IMAGE_MODEL` requires no code change.
- The two integrations can be swapped independently: replacing the Image interface implementation leaves detection untouched.
