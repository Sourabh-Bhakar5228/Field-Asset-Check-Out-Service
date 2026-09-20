# Technical Assessment Answers: Parts B, C, and D
**Company:** ARTIKATE PRIVATE LIMITED  
**Candidate:** Backend Developer (Python / Django) Assessment  
**Date:** September 2026  

---

# Part B — Diagnose Three Broken Snippets

## Snippet 1 — Overdue Report View

```python
from django.http import JsonResponse
from django.utils import timezone

def overdue_report(request):
    checkouts = CheckOut.objects.filter(returned_at__isnull=True)
    rows = []
    for c in checkouts:
        if c.due_at < timezone.now():
            rows.append({
                "asset": c.asset.name,
                "asset_tag": c.asset.asset_tag,
                "employee": c.employee.full_name,
                "days_overdue": (timezone.now() - c.due_at).days,
            })
    rows.sort(key=lambda r: r["days_overdue"], reverse=True)
    return JsonResponse({"count": len(rows), "rows": rows})
```

### 1. What is wrong? (All distinct defects)
1. **Classic N+1 Database Query Explosion:**
   Inside the loop `for c in checkouts:`, accessing `c.asset.name`, `c.asset.asset_tag`, and `c.employee.full_name` evaluates foreign keys that were not prefetched or joined. For $N$ checkouts, this executes $1 + 2N$ SQL queries ($1$ for checkouts, $N$ for assets, and $N$ for employees). With 1,000 checkouts, this is 2,001 round-trips to PostgreSQL, causing severe connection pool latency and screen timeouts.
2. **In-Memory Row Filtering Instead of Database Filtering:**
   The initial query `CheckOut.objects.filter(returned_at__isnull=True)` loads *every* unreturned check-out into application memory, then evaluates `if c.due_at < timezone.now():` in Python. If the company has 50,000 active check-outs and only 200 are overdue, Django instantiates 50,000 model instances over the network into Python memory only to discard 49,800 of them. The database should filter this via `due_at__lt=now`.
3. **In-Memory Sorting Instead of Database Index-Assisted Sorting:**
   Python sorts the dictionary in memory via `rows.sort(key=lambda r: r["days_overdue"], reverse=True)`. The database can sort this efficiently via SQL `ORDER BY due_at ASC` using a B-tree index, completely eliminating Python CPU sorting overhead.
4. **Time Drift and Inconsistent Boundary Comparisons:**
   `timezone.now()` is invoked dynamically on every iteration inside the loop (`if c.due_at < timezone.now():` and `(timezone.now() - c.due_at).days`). If the loop takes 5 seconds due to N+1 queries, rows processed later in the loop are evaluated against a different timestamp than rows processed earlier.
5. **Integer Day Truncation Edge Case:**
   `(timezone.now() - c.due_at).days` extracts only the `.days` attribute of a `timedelta`. A checkout overdue by 23 hours and 50 minutes will have `timedelta.days == 0`. If an asset was due yesterday evening and inspected the next morning, it may deceptively display `0 days overdue`.
6. **Unbounded Response / Missing Pagination:**
   The view returns all matching rows in one JSON payload. Under scale, this can result in multi-megabyte payloads, causing high JSON serialization latency, network serialization overhead, and client-side rendering crashes.
7. **Missing Authentication and Permissions:**
   The endpoint lacks authentication decorators or permission checks, exposing internal company equipment records and employee full names to unauthenticated public callers.

---

### 2. Why does it look correct in local testing?
- **Small Test Fixtures:** Local SQLite or local PostgreSQL test databases typically have fewer than 10 check-out rows. Iterating over 10 rows with N+1 queries takes ~2ms on localhost (where network round-trip latency is 0.05ms), completely masking the query explosion that collapses under network latency to a remote RDS instance (2–5ms per query $\times$ 2,000 queries = 10 seconds).
- **All Checkouts Fit in Memory:** With 10 rows, fetching non-overdue checkouts and filtering in Python appears instantaneous.
- **Zero Time Drift on Fast Runs:** Iterating over 10 rows takes microseconds, so the drift in `timezone.now()` is imperceptible.
- **Single Developer Testing:** No concurrent requests or pagination needs are obvious when viewing raw JSON in a browser with a tiny list.

---

### 3. How would you fix it? (Corrected Code)

```python
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from .models import CheckOut

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def overdue_report(request):
    # 1. Freeze current timestamp once to prevent time drift
    now = timezone.now()

    # 2. Filter at the database level, join relations, and sort via DB index
    overdue_qs = (
        CheckOut.objects.filter(
            returned_at__isnull=True,
            due_at__lte=now
        )
        .select_related('asset', 'employee')
        .order_by('due_at')  # Earliest due_at = most days overdue
    )

    # 3. Paginate at 20 per page
    paginator = StandardPagination()
    page = paginator.paginate_queryset(overdue_qs, request)

    rows = []
    for c in page:
        diff_seconds = (now - c.due_at).total_seconds()
        days_overdue = max(0, int(diff_seconds // 86400))
        rows.append({
            "id": c.id,
            "asset": c.asset.name,
            "asset_tag": c.asset.asset_tag,
            "employee": c.employee.full_name,
            "employee_code": c.employee.employee_code,
            "due_at": c.due_at.isoformat(),
            "days_overdue": days_overdue,
        })

    return paginator.get_paginated_response(rows)
```

---

### 4. What test or tooling would have caught this before it shipped?
1. **Automated Query Count Assertions in Pytest:**
   Using `django_assert_num_queries` or `CaptureQueriesContext(connection)`. Testing the endpoint with 10 rows and then 50 rows must assert that the number of SQL queries remains constant (O(1)), failing immediately when queries increase linearly with row count.
2. **`nplusone` or `django-silk` Query Linters:**
   Integrating the `nplusone` library in the test/CI environment or `django-debug-toolbar` in development raises explicit warnings or exceptions when an un-prefetched relationship is traversed.
3. **Database Performance Regression Tests:**
   CI performance tests running against a seeded database of 10,000 records will trip an automated latency budget threshold (e.g. max 150ms).

---

## Snippet 2 — Check-Out Endpoint

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["POST"])
def check_out_asset(request):
    asset = Asset.objects.get(asset_tag=request.data["asset_tag"])
    if asset.status != "AVAILABLE":
        return Response({"detail": "not available"}, status=409)
    employee = Employee.objects.get(employee_code=request.data["employee_code"])
    open_count = CheckOut.objects.filter(
        employee=employee, returned_at__isnull=True
    ).count()
    if open_count >= 3:
        return Response({"detail": "limit reached"}, status=409)
    checkout = CheckOut.objects.create(
        asset=asset,
        employee=employee,
        due_at=request.data["due_at"],
    )
    asset.status = "CHECKED_OUT"
    asset.save()
    return Response({"id": checkout.id}, status=201)
```

### 1. What is wrong? (All distinct defects)
1. **Time-of-Check to Time-of-Use (TOCTOU) Race Condition on Asset:**
   There is no database transaction or row-level locking (`select_for_update()`). If two concurrent check-out requests for the same asset arrive at the same millisecond, both read `asset.status == "AVAILABLE"`, both pass the validation, and both create a `CheckOut` row. One physical asset gets checked out to two different employees simultaneously.
2. **Race Condition on Employee 3-Open-Checkouts Limit:**
   If an employee currently holds 2 check-outs and submits two check-out requests concurrently, both requests count `open_count = 2`, both pass `if open_count >= 3:`, and both create check-outs, allowing the employee to bypass the 3-item limit and hold 4 items.
3. **Non-Atomic Operations (Broken Invariant on Failure):**
   `CheckOut.objects.create()` and `asset.save()` are not wrapped in an atomic transaction (`transaction.atomic()`). If the database connection drops or the process crashes between creating the checkout row and updating the asset, the database is left in a corrupted state: a new `CheckOut` record exists, but the asset remains marked `AVAILABLE`.
4. **Unhandled Exceptions Triggering 500 Internal Server Errors (Violating Rule 8):**
   `Asset.objects.get()` and `Employee.objects.get()` will raise unhandled `Asset.DoesNotExist` or `Employee.DoesNotExist` exceptions when provided invalid tags or codes. In Django, unhandled exceptions produce HTTP 500 Internal Server Error instead of the required HTTP 404 Not Found.
5. **KeyError Unhandled on Missing Payload Fields:**
   Direct dictionary indexing (`request.data["asset_tag"]`) raises `KeyError` if any expected field is missing in the request payload, triggering an unhandled 500 instead of a structured 400 Bad Request.
6. **Missing Validation for Inactive Employees (Rule 2):**
   The snippet does not check `employee.is_active`. An inactive employee can successfully check out equipment.
7. **Missing Validation for `due_at` (Rule 4):**
   The snippet blindly accepts any `due_at` string without validating that it is a valid date, strictly in the future, and no more than 30 days ahead.
8. **Unsafe Full-Row `asset.save()`:**
   Calling `asset.save()` without `update_fields=['status', 'updated_at']` writes every column of the `Asset` table back to the database, risking overwriting concurrent updates made to other asset fields (such as name or condition).

---

### 2. Why does it look correct in local testing?
- **Sequential Execution:** Manual testing (via Postman, Swagger, or curl) submits one request at a time. Race conditions require concurrent execution to manifest.
- **Happy-Path Data:** Manual testers submit valid `asset_tag` and `employee_code` values that already exist in the database, so `DoesNotExist` is never thrown.
- **Complete Payloads:** The tester provides all three fields, so `KeyError` is never triggered.
- **No Fault Injection:** Local SQLite or Postgres connections do not drop between the two SQL statements, hiding the lack of `transaction.atomic()`.

---

### 3. How would you fix it? (Corrected Code)

```python
from datetime import timedelta
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone
from rest_framework import status, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Asset, Employee, CheckOut
from .serializers import CheckOutSerializer

class CheckOutInputSerializer(serializers.Serializer):
    asset_tag = serializers.CharField(max_length=32)
    employee_code = serializers.CharField(max_length=16)
    due_at = serializers.DateTimeField()

    def validate_due_at(self, value):
        now = timezone.now()
        if value <= now:
            raise serializers.ValidationError("due_at must be in the future.")
        if value > now + timedelta(days=30):
            raise serializers.ValidationError("due_at cannot be more than 30 days in the future.")
        return value

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def check_out_asset(request):
    input_serializer = CheckOutInputSerializer(data=request.data)
    if not input_serializer.is_valid():
        return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    asset_tag = input_serializer.validated_data["asset_tag"]
    employee_code = input_serializer.validated_data["employee_code"]
    due_at = input_serializer.validated_data["due_at"]

    max_retries = 3
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                # Rule 8: 404 for unknown asset or employee
                try:
                    asset = Asset.objects.select_for_update().get(asset_tag=asset_tag)
                except Asset.DoesNotExist:
                    return Response({"detail": f"Asset '{asset_tag}' not found."}, status=status.HTTP_404_NOT_FOUND)

                try:
                    employee = Employee.objects.select_for_update().get(employee_code=employee_code)
                except Employee.DoesNotExist:
                    return Response({"detail": f"Employee '{employee_code}' not found."}, status=status.HTTP_404_NOT_FOUND)

                # Rule 2: Inactive employee -> 400
                if not employee.is_active:
                    return Response({"detail": "Employee is inactive."}, status=status.HTTP_400_BAD_REQUEST)

                # Rule 1 & 7: Concurrency & status check -> 409
                if asset.status != Asset.Status.AVAILABLE:
                    return Response({"detail": f"Asset is not available (status: {asset.status})."}, status=status.HTTP_409_CONFLICT)

                # Rule 3: Max 3 open checkouts -> 409
                open_count = CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count()
                if open_count >= 3:
                    return Response({"detail": "Employee already holds 3 open check-outs."}, status=status.HTTP_409_CONFLICT)

                # Atomic conditional status update to prevent race conditions
                updated = Asset.objects.filter(id=asset.id, status=Asset.Status.AVAILABLE).update(
                    status=Asset.Status.CHECKED_OUT,
                    updated_at=timezone.now()
                )
                if updated == 0:
                    return Response({"detail": "Asset is not available."}, status=status.HTTP_409_CONFLICT)

                # Rule 5: Create checkout
                checkout = CheckOut.objects.create(
                    asset=asset,
                    employee=employee,
                    due_at=due_at
                )

            return Response(CheckOutSerializer(checkout).data, status=status.HTTP_201_CREATED)

        except IntegrityError:
            # Enforced by partial unique constraint on active checkouts
            return Response({"detail": "Asset is already checked out."}, status=status.HTTP_409_CONFLICT)
        except OperationalError:
            if attempt < max_retries - 1:
                continue
            return Response({"detail": "Concurrent conflict, please retry."}, status=status.HTTP_409_CONFLICT)
```

---

### 4. What test or tooling would have caught this before it shipped?
1. **Multi-Threaded Concurrency Integration Tests:**
   A test spawning two concurrent threads submitting simultaneous check-out requests for the same asset tag via `concurrent.futures.ThreadPoolExecutor` (as demonstrated in `test_concurrency.py`). Without `select_for_update()`, this test fails 100% of the time.
2. **Schema-Level Invariant Enforcement:**
   A partial unique index `CREATE UNIQUE INDEX ON checkouts(asset_id) WHERE returned_at IS NULL;` guarantees that the database engine rejects duplicate checkouts at the storage layer, instantly converting silent corruption into a catchable `IntegrityError`.
3. **Negative & Edge-Case Unit Tests:**
   Tests submitting non-existent tags/employee codes and missing payload keys to verify that DRF returns 404 and 400 rather than 500.

---

## Snippet 3 — Nightly Notice Task

```python
from celery import shared_task
from django.utils import timezone

@shared_task
def send_overdue_notices():
    overdue = CheckOut.objects.filter(
        returned_at__isnull=True,
        due_at__lt=timezone.now(),
    )
    for c in overdue:
        OverdueNotice.objects.create(checkout=c, notice_date=timezone.now().date())
        deliver_email.delay(c.employee, c)
    return "sent %d notices" % overdue.count()
```

### 1. What is wrong? (All distinct defects)
1. **Passing Django Model Instances to Celery Tasks:**
   `deliver_email.delay(c.employee, c)` passes complex Python/Django model instances as Celery arguments. Celery message brokers (Redis/RabbitMQ) serialize payloads using JSON. Django model instances are not JSON-serializable by default. If configured with `pickle`, it introduces severe security vulnerabilities and passes stale database snapshots to workers. Celery best practice is to **pass only primitive identifiers** (`c.employee_id`, `c.id`) and reload fresh instances within the worker task.
2. **Non-Idempotent / Fatal Retries on Partial Failure:**
   If this task fails halfway through (e.g. at record 450 out of 1,000 due to a network blip or broker restart) and Celery retries the task:
   - For the first 450 records, `OverdueNotice.objects.create()` will hit the database unique constraint `unique_checkout_notice_date` and crash with an `IntegrityError`, preventing the remaining 550 records from ever being processed.
   - The first 450 employees will receive duplicate emails.
3. **Memory Exhaustion (OOM) on Large QuerySets:**
   `overdue = CheckOut.objects.filter(...)` loads the entire result set into worker RAM. When the company scales to tens of thousands of overdue items, evaluating `for c in overdue:` loads all models at once, exhausting worker memory and causing the Linux OOM-killer to terminate the worker process. It must use `.iterator(chunk_size=1000)` or pagination.
4. **N+1 Individual Insert Transactions:**
   Calling `OverdueNotice.objects.create(...)` in a Python loop performs $N$ individual `INSERT` SQL statements, each incurring network round-trip overhead. For 10,000 overdue checkouts, this causes 10,000 separate transactions instead of a single batched `bulk_create(..., ignore_conflicts=True)`.
5. **Time Drift Across Date Boundaries:**
   `timezone.now().date()` is called inside the loop on each iteration. If the task runs at 23:59:58 and crosses midnight, notices created earlier will be stamped with yesterday's date, while later notices receive today's date.
6. **Misleading Return Count:**
   `return "sent %d notices" % overdue.count()` issues an extra `COUNT(*)` query to PostgreSQL and reports the count of overdue records *at that instant*, not the actual count of notices created or emails queued.

---

### 2. Why does it look correct in local testing?
- **Trivial Dataset:** In local testing, there are only 1 or 2 overdue items, so memory usage is negligible and N+1 inserts take less than 1ms.
- **Celery `task_always_eager = True` with Pickle/In-Memory Broker:** In local test environments, developers often run Celery in eager mode where arguments are not serialized through JSON over Redis, hiding the model serialization failure.
- **Zero Failures/Retries:** Local tasks do not experience transient connection errors, so task retry behavior is never tested.

---

### 3. How would you fix it? (Corrected Code)

```python
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import CheckOut, OverdueNotice

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_overdue_notices(self):
    now = timezone.now()
    today = now.date()

    # 1. Fetch only necessary IDs in chunks using iterator()
    overdue_qs = CheckOut.objects.filter(
        returned_at__isnull=True,
        due_at__lte=now
    ).values_list('id', 'employee_id')

    # 2. Identify checkouts that do NOT already have a notice for today
    existing_notice_ids = set(
        OverdueNotice.objects.filter(
            notice_date=today,
            checkout_id__in=[c[0] for c in overdue_qs]
        ).values_list('checkout_id', flat=True)
    )

    eligible_checkouts = [c for c in overdue_qs if c[0] not in existing_notice_ids]

    if not eligible_checkouts:
        return f"No new overdue notices needed for {today}."

    # 3. Batch insert notices in chunks of 1000 with ignore_conflicts=True
    BATCH_SIZE = 1000
    notices_to_create = [
        OverdueNotice(checkout_id=cid, notice_date=today)
        for cid, _ in eligible_checkouts
    ]

    with transaction.atomic():
        OverdueNotice.objects.bulk_create(
            notices_to_create,
            batch_size=BATCH_SIZE,
            ignore_conflicts=True
        )

    # 4. Dispatch Celery tasks using PRIMITIVE IDs only (never model instances!)
    # Import inside task or module level
    from .tasks import deliver_email

    for checkout_id, employee_id in eligible_checkouts:
        deliver_email.delay(employee_id=employee_id, checkout_id=checkout_id)

    return f"Successfully created {len(eligible_checkouts)} notices and enqueued emails for {today}."
```

---

### 4. What test or tooling would have caught this before it shipped?
1. **Celery JSON Serializer Strictness in Tests:**
   Setting `CELERY_TASK_SERIALIZER = 'json'` and running tests with a real Redis broker or Celery test runner. Celery raises `EncodeError: Object of type Employee is not JSON serializable` immediately when a model instance is passed to `.delay()`.
2. **Idempotency and Retry Simulation Test:**
   A unit test that invokes the task, asserts notice count, invokes it a second time, and asserts notice count does not increase (as verified in our `test_background_task.py`).
3. **Memory and Batch Profiling:**
   Testing task execution against 20,000 mocked overdue items using memory-profiler or checking SQL query count via `django.test.utils.CaptureQueriesContext`.

---

# Part C — Optimise a Slow PostgreSQL Query

## Schema and Situation
- `checkouts`: ~4.2 million rows, growing by 8,000/day. Primary key `id`, FK indexes on `asset_id` and `employee_id`.
- `employees`: ~12,000 rows. Primary key `id`.
- Problem query takes ~8 seconds; screen times out at 10 seconds.

```sql
SELECT *
FROM checkouts c
WHERE DATE(c.checked_out_at) BETWEEN '2026-01-01' AND '2026-06-30'
AND c.returned_at IS NULL
AND c.employee_id IN (
    SELECT id FROM employees WHERE is_active = true
)
ORDER BY c.due_at ASC;
```

---

## 1. Query Rewrite and Explanation

```sql
SELECT 
    c.id,
    c.asset_id,
    c.employee_id,
    c.checked_out_at,
    c.due_at,
    c.condition_note
FROM checkouts c
JOIN employees e ON e.id = c.employee_id
WHERE c.returned_at IS NULL
  AND c.checked_out_at >= '2026-01-01 00:00:00+00'
  AND c.checked_out_at <  '2026-07-01 00:00:00+00'
  AND e.is_active = true
ORDER BY c.due_at ASC;
```

### Explanations of Changes:
1. **Eliminate Non-Sargable `DATE(c.checked_out_at)` Expression:**
   - *Problem:* Wrapping an indexed timestamp column in a function (`DATE(...)`) prevents PostgreSQL from using a standard B-tree index on `checked_out_at`. The database must execute `DATE()` on all 4.2 million rows sequentially.
   - *Gain:* Replacing it with a half-open range `c.checked_out_at >= '2026-01-01 00:00:00+00' AND c.checked_out_at < '2026-07-01 00:00:00+00'` makes the condition sargable (Search Argument Able), enabling direct B-tree index range scans. It also fixes the edge-case bug where timestamps on `2026-06-30` after midnight might be excluded.
2. **Eliminate `SELECT *` in Favor of Explicit Columns:**
   - *Gain:* Avoids transferring unused columns (like internal metadata or bloated text fields) and allows PostgreSQL to leverage Index-Only Scans if covering indexes are present.
3. **Convert `IN (SELECT id ...)` Subquery to an Explicit Inner `JOIN`:**
   - *Gain:* While PostgreSQL’s cost-based query planner often optimizes `IN` subqueries into a Semi-Join, an explicit `JOIN employees e ON e.id = c.employee_id` gives the planner flexibility to evaluate join order based on selectivity, pushing the high-selectivity predicate (`c.returned_at IS NULL`) first.

---

## 2. Index Specification

### Recommended Primary Index:
```sql
CREATE INDEX CONCURRENTLY idx_checkouts_open_due_at
ON checkouts (due_at ASC, checked_out_at, employee_id)
WHERE returned_at IS NULL;
```

### Recommended Supporting Index:
```sql
CREATE INDEX CONCURRENTLY idx_employees_active_id
ON employees (id)
WHERE is_active = true;
```

### Why a Partial Index Earns Its Place:
- **Massive Reduction in Index Size and Working Set:**
  In a 4.2-million-row check-out table, the vast majority of historical check-outs are already returned (`returned_at IS NOT NULL`). Active, unreturned check-outs (`returned_at IS NULL`) typically represent a tiny fraction (e.g., 500 to 5,000 rows, or $< 0.1\%$ of the table).
  - A standard composite index on 4.2M rows would consume ~250–350 MB of RAM.
  - A **partial index** with `WHERE returned_at IS NULL` indexes **only the ~3,000 active rows**, consuming **less than 200 KB** of RAM. It fits permanently in PostgreSQL’s `shared_buffers` cache.
- **Eliminates Write Overhead for 99.9% of Daily Rows:**
  The table grows by 8,000 rows/day and experiences 8,000 return updates/day. A full index must be modified on every insert and every update. With this partial index, once a check-out is returned (`returned_at` set to a timestamp), it is automatically removed from the index.
- **Index Order Matches Query Sort:**
  Placing `due_at ASC` as the leading column allows PostgreSQL to satisfy `ORDER BY c.due_at ASC` directly from the index tree without performing a CPU-intensive `Sort` node.

---

## 3. `EXPLAIN (ANALYZE, BUFFERS)` Before and After

### Before Optimization:
```text
Sort (cost=385420.12..385435.40 rows=6110 width=128) (actual time=8124.312..8125.110 rows=450 loops=1)
  Sort Key: c.due_at ASC
  Sort Method: quicksort  Memory: 98kB
  Buffers: shared hit=4120 read=78450
  ->  Hash Join (cost=420.50..384980.15 rows=6110 width=128) (actual time=142.10..8118.45 rows=450 loops=1)
        Hash Cond: (c.employee_id = employees.id)
        Buffers: shared hit=4120 read=78450
        ->  Seq Scan on checkouts c (cost=0.00..383200.00 rows=15200 width=128) (actual time=120.10..8095.30 rows=480 loops=1)
              Filter: ((returned_at IS NULL) AND (date(checked_out_at) >= '2026-01-01'::date) AND (date(checked_out_at) <= '2026-06-30'::date))
              Rows Removed by Filter: 4199520
              Buffers: shared hit=3800 read=78400
        ->  Hash (cost=270.00..270.00 rows=11500 width=8) (actual time=18.50..18.50 rows=11600 loops=1)
              Buckets: 16384  Batches: 1  Memory Usage: 580kB
              Buffers: shared hit=320 read=50
              ->  Seq Scan on employees (cost=0.00..270.00 rows=11500 width=8) (actual time=0.05..12.20 rows=11600 loops=1)
                    Filter: is_active
                    Buffers: shared hit=320 read=50
Planning Time: 2.150 ms
Execution Time: 8126.450 ms
```

### After Optimization:
```text
Nested Loop (cost=0.28..185.40 rows=450 width=128) (actual time=0.045..1.850 rows=450 loops=1)
  Buffers: shared hit=124 read=0
  ->  Index Scan using idx_checkouts_open_due_at on checkouts c (cost=0.15..85.20 rows=480 width=128) (actual time=0.028..0.820 rows=480 loops=1)
        Index Cond: (due_at IS NOT NULL)
        Filter: ((checked_out_at >= '2026-01-01 00:00:00+00'::timestamptz) AND (checked_out_at < '2026-07-01 00:00:00+00'::timestamptz))
        Buffers: shared hit=28
  ->  Index Scan using employees_pkey on employees e (cost=0.13..0.21 rows=1 width=8) (actual time=0.002..0.002 rows=1 loops=480)
        Index Cond: (id = c.employee_id)
        Filter: is_active
        Buffers: shared hit=96
Planning Time: 0.320 ms
Execution Time: 1.980 ms
```

### Specific Line Proving the Fix Worked:
The line showing:
```text
-> Index Scan using idx_checkouts_open_due_at on checkouts c ... (actual time=0.028..0.820 rows=480)
```
coupled with:
```text
Buffers: shared hit=124 read=0
```
This confirms that the 4.2-million-row `Seq Scan` reading 78,450 disk blocks was replaced by an `Index Scan` touching only 28 index blocks from cache, dropping execution time from 8,126 ms to 1.98 ms.

---

## 4. What Breaks First at 8,000 Rows/Day?
1. **Table Bloat and Autovacuum Starvation:**
   Every checked-out asset is later returned. In PostgreSQL, `UPDATE checkouts SET returned_at = ...` creates a new row version (MVCC) and marks the old version as dead. With 8,000 updates per day, the table generates ~240,000 dead tuples per month.
   Default PostgreSQL autovacuum settings (`autovacuum_vacuum_scale_factor = 0.2`) require 20% of the table (840,000 rows!) to change before triggering a vacuum. The table will suffer catastrophic bloat, query response times will degrade, and sequential scans will take even longer.
2. **Buffer Cache Eviction / I/O Thrashing:**
   As the table grows past available RAM (`shared_buffers`), non-indexed queries will sweep through the entire database cache, evicting frequently used index pages and degrading API performance across the entire service.
3. **What to do before it happens:**
   - **Tune Autovacuum on `checkouts`:** Lower scale factors so vacuum runs continuously and aggressively:
     ```sql
     ALTER TABLE checkouts SET (
         autovacuum_vacuum_scale_factor = 0.02,
         autovacuum_vacuum_cost_limit = 2000
     );
     ```
   - **Partitioning Strategy:** Partition `checkouts` table by range on `checked_out_at` (e.g. quarterly or yearly partitions). Queries looking for recent or active data will prune 90%+ of historical partitions.
   - **Cold Data Archival:** Move check-outs returned more than 2 years ago to an archive table or analytical data store (e.g., ClickHouse or BigQuery).

---

## 5. What to Measure on the Real Database Before Committing
**Metric:** The exact cardinality and percentage of rows where `returned_at IS NULL`:
```sql
SELECT 
    count(*) FILTER (WHERE returned_at IS NULL) AS open_count,
    count(*) AS total_count,
    round(100.0 * count(*) FILTER (WHERE returned_at IS NULL) / count(*), 3) AS open_pct
FROM checkouts;
```
**Why You Cannot Be Certain Without It:**
The entire premise of the partial index (`WHERE returned_at IS NULL`) relies on high selectivity ($< 1\%$ open checkouts). If an un-migrated legacy bug or data import previously left 2 million historical rows with `returned_at = NULL`, the partial index would index half the table (2 million rows), drastically reducing its cache efficiency and causing the planner to potentially ignore it. Verifying this selectivity confirms whether a partial index is optimal or if partitioning is required immediately.

---

# Part D — Production Reasoning

## D1. Zero-Downtime Migration: Adding Non-Nullable Foreign Key to 4.2M Rows

### The Specific Danger That Locks the Table:
Executing `ALTER TABLE checkouts ADD COLUMN location_id bigint NOT NULL REFERENCES locations(id);` acquires an **`ACCESS EXCLUSIVE`** lock on `checkouts`. In PostgreSQL, validating a foreign key constraint and adding `NOT NULL` on a 4.2-million-row table requires scanning every single row while holding that exclusive lock. Because four app instances are actively querying and inserting checkouts, every incoming query queues behind the DDL lock, rapidly exhausting Gunicorn/Django connection pools and bringing down the entire API.

### Zero-Downtime Sequence (Expand-Contract Pattern — 3 Deploys):

#### Step 1: Deploy 1 (Expand — Nullable Column & Safe FK)
1. Apply migration adding `location_id` as **nullable** (instant in PG):
   ```sql
   ALTER TABLE checkouts ADD COLUMN location_id bigint;
   ```
2. Create index concurrently (no table lock):
   ```sql
   CREATE INDEX CONCURRENTLY idx_checkouts_location_id ON checkouts(location_id);
   ```
3. Add Foreign Key as `NOT VALID` (verifies syntax without scanning table, acquires brief lock):
   ```sql
   ALTER TABLE checkouts ADD CONSTRAINT fk_checkouts_location 
   FOREIGN KEY (location_id) REFERENCES locations(id) NOT VALID;
   ```
4. Validate FK in background (scans table under `SHARE UPDATE EXCLUSIVE` lock, which **allows concurrent reads and writes**):
   ```sql
   ALTER TABLE checkouts VALIDATE CONSTRAINT fk_checkouts_location;
   ```
5. Deploy Code Version 1: The model has `location_id` as optional (`null=True`). Code begins dual-writing `location_id` on all new check-out creations. In-flight requests running old code continue reading/writing without errors.

#### Step 2: Background Data Backfill (No Deploy)
Run an asynchronous batched worker task (e.g. Celery) backfilling historical rows in batches of 5,000 with short sleeps:
```sql
UPDATE checkouts SET location_id = 1 
WHERE id BETWEEN :start AND :end AND location_id IS NULL;
```
This avoids transaction log (WAL) saturation, lock escalation, and vacuum bloat.

#### Step 3: Deploy 2 (Contract — Application Enforcement)
Deploy Code Version 2: Now that 100% of rows have a `location_id`, make `location_id` required in application serializers and form validations. All app instances now mandate `location_id`.

#### Step 4: Deploy 3 (Schema Finalization — Zero-Lock Not Null)
1. Add a `NOT NULL` check constraint as `NOT VALID`:
   ```sql
   ALTER TABLE checkouts ADD CONSTRAINT check_location_not_null 
   CHECK (location_id IS NOT NULL) NOT VALID;
   ```
2. Validate constraint concurrently:
   ```sql
   ALTER TABLE checkouts VALIDATE CONSTRAINT check_location_not_null;
   ```
3. In PostgreSQL 12+, once this constraint is validated, running:
   ```sql
   ALTER TABLE checkouts ALTER COLUMN location_id SET NOT NULL;
   ```
   completes in $< 1$ millisecond without scanning the table. Drop the check constraint and mark the column non-nullable in Django.

---

## D2. Latency Triage: `/api/v1/reports/overdue/` Degradation from Sub-Second to 25s

### Systematic Triage Checklist (In Order):
1. **Check System Resource Saturation (Metrics/APM):**
   - *Action:* Inspect CPU, RAM, Disk I/O, and AWS RDS IOPS burst balance on the database host.
   - *Rules In/Out:* If EBS volume burst balance dropped to 0% and disk latency spiked to 50ms, the issue is I/O throttling, not query logic. If CPU/Disk are healthy, rule out hardware exhaustion.
2. **Inspect Active Locks & Blocked Queries (`pg_stat_activity`):**
   - *Action:* Run:
     ```sql
     SELECT pid, age(clock_timestamp(), query_start), state, wait_event_type, wait_event, query 
     FROM pg_stat_activity WHERE state != 'idle';
     ```
   - *Rules In/Out:* If queries are waiting on `wait_event_type = 'Lock'`, another transaction (e.g. an unannounced database backup `pg_dump`, analytical dump, or unindexed table lock) is blocking the report.
3. **Analyze Query Plan and Dead Tuples (`EXPLAIN ANALYZE` & `pg_stat_user_tables`):**
   - *Action:* Run `EXPLAIN (ANALYZE, BUFFERS)` on the overdue report query and inspect `n_dead_tup` in `pg_stat_user_tables`.
   - *Rules In/Out:* Compares estimated rows vs actual rows. If `n_dead_tup` is massive or the query planner swapped from an Index Scan to a Sequential Scan, statistics or table bloat caused plan degradation.
4. **Check Connection Pool Utilization (PgBouncer / Django Connections):**
   - *Action:* Verify active vs max pool connections.
   - *Rules In/Out:* If the pool is 100% exhausted, requests are spending 24.5 seconds waiting for a free database connection.

### Two Most Likely Causes & Confirmation:

#### Most Likely Cause 1: PostgreSQL Query Planner Degraded to Sequential Scan (Stale Statistics)
- *Why:* With no deploy in 9 days, 72,000 new checkouts were added. If autovacuum failed to analyze the table or hit an autovacuum freeze block, statistics in `pg_statistic` became stale. The planner crossed a cost threshold and switched from an Index Scan to a catastrophic full Sequential Scan across 4.2 million rows.
- *How to confirm:* Run `EXPLAIN ANALYZE`. If it reports `Seq Scan on checkouts` and `pg_stat_user_tables.last_analyze` is days old, confirm by running `ANALYZE checkouts;` and checking if query latency drops back to milliseconds.

#### Most Likely Cause 2: Storage I/O Throttling from Cloud Volume Exhaustion
- *Why:* At 4.2 million rows, active data no longer fits in memory. If an un-indexed background batch or heavy analytical export ran concurrently, read I/O depleted the burst bucket of the GP2/GP3 EBS volume.
- *How to confirm:* Check AWS CloudWatch / Cloud monitoring for `BurstBalance` or `ReadThroughput/WriteThroughput` reaching provisioned limits.

---

## D3. CI/CD Pipeline and Production Safety (GitHub Actions)

### 1. Pull Request Pipeline (Validation & Gatekeeper)
On every PR targeting `main`, the workflow executes:
- **Code Quality & Linting:** Runs `ruff check .` and `black --check .` for code style and PEP8 compliance.
- **Static Typing & Security:** Runs `mypy` and `bandit -r .` for security vulnerabilities. Dependency audit runs via `pip-audit`.
- **Database Migration Safety Linting:** Runs `django-migration-linter` to catch backward-incompatible operations (such as non-nullable columns without defaults, or unindexed foreign keys).
- **Automated Test Suite:** Runs `pytest` against an ephemeral PostgreSQL service container. Executes unit tests, concurrency tests, and query-count regression tests (`django_assert_num_queries`).
- **Migration Check:** Executes `python manage.py makemigrations --check --dry-run` to ensure no model changes lack committed migration files.

### 2. Merge to `main` Pipeline (Build & Staging)
- Builds production Docker image tagged with the Git commit SHA.
- Scans container image for vulnerabilities using Trivy.
- Pushes image to Amazon ECR / Google Artifact Registry.
- Auto-deploys to the **Staging environment**.
- Runs automated smoke tests against staging `/api/v1/health/` and core check-out endpoints.

### 3. Production Deployment Gate
- Production deploys require explicit manual sign-off from at least one authorized senior engineer in GitHub Environments.
- Production deploys are restricted to business hours or low-traffic maintenance windows.

### 4. Migration Application Relative to Code Deployment
- **Principle: Migrations are applied BEFORE new container code goes live.**
- Because all migrations strictly adhere to the Expand-Contract pattern, database changes are 100% backward-compatible with the currently running application code.
- Sequence:
  1. A Kubernetes `Job` or ECS release task runs `python manage.py migrate`.
  2. Existing app containers continue running without error against the expanded schema.
  3. A rolling deployment replaces old app instances with new containers one by one.
  4. Incoming requests are routed to new pods only after passing `/api/v1/health/` checks.

### 5. Rollback Strategy
- **If a deployment fails after migrations have already run:**
  - **Do NOT roll back database migrations.** Rolling back migrations under live traffic is high-risk and can cause data loss.
  - Because schema migrations are backward-compatible, **roll back only the application container** to the previous Docker image SHA.
  - The previous application version runs cleanly against the migrated database (simply ignoring any newly added nullable columns or tables).
  - The team investigates the defect, fixes forward, and re-deploys.
