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
    user = User.objects.create_user(username='asset_tester', password='password')
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
    return client


@pytest.fixture
def unauth_client():
    return APIClient()


@pytest.mark.django_db
def test_health_check_endpoint_unauthenticated(unauth_client):
    """Health check endpoint is unauthenticated and returns database status."""
    response = unauth_client.get('/api/v1/health/')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['status'] == 'ok'
    assert data['database'] == 'connected'


@pytest.mark.django_db
def test_protected_endpoints_require_authentication(unauth_client):
    """Protected endpoints reject requests without valid authentication."""
    response = unauth_client.get('/api/v1/assets/')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    response_checkouts = unauth_client.post('/api/v1/checkouts/', {})
    assert response_checkouts.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_create_asset(auth_client):
    """POST /api/v1/assets/ creates a new asset."""
    payload = {
        'asset_tag': 'NEW-SEN-99',
        'name': 'Spectral Soil Sensor',
        'category': 'SENSOR',
        'status': 'AVAILABLE',
        'purchase_date': '2024-05-10',
    }
    response = auth_client.post('/api/v1/assets/', payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data['asset_tag'] == 'NEW-SEN-99'
    assert data['name'] == 'Spectral Soil Sensor'
    assert data['status'] == 'AVAILABLE'
    assert data['current_holder'] is None


@pytest.mark.django_db
def test_asset_list_filtering_and_search(auth_client):
    """GET /api/v1/assets/ supports category/status filtering, search, and pagination."""
    Asset.objects.create(
        asset_tag='CAM-A',
        name='Alpha Cam',
        category=Asset.Category.CAMERA,
        status=Asset.Status.AVAILABLE,
        purchase_date=date(2023, 1, 1),
    )
    Asset.objects.create(
        asset_tag='LAP-B',
        name='Beta Laptop',
        category=Asset.Category.LAPTOP,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2023, 1, 1),
    )
    Asset.objects.create(
        asset_tag='VEH-C',
        name='Gamma Rover',
        category=Asset.Category.VEHICLE,
        status=Asset.Status.MAINTENANCE,
        purchase_date=date(2023, 1, 1),
    )

    # Filter by category
    res_cat = auth_client.get('/api/v1/assets/?category=CAMERA')
    assert res_cat.status_code == status.HTTP_200_OK
    cat_results = res_cat.json()['results']
    assert len(cat_results) == 1
    assert cat_results[0]['asset_tag'] == 'CAM-A'

    # Filter by status
    res_stat = auth_client.get('/api/v1/assets/?status=MAINTENANCE')
    assert res_stat.status_code == status.HTTP_200_OK
    stat_results = res_stat.json()['results']
    assert len(stat_results) == 1
    assert stat_results[0]['asset_tag'] == 'VEH-C'

    # Search by tag or name
    res_search = auth_client.get('/api/v1/assets/?search=Beta')
    assert res_search.status_code == status.HTTP_200_OK
    search_results = res_search.json()['results']
    assert len(search_results) == 1
    assert search_results[0]['asset_tag'] == 'LAP-B'


@pytest.mark.django_db
def test_asset_detail_current_holder(auth_client):
    """GET /api/v1/assets/{id}/ includes current_holder when checked out, null when available."""
    asset_avail = Asset.objects.create(
        asset_tag='AVAIL-01',
        name='Available Unit',
        category=Asset.Category.LAPTOP,
        status=Asset.Status.AVAILABLE,
        purchase_date=date(2024, 1, 1),
    )
    res_avail = auth_client.get(f'/api/v1/assets/{asset_avail.id}/')
    assert res_avail.status_code == status.HTTP_200_OK
    assert res_avail.json()['current_holder'] is None

    # Check out asset
    emp = Employee.objects.create(
        employee_code='EMP-HOLDER',
        full_name='Current Holding Employee',
        email='holder@artikate.local',
        is_active=True,
    )
    asset_held = Asset.objects.create(
        asset_tag='HELD-01',
        name='Held Unit',
        category=Asset.Category.LAPTOP,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2024, 1, 1),
    )
    CheckOut.objects.create(
        asset=asset_held,
        employee=emp,
        due_at=timezone.now() + timedelta(days=5),
        returned_at=None,
    )

    res_held = auth_client.get(f'/api/v1/assets/{asset_held.id}/')
    assert res_held.status_code == status.HTTP_200_OK
    holder = res_held.json()['current_holder']
    assert holder is not None
    assert holder['employee_code'] == 'EMP-HOLDER'
    assert holder['full_name'] == 'Current Holding Employee'
