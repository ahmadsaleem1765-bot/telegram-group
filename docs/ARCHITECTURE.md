# Architecture

## System Overview

The application is a Flask-based Telegram automation platform with a modular backend, a vanilla JavaScript frontend, and JSON-based persistence. The v1.1 release introduces an automated daily ad delivery pipeline.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Flask Web Server                         │
│                          (main.py)                              │
├─────────────┬───────────────┬───────────────┬───────────────────┤
│  Auth API   │  Groups API   │  Rules API    │  Ads & Scheduler  │
│             │               │               │       API         │
└──────┬──────┴───────┬───────┴───────┬───────┴────────┬──────────┘
       │              │               │                │
       ▼              ▼               ▼                ▼
┌──────────┐  ┌──────────────┐ ┌───────────┐  ┌──────────────────┐
│ Telegram │  │    Group     │ │   Rules   │  │   Ad Delivery    │
│  Client  │  │   Scanner    │ │  Engine   │  │    Pipeline      │
│ Manager  │  │              │ │           │  │                  │
└──────────┘  └──────────────┘ └───────────┘  └──────────────────┘
                                                       │
                                          ┌────────────┼────────────┐
                                          ▼            ▼            ▼
                                   ┌───────────┐ ┌──────────┐ ┌─────────┐
                                   │  Content  │ │ Delivery │ │   Ad    │
                                   │  Manager  │ │  Engine  │ │Scheduler│
                                   └─────┬─────┘ └────┬─────┘ └────┬────┘
                                         │            │             │
                                         ▼            ▼             ▼
                                   ┌───────────┐ ┌──────────┐ ┌─────────┐
                                   │ manifest  │ │ Channel  │ │Delivery │
                                   │  .json    │ │ Adapters │ │ Ledger  │
                                   └───────────┘ └──────────┘ └─────────┘
```

## Ad Delivery Pipeline

The daily ad delivery follows this flow:

```
 APScheduler (CronTrigger)
        │
        ▼
 AdScheduler.run_daily_delivery()
        │
        ├── 1. ContentManager.get_ad_for_date(today)
        │       │
        │       ├── Check for date-specific ad (schedule_date match)
        │       └── Fall back to general pool (day-of-year rotation)
        │
        ├── 2. For each Destination:
        │       │
        │       ├── DeliveryLedger.was_delivered(hash, dest, today)?
        │       │       └── YES → Skip (idempotency)
        │       │
        │       └── NO → DeliveryEngine.deliver()
        │               │
        │               ├── Select ChannelAdapter by destination.type
        │               ├── Attempt send (text or media+caption)
        │               ├── On failure: exponential backoff retry
        │               │       delay = base * 2^attempt (capped)
        │               └── Record result in DeliveryLedger
        │
        └── 3. Log summary (sent / skipped / failed)
```

## Module Responsibilities

### `backend/content_manager/`
- **Source of truth**: `content/manifest.json`
- Loads ad metadata (id, title, message, media_path, is_active, priority, schedule_date)
- Hot-swap support: detects manifest file changes via mtime comparison
- Daily rotation: selects ad by date match or day-of-year modulo for general pool
- CRUD operations that persist back to manifest

### `backend/channel_adapter/`
- **ABC pattern**: `ChannelAdapter` defines `send_text()`, `send_media()`, `is_available()`
- **TelegramAdapter**: Wraps Telethon client for Telegram delivery
- **DeliveryEngine**: Orchestrates delivery with exponential backoff retry
  - `max_retries`: Number of retry attempts (default: 3)
  - `backoff_base`: Base delay in seconds (default: 2.0)
  - `backoff_cap`: Maximum delay cap (default: 60.0)
  - `inter_send_delay`: Delay between destinations (default: 5.0s)

### `backend/ad_scheduler/`
- **APScheduler**: AsyncIO scheduler with CronTrigger for daily delivery
- **DeliveryLedger**: JSON-backed idempotency tracker
  - Records (content_hash, destination_id, date, status)
  - Prevents re-delivery on restart within the same day
  - Supports pruning of old records
- **AdScheduler**: Coordinates ContentManager → DeliveryEngine → Ledger

### `backend/logging_config.py`
- Structured JSON logging via `python-json-logger`
- Separate `delivery.log` for channel adapter and ad scheduler events
- Console output remains human-readable plain text

## Data Flow: Content Management

```
Developer edits content/manifest.json
        │
        ▼
ContentManager.check_for_updates()  ← called on every read operation
        │
        ├── Compare file mtime with cached mtime
        │
        └── If changed → reload() all ads from disk
                │
                └── No code restart required (hot-swap)
```

### manifest.json Schema

```json
{
  "ads": [
    {
      "id": "unique-id",
      "title": "Human-readable title",
      "message": "Message text sent to channels",
      "media_path": "poster.jpg",
      "media_type": "photo",
      "is_active": true,
      "priority": 10,
      "schedule_date": "2026-12-25",
      "tags": ["holiday", "promo"],
      "created_at": "2026-03-25T00:00:00+00:00"
    }
  ]
}
```

### Ad Selection Algorithm

1. **Date-specific**: Ads with `schedule_date` matching today, sorted by priority (highest wins)
2. **General pool**: Ads with `schedule_date: null`, rotated by `day_of_year % pool_size`
3. **None**: If no active ads exist

## Idempotency Design

The DeliveryLedger prevents duplicate sends using a composite key:

```
(content_hash, destination_id, delivery_date)
```

- `content_hash` = SHA-256 of `"{id}:{message}:{media_path}"` (first 16 chars)
- Only `SUCCESS` status counts as "delivered"
- Failed deliveries can be retried on the same day
- Ledger persists to `data/delivery_ledger.json`

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `CONTENT_DIR` | `content` | Directory containing manifest.json and media |
| `SCHEDULE_TIME` | `09:00` | Daily delivery time (HH:MM, 24-hour) |
| `SCHEDULE_TIMEZONE` | `UTC` | IANA timezone for schedule |
| `DELIVERY_LEDGER_PATH` | `data/delivery_ledger.json` | Idempotency ledger path |
| `DELIVERY_MAX_RETRIES` | `3` | Max retry attempts per destination |
| `DELIVERY_INTER_DELAY` | `5.0` | Seconds between sends to different destinations |

## API Endpoints (Ad System)

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/ads` | List all ads |
| `GET` | `/api/ads/today` | Get today's selected ad |
| `POST` | `/api/ads` | Create a new ad |
| `PUT` | `/api/ads/<id>` | Update an ad |
| `DELETE` | `/api/ads/<id>` | Delete an ad |
| `GET` | `/api/ad-scheduler/status` | Scheduler status |
| `POST` | `/api/ad-scheduler/start` | Start scheduler |
| `POST` | `/api/ad-scheduler/stop` | Stop scheduler |
| `POST` | `/api/ad-scheduler/trigger` | Manual delivery now |
| `GET` | `/api/ad-scheduler/ledger?date=YYYY-MM-DD` | View delivery records |

## Testing Strategy

- **Unit tests**: Each module tested in isolation with temporary directories
- **Integration tests**: Full pipeline with mock adapters (no external credentials)
- **Idempotency**: Verified by running delivery twice and asserting skip on second run
- All tests are idempotent and use `pytest` `tmp_path` fixtures
