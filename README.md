# Sensus API (Clean Version)

FastAPI + SQLite backend for the Sensus project.

## Data model (single user table)

- `data_peek`:
  - first_name
  - last_name
  - job_title
  - phone_number
  - birthday
  - address

- `note_peek`:
  - note_name
  - note_body

- `screen_peek`:
  - contact
  - screenshot_path (file on disk; accepts base64 OR file upload)
  - url

- `commands`:
  - command

Timestamps are stored internally (created_at, updated_at, *_updated_at) but are not required by the frontend.

## Key endpoints

- `POST /data_peek/{user_id}` — merge-safe update of data_peek fields
- `POST /note_peek/{user_id}` — merge-safe; sends push on change
- `POST /screen_peek/{user_id}` — JSON with optional base64 screenshot
- `POST /screen_peek/{user_id}/upload` — file upload screenshot
- `GET /screen_peek/{user_id}/screenshot` — fetch latest screenshot
- `POST /commands/{user_id}` — set command
- `GET /commands/{user_id}` — get command
- `POST /push/subscribe/{user_id}` — save web push subscription
- `GET /user/{user_id}` — full snapshot
- `DELETE /user/{user_id}` — delete user and related data

## Running locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open: http://127.0.0.1:8000/docs
