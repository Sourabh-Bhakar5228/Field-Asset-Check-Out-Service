from datetime import date, timedelta
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token

from field_assets.models import Asset, Employee, CheckOut

User = get_user_model()


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(username='tester', password='testpassword')
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    return client


@pytest.fixture
def sample_asset(db):
    return Asset.objects.create(
        asset_tag='TEST-CAM-01',
        name='Test Camera 1',
        category=Asset.Category.CAMERA,
        status=Asset.Status.AVAILABLE,
        purchase_date=date(2024, 1, 1),
    )


@pytest.fixture
def sample_employee(db):
    return Employee.objects.create(
        employee_code='EMP100',
        full_name='Test Employee',
        email='emp100@test.local',
        is_active=True,
    )


@pytest.mark.django_db
def test_successful_checkout_applies_rule_5(auth_client, sample_asset, sample_employee):
    """Rule 5: Successful check-out creates CheckOut row and sets asset to CHECKED_OUT."""
    due = timezone.now() + timedelta(days=5)
    response = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': due.isoformat(),
    })

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data['asset_tag'] == sample_asset.asset_tag
    assert data['employee_code'] == sample_employee.employee_code

    sample_asset.refresh_from_db()
    assert sample_asset.status == Asset.Status.CHECKED_OUT
    assert CheckOut.objects.filter(asset=sample_asset, employee=sample_employee).exists()


@pytest.mark.django_db
def test_checkout_unavailable_asset_rule_1(auth_client, sample_asset, sample_employee):
    """Rule 1: An asset whose status is not AVAILABLE cannot be checked out -> 409."""
    sample_asset.status = Asset.Status.CHECKED_OUT
    sample_asset.save()

    due = timezone.now() + timedelta(days=5)
    response = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': due.isoformat(),
    })
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "not available" in response.json()['detail']


@pytest.mark.django_db
def test_checkout_inactive_employee_rule_2(auth_client, sample_asset, sample_employee):
    """Rule 2: An employee with is_active=False cannot check out anything -> 400."""
    sample_employee.is_active = False
    sample_employee.save()

    due = timezone.now() + timedelta(days=5)
    response = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': due.isoformat(),
    })
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "inactive" in response.json()['detail']


@pytest.mark.django_db
def test_three_open_checkouts_limit_rule_3(auth_client, sample_employee):
    """Rule 3: An employee may hold at most three open check-outs. Fourth attempt -> 409."""
    assets = []
    for i in range(4):
        assets.append(Asset.objects.create(
            asset_tag=f'LIM-LAP-{i}',
            name=f'Laptop {i}',
            category=Asset.Category.LAPTOP,
            status=Asset.Status.AVAILABLE,
            purchase_date=date(2024, 1, 1),
        ))

    due = timezone.now() + timedelta(days=7)

    # First 3 check-outs must succeed
    for i in range(3):
        res = auth_client.post('/api/v1/checkouts/', {
            'asset_tag': assets[i].asset_tag,
            'employee_code': sample_employee.employee_code,
            'due_at': due.isoformat(),
        })
        assert res.status_code == status.HTTP_201_CREATED, f"Failed at checkout {i}"

    # 4th check-out must fail with 409
    res_fourth = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': assets[3].asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': due.isoformat(),
    })
    assert res_fourth.status_code == status.HTTP_409_CONFLICT
    assert "3 open check-outs" in res_fourth.json()['detail']

    # Asset 3 must remain AVAILABLE
    assets[3].refresh_from_db()
    assert assets[3].status == Asset.Status.AVAILABLE


@pytest.mark.django_db
def test_due_at_validations_rule_4(auth_client, sample_asset, sample_employee):
    """Rule 4: due_at must be in the future and no more than 30 days ahead of now -> otherwise 400."""
    now = timezone.now()

    # Past due_at
    past_due = now - timedelta(days=1)
    res_past = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': past_due.isoformat(),
    })
    assert res_past.status_code == status.HTTP_400_BAD_REQUEST

    # More than 30 days ahead
    far_due = now + timedelta(days=31)
    res_far = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': far_due.isoformat(),
    })
    assert res_far.status_code == status.HTTP_400_BAD_REQUEST

    # Exactly now (boundary)
    res_now = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': sample_employee.employee_code,
        'due_at': now.isoformat(),
    })
    assert res_now.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_unknown_identifiers_rule_8(auth_client, sample_asset, sample_employee):
    """Rule 8: An unknown asset_tag or employee_code -> 404 Not Found, not a 500."""
    due = timezone.now() + timedelta(days=5)

    # Unknown asset
    res_bad_asset = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': 'NONEXISTENT-TAG',
        'employee_code': sample_employee.employee_code,
        'due_at': due.isoformat(),
    })
    assert res_bad_asset.status_code == status.HTTP_404_NOT_FOUND

    # Unknown employee
    res_bad_emp = auth_client.post('/api/v1/checkouts/', {
        'asset_tag': sample_asset.asset_tag,
        'employee_code': 'NONEXISTENT-EMP',
        'due_at': due.isoformat(),
    })
    assert res_bad_emp.status_code == status.HTTP_404_NOT_FOUND
