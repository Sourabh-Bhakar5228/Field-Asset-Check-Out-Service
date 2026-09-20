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
    user = User.objects.create_user(username='returntester', password='password')
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    return client


@pytest.fixture
def active_checkout(db):
    asset = Asset.objects.create(
        asset_tag='RET-VEH-01',
        name='Rover Vehicle',
        category=Asset.Category.VEHICLE,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )
    emp = Employee.objects.create(
        employee_code='EMP-RET-1',
        full_name='Returner One',
        email='returner@test.local',
        is_active=True,
    )
    checkout = CheckOut.objects.create(
        asset=asset,
        employee=emp,
        due_at=timezone.now() + timedelta(days=5),
        returned_at=None,
    )
    return checkout


@pytest.mark.django_db
def test_successful_return_sets_available(auth_client, active_checkout):
    """Returning sets returned_at to now and sets the asset back to AVAILABLE."""
    response = auth_client.post(f'/api/v1/checkouts/{active_checkout.id}/return/', {
        'condition_note': 'All good, no scratches',
        'needs_maintenance': False,
    })

    assert response.status_code == status.HTTP_200_OK
    active_checkout.refresh_from_db()
    assert active_checkout.returned_at is not None
    assert active_checkout.condition_note == 'All good, no scratches'

    active_checkout.asset.refresh_from_db()
    assert active_checkout.asset.status == Asset.Status.AVAILABLE


@pytest.mark.django_db
def test_return_flags_maintenance(auth_client, active_checkout):
    """Returning with needs_maintenance=True sets asset to MAINTENANCE."""
    response = auth_client.post(f'/api/v1/checkouts/{active_checkout.id}/return/', {
        'condition_note': 'Sensor lens cracked during field survey',
        'needs_maintenance': True,
    })

    assert response.status_code == status.HTTP_200_OK
    active_checkout.asset.refresh_from_db()
    assert active_checkout.asset.status == Asset.Status.MAINTENANCE


@pytest.mark.django_db
def test_return_already_returned_checkout_rule_6(auth_client, active_checkout):
    """Returning an already-returned check-out -> 409 Conflict."""
    # First return succeeds
    res1 = auth_client.post(f'/api/v1/checkouts/{active_checkout.id}/return/', {})
    assert res1.status_code == status.HTTP_200_OK

    # Second return fails with 409
    res2 = auth_client.post(f'/api/v1/checkouts/{active_checkout.id}/return/', {})
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already been returned" in res2.json()['detail']


@pytest.mark.django_db
def test_return_nonexistent_checkout(auth_client):
    """Returning an unknown checkout -> 404 Not Found."""
    response = auth_client.post('/api/v1/checkouts/999999/return/', {})
    assert response.status_code == status.HTTP_404_NOT_FOUND
