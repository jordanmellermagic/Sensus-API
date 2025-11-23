# Sensus API

FastAPI + SQLite backend for the Sensus project.

## Features

- Multi-user support (each `user_id` is independent)
- `data_peek` (first_name, last_name, job_title, phone_number, birthday, address, days_alive)
- `note_peek` (note_name, note_body) with push notifications on change
- `screen_peek` (contact, screenshot, url) with:
  - JSON endpoint that accepts base64 screenshots
  - File upload endpoint that accepts real JPEG/PNG files
- `commands` split with a `command` field
- Web Push subscriptions (`/push/subscribe/{user_id}`)
- SQLite persistence (`sensus.db`) so data survives restarts

## Running locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.
