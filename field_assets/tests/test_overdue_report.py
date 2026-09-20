from datetime import date, timedelta
import pytest
from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from field_assets.models import Asset, Employee, CheckOut

User = get_user_model()


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(username='report_tester', password='password')
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    return client


@pytest.mark.django_db
def test_overdue_report_includes_item_due_exactly_now_and_order(auth_client):
    """
    Tests:
    1. Overdue calculation captures items due in the past AND item due exactly now.
    2. Items ordered most overdue first.
    3. Proper fields returned.
    """
    emp = Employee.objects.create(
        employee_code='EMP-REP-1',
        full_name='Report Employee',
        email='report_emp@artikate.local',
        is_active=True,
    )

    a1 = Asset.objects.create(
        asset_tag='REP-AST-1',
        name='Old Overdue Camera',
        category=Asset.Category.CAMERA,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )
    a2 = Asset.objects.create(
        asset_tag='REP-AST-2',
        name='Recent Overdue Laptop',
        category=Asset.Category.LAPTOP,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )
    a3 = Asset.objects.create(
        asset_tag='REP-AST-3',
        name='Due Exactly Now Sensor',
        category=Asset.Category.SENSOR,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )
    a4 = Asset.objects.create(
        asset_tag='REP-AST-4',
        name='Future Due Vehicle',
        category=Asset.Category.VEHICLE,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )

    now = timezone.now()

    # Most overdue (due 10 days ago)
    c1 = CheckOut.objects.create(
        asset=a1,
        employee=emp,
        due_at=now - timedelta(days=10),
        returned_at=None,
    )

    # Moderate overdue (due 2 days ago)
    c2 = CheckOut.objects.create(
        asset=a2,
        employee=emp,
        due_at=now - timedelta(days=2),
        returned_at=None,
    )

    # Item due EXACTLY now (boundary condition)
    c3 = CheckOut.objects.create(
        asset=a3,
        employee=emp,
        due_at=now,
        returned_at=None,
    )

    # Future item (not overdue)
    c4 = CheckOut.objects.create(
        asset=a4,
        employee=emp,
        due_at=now + timedelta(days=3),
        returned_at=None,
    )

    response = auth_client.get('/api/v1/reports/overdue/')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    results = data.get('results', data)
    assert len(results) == 3  # c1, c2, c3

    # Most overdue first
    assert results[0]['asset_tag'] == 'REP-AST-1'
    assert results[0]['days_overdue'] >= 10
    assert results[0]['asset_name'] == 'Old Overdue Camera'
    assert results[0]['employee_code'] == 'EMP-REP-1'
    assert results[0]['employee_name'] == 'Report Employee'

    assert results[1]['asset_tag'] == 'REP-AST-2'
    assert results[1]['days_overdue'] >= 2

    # Exactly now item is present and has days_overdue == 0
    assert results[2]['asset_tag'] == 'REP-AST-3'
    assert results[2]['days_overdue'] == 0


@pytest.mark.django_db
def test_overdue_report_does_not_issue_query_per_row(auth_client):
    """
    Tests that the overdue report uses select_related and does NOT issue N+1 queries.
    """
    emp = Employee.objects.create(
        employee_code='EMP-BULK',
        full_name='Bulk Employee',
        email='bulk@artikate.local',
        is_active=True,
    )

    now = timezone.now()
    # Create 15 overdue checkouts
    for i in range(15):
        asset = Asset.objects.create(
            asset_tag=f'BULK-AST-{i}',
            name=f'Bulk Asset {i}',
            category=Asset.Category.LAPTOP,
            status=Asset.Status.CHECKED_OUT,
            purchase_date=date(2023, 1, 1),
        )
        CheckOut.objects.create(
            asset=asset,
            employee=emp,
            due_at=now - timedelta(days=i + 1),
            returned_at=None,
        )

    with CaptureQueriesContext(connection) as queries:
        response = auth_client.get('/api/v1/reports/overdue/')
        assert response.status_code == status.HTTP_200_OK

    # Query count should be constant (auth check + select_related checkout query)
    # Crucially, it must NOT execute 15 additional queries for assets and employees!
    # Typically 1 query for user/token + 1 query for checkout join asset + employee + optional count
    assert len(queries) <= 5, f"Expected small fixed number of queries, got {len(queries)}"
