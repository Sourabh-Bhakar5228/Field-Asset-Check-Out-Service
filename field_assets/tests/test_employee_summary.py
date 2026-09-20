from datetime import date, timedelta
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from field_assets.models import Asset, Employee, CheckOut

User = get_user_model()


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(username='sum_tester', password='password')
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    return client


@pytest.mark.django_db
def test_employee_summary_four_numbers_against_controlled_data(auth_client):
    """
    Tests that the employee summary endpoint computes the four numbers accurately
    against strictly controlled data via database aggregation.
    """
    emp = Employee.objects.create(
        employee_code='EMP-METRIC-1',
        full_name='Metric Tester',
        email='metric@artikate.local',
        is_active=True,
    )

    # Create 4 assets
    assets = [
        Asset.objects.create(
            asset_tag=f'MET-AST-{i}',
            name=f'Asset {i}',
            category=Asset.Category.LAPTOP,
            status=Asset.Status.AVAILABLE,
            purchase_date=date(2023, 1, 1),
        )
        for i in range(4)
    ]

    now = timezone.now()

    # Item 1: Held for exactly 4 days, returned on time
    c1 = CheckOut.objects.create(
        asset=assets[0],
        employee=emp,
        due_at=now - timedelta(days=5),
        returned_at=now - timedelta(days=6),
    )
    CheckOut.objects.filter(id=c1.id).update(checked_out_at=now - timedelta(days=10))

    # Item 2: Held for exactly 6 days, returned
    c2 = CheckOut.objects.create(
        asset=assets[1],
        employee=emp,
        due_at=now - timedelta(days=2),
        returned_at=now - timedelta(days=2),
    )
    CheckOut.objects.filter(id=c2.id).update(checked_out_at=now - timedelta(days=8))

    # Item 3: Currently held AND overdue (due 2 days ago)
    c3 = CheckOut.objects.create(
        asset=assets[2],
        employee=emp,
        due_at=now - timedelta(days=2),
        returned_at=None,
    )
    CheckOut.objects.filter(id=c3.id).update(checked_out_at=now - timedelta(days=5))

    # Item 4: Currently held, NOT overdue (due in 5 days)
    c4 = CheckOut.objects.create(
        asset=assets[3],
        employee=emp,
        due_at=now + timedelta(days=5),
        returned_at=None,
    )
    CheckOut.objects.filter(id=c4.id).update(checked_out_at=now - timedelta(days=1))

    response = auth_client.get(f'/api/v1/employees/{emp.employee_code}/summary/')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data['employee_code'] == emp.employee_code
    assert data['lifetime_checkouts'] == 4
    assert data['currently_held'] == 2
    assert data['currently_overdue'] == 1
    # Mean of 4.0 and 6.0 is 5.0 days
    assert data['mean_hold_duration_days'] == 5.0


@pytest.mark.django_db
def test_employee_summary_unknown_employee(auth_client):
    """Unknown employee_code returns 404."""
    response = auth_client.get('/api/v1/employees/NONEXISTENT/summary/')
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_employee_summary_no_checkouts(auth_client):
    """Employee with zero checkouts returns zero counts and None for mean_hold_duration_days."""
    emp = Employee.objects.create(
        employee_code='EMP-EMPTY',
        full_name='Empty Employee',
        email='empty@artikate.local',
        is_active=True,
    )
    response = auth_client.get(f'/api/v1/employees/{emp.employee_code}/summary/')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['lifetime_checkouts'] == 0
    assert data['currently_held'] == 0
    assert data['currently_overdue'] == 0
    assert data['mean_hold_duration_days'] is None
