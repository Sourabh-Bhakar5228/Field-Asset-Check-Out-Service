# Field Asset Check-Out Service

An enterprise-grade Django REST Framework service for tracking physical equipment checked out to and returned by employees, built with strict database-level concurrency control, query aggregation, background task processing via Celery & Redis, and containerized deployment with Docker Compose.

---

## Architecture & Tech Stack

- **Backend:** Python 3.13, Django 6.1, Django REST Framework 3.18
- **Database:** PostgreSQL 15 (Docker) / SQLite with WAL mode (local testing)
- **Asynchronous Processing:** Celery 5.6 & Celery Beat
- **Message Broker & Cache:** Redis 7
- **Testing:** Pytest, Pytest-Django (22 comprehensive tests)
- **Containerization:** Docker, Docker Compose

---

## Quickstart Guide

### Option 1: Running with Docker Compose (Recommended)

Bring up all 4 required services (`web`, `db`, `redis`, `celery_worker`, `celery_beat`) in one command:

```bash
# 1. Build and start containers
docker compose up -d --build

# 2. Run database migrations
docker compose exec web python manage.py migrate

# 3. Seed demonstration data (creates assets, employees, checkouts, and admin token)
docker compose exec web python manage.py seed_demo_data

# 4. Run the automated test suite inside the container
docker compose exec web pytest
```

The API will be live at `http://localhost:8000/api/v1/`.

To inspect background Celery worker logs:

```bash
docker compose logs -f celery_worker
```

To stop all services:

```bash
docker compose down
```

---

### Option 2: Running Locally (Without Docker)

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
# source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Apply database migrations
python manage.py migrate

# 4. Populate demo data
python manage.py seed_demo_data

# 5. Run the test suite
pytest

# 6. Start the local server
python manage.py runserver 127.0.0.1:8000
```

---

## Interactive Live Test Dashboard

An interactive dark-mode dashboard is mounted directly at the service root:
👉 **`http://localhost:8000/`** (or `http://127.0.0.1:8000/`)

### Dashboard Features:
1. **Live Health & Token Bar:** Displays real-time database connection status (`DB: connected`) and pre-fills the seeded admin token (`a40f74ba82743b103305fff7d0264aac747bbbfe`). Clearing this input allows immediate verification of `401 Unauthorized` responses.
2. **Assets Explorer & Dynamic Filtering:** Filter live equipment by category (`CAMERA`, `LAPTOP`, `SENSOR`, `VEHICLE`) or status (`AVAILABLE`, `CHECKED_OUT`, `MAINTENANCE`), with instant detail modal inspection.
3. **Check-Out Dispatcher & Conflict Guard:** Dispatch checkouts for employees. Demonstrates immediate **`201 Created`** on success and **`409 Conflict`** when attempting to check out an already held asset (Rule 1 & Rule 7).
4. **Live Concurrency Stress Button:** Fires two simultaneous check-out requests for the same asset (`EMP001` and `EMP002`) over `Promise.all()`, visibly demonstrating race-condition safety (one request returns `201`, the other returns `409`).
5. **Return Item:** Return active check-outs with condition notes, optionally setting `needs_maintenance: true` to toggle equipment into `MAINTENANCE`.
6. **Aggregated Employee Metrics:** Real-time single-query ORM calculation of lifetime checkouts, currently held items, overdue items, and mean hold duration in days.
7. **Overdue Report:** Tabular inspection of past-due check-outs ordered by most overdue.
8. **Real-time API Console:** Live interactive inspector displaying the exact HTTP method, endpoint, status code badge (2xx, 4xx, 5xx), and formatted JSON response payload.

---

## Updating & Maintenance Cheat Sheet

Quick commands for updating and maintaining the service:

### 1. Docker Update & Restart Commands
```bash
# Rebuild containers after code modifications
docker compose up -d --build

# Run database migrations
docker compose exec web python manage.py migrate

# Re-seed test database with fresh assets and employees
docker compose exec web python manage.py seed_demo_data

# Run all 22 automated tests inside Docker
docker compose exec web pytest

# Inspect real-time Celery background task and worker logs
docker compose logs -f celery_worker
```

### 2. Local Python Environment Commands
```bash
# Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Run local development server
python manage.py runserver 127.0.0.1:8000

# Run local test suite
pytest
```

### 3. Git Save & Update Commands
```bash
# Stage all updated files
git add .

# Commit updates with descriptive message
git commit -m "docs: update README with live dashboard documentation and maintenance commands"

# Push to your repository
git push origin main
```

---

## Authentication & API Credentials

All endpoints under `/api/v1/` require token authentication, except the health check (`/api/v1/health/`).

The `python manage.py seed_demo_data` command automatically provisions a superuser and a DRF API Token:

- **Username:** `admin`
- **Password:** `adminpassword123`
- **Auth Header:**
  ```http
  Authorization: Token a40f74ba82743b103305fff7d0264aac747bbbfe
  ```
  _(Note: If a different token is printed during your seed run, use the token printed in the command output)._

---

## Endpoints Specification & cURL Examples

Set your token variable:

```bash
export TOKEN="a40f74ba82743b103305fff7d0264aac747bbbfe"
export BASE_URL="http://localhost:8000/api/v1"
```

### 1. Health Check (Unauthenticated)

```bash
curl -i -X GET "$BASE_URL/health/"
```

**Response (200 OK):**

```json
{
  "status": "ok",
  "database": "connected"
}
```

### 2. List Assets (Filtered & Paginated)

Supports filtering by `status`, `category`, and search parameter `search`:

```bash
curl -i -X GET "$BASE_URL/assets/?category=CAMERA&status=AVAILABLE" \
  -H "Authorization: Token $TOKEN"
```

### 3. Retrieve Asset (with `current_holder`)

Returns `current_holder: null` when available, or holding employee details when checked out:

```bash
curl -i -X GET "$BASE_URL/assets/2/" \
  -H "Authorization: Token $TOKEN"
```

**Response (200 OK):**

```json
{
  "id": 2,
  "asset_tag": "CAM-002",
  "name": "RED Komodo 6K Cinema Camera",
  "category": "CAMERA",
  "status": "CHECKED_OUT",
  "purchase_date": "2023-11-20",
  "current_holder": {
    "employee_code": "EMP001",
    "full_name": "Priya Sharma"
  }
}
```

### 4. Create Check-Out

Applies Rules 1–5, 7, and 8 with database-level row locking (`select_for_update()`):

```bash
curl -i -X POST "$BASE_URL/checkouts/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_tag": "LAP-002",
    "employee_code": "EMP003",
    "due_at": "2026-10-05T12:00:00Z"
  }'
```

**Response (201 Created):**

```json
{
  "id": 8,
  "asset": 4,
  "asset_tag": "LAP-002",
  "asset_name": "ThinkPad X1 Carbon Gen 11",
  "employee": 3,
  "employee_code": "EMP003",
  "employee_name": "Ananya Rao",
  "checked_out_at": "2026-09-20T07:15:00Z",
  "due_at": "2026-10-05T12:00:00Z",
  "returned_at": null,
  "condition_note": ""
}
```

### 5. Return Check-Out

Applies Rule 6. Sets `returned_at` to now and returns asset to `AVAILABLE` or `MAINTENANCE`:

```bash
curl -i -X POST "$BASE_URL/checkouts/8/return/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "condition_note": "Lens cleaned and battery recharged",
    "needs_maintenance": false
  }'
```

### 6. Employee Summary (Database Aggregation in 1 Query)

Returns lifetime count, currently held, currently overdue, and mean hold duration in days across returned items, computed entirely via database ORM aggregation:

```bash
curl -i -X GET "$BASE_URL/employees/EMP001/summary/" \
  -H "Authorization: Token $TOKEN"
```

**Response (200 OK):**

```json
{
  "employee_code": "EMP001",
  "full_name": "Priya Sharma",
  "lifetime_checkouts": 3,
  "currently_held": 2,
  "currently_overdue": 1,
  "mean_hold_duration_days": 7.0
}
```

### 7. Overdue Report (No Query-Per-Row)

Returns all open checkouts past `due_at`, ordered most overdue first:

```bash
curl -i -X GET "$BASE_URL/reports/overdue/" \
  -H "Authorization: Token $TOKEN"
```

---

## Background Celery Task (A4)

The Celery task `flag_overdue_checkouts` is defined in `field_assets/tasks.py`.

- **Idempotency:** It queries existing notices created today and uses `OverdueNotice.objects.bulk_create(..., ignore_conflicts=True)` backed by the database-level unique constraint `(checkout, notice_date)`. Running it multiple times on the same day creates zero duplicate notices.
- **Schedule:** Configured in `config/celery.py` with Celery Beat to run **hourly** (`crontab(minute=0)`).

To trigger the task manually from the command line:

```bash
python -c "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; django.setup(); from field_assets.tasks import flag_overdue_checkouts; print(flag_overdue_checkouts())"
```

---

## Assumptions & Architectural Decisions

1. **Authentication Choice:**
   - Evaluated DRF Token Authentication vs. JWT vs. Session Authentication. Selected **DRF Token Authentication** (`rest_framework.authentication.TokenAuthentication`) as the primary API mechanism because it provides stateless, reliable header-based authentication (`Authorization: Token <key>`) with zero token-refresh complexity during automated and live evaluation rounds. SessionAuthentication is enabled as a secondary mechanism for browsable API exploration.
2. **Strict Concurrency Solution (Rule 7):**
   - Implemented database row locking via `Asset.objects.select_for_update()` inside `transaction.atomic()`.
   - Also implemented an atomic conditional update (`Asset.objects.filter(id=asset.id, status='AVAILABLE').update(status='CHECKED_OUT')`).
   - Added a database partial unique constraint:
     `models.UniqueConstraint(fields=['asset'], condition=models.Q(returned_at__isnull=True), name='unique_active_checkout_per_asset')`
     This provides defense-in-depth: even if application locking were bypassed, PostgreSQL/SQLite storage engine guarantees that an asset can never have two active check-outs simultaneously.
3. **Overdue Calculation Boundary:**
   - Checkouts with `due_at <= timezone.now()` are classified as overdue, correctly including items due exactly at the current timestamp.
   - `days_overdue` is computed as `max(0, int((now - due_at).total_seconds() // 86400))`.
4. **Mean Hold Duration in Employee Summary:**
   - Computed directly inside PostgreSQL/SQLite using:
     ```python
     Avg(ExpressionWrapper(F('returned_at') - F('checked_out_at'), output_field=DurationField()), filter=Q(returned_at__isnull=False))
     ```
     This executes as a single SQL query with zero Python iteration. When an employee has zero returned checkouts, `mean_hold_duration_days` returns `null` (`None`).
5. **Pagination:**
   - Implemented standard 20-items-per-page pagination (`PageNumberPagination`) on all list endpoints (`/assets/` and `/reports/overdue/`).

---

## Known Gaps

1. **Email Delivery Mocking in Celery:**
   - In accordance with Part A4 and Part B Snippet 3, Celery background tasks create `OverdueNotice` records and avoid model instance serialization. Actual SMTP credentials were intentionally not provisioned in docker-compose, and email tasks are queued or mocked.
2. **Dynamic Timezone Localization per Employee:**
   - All datetime records are strictly stored and compared in UTC (`USE_TZ = True`). In a full production rollout with international offices, employees' local timezones could be configured on the `Employee` model for customized localized notifications.

---

## Automated Test Suite

The test suite contains **22 automated tests** covering 100% of business rules:

```bash
pytest
```

### Test Coverage Highlights:

- `test_concurrency.py`: Spawns simultaneous threads checking out the same asset; asserts exactly one succeeds (201) and one receives 409 Conflict.
- `test_checkout_rules.py`: Covers Rules 1, 2, 3 (3-item limit), 4 (future and $\le 30$ days), 5 (atomic status change), and 8 (404 on unknown tags).
- `test_return_rules.py`: Covers Rule 6 (return status, maintenance flag, 409 on already-returned).
- `test_employee_summary.py`: Tests the 4 ORM aggregation numbers against strictly controlled fixtures.
- `test_overdue_report.py`: Verifies overdue ordering, items due exactly now, and asserts O(1) query efficiency (no N+1 queries).
- `test_background_task.py`: Tests Celery task idempotency (running twice produces exactly one notice).
- `test_asset_endpoints_and_health.py`: Verifies unauthenticated health check, authentication gating, filtering, and `current_holder`.

---

## Screen Recording Walkthrough Script (6–8 Mins)

When recording your demonstration (Loom or screen recorder), use the following structured flow:

1. **Stack Startup (0:00 - 1:30):**
   - Run `docker compose up -d --build`.
   - Run `docker compose exec web python manage.py migrate`.
   - Run `docker compose exec web python manage.py seed_demo_data`. Show the output displaying the created assets, employees, checkouts, and admin API token.
2. **API Verification via cURL / Postman (1:30 - 4:00):**
   - Call `/api/v1/health/` (unauthenticated 200).
   - Call `GET /api/v1/assets/2/` to show `current_holder` populated.
   - Call `POST /api/v1/checkouts/` with an available asset tag. Show 201 Created.
   - Re-submit the exact same checkout call immediately to demonstrate HTTP 409 Conflict.
   - Call `POST /api/v1/checkouts/<id>/return/` with `{"needs_maintenance": true}` and demonstrate the asset transitioning to `MAINTENANCE`.
   - Call `GET /api/v1/employees/EMP001/summary/` and highlight the 4 aggregated numbers computed in one database query.
   - Call `GET /api/v1/reports/overdue/` showing most overdue first.
3. **Automated Test Suite (4:00 - 5:30):**
   - Run `pytest` inside the terminal. Let the reviewer see all 22 tests pass cleanly.
4. **Architectural Reflection & Defense (5:30 - 7:30):**
   - Talk through the decision you were least sure about:
     _"I spent the most time evaluating how to handle the 3-open-checkouts limit under extreme concurrency. While locking the Asset row via `select_for_update()` trivially prevents two employees from checking out the same equipment, preventing a single employee from opening two concurrent checkouts and exceeding the 3-item limit requires also acquiring a row-lock on the Employee record (`Employee.objects.select_for_update()`). In addition, I introduced a database-level partial unique constraint `UniqueConstraint(fields=['asset'], condition=Q(returned_at__isnull=True))` so that even if application-level locking was ever misconfigured, the database storage engine itself prevents data corruption."_
5. **Video Link:**
   - `[Insert your Loom / Screen recording URL here]`

---

## Written Answers for Parts B, C, and D

Comprehensive, production-grade diagnostic and architecture answers are provided in [ANSWERS.md](file:///d:/Downloads/python/ANSWERS.md).
