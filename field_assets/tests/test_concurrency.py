import concurrent.futures
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from field_assets.models import Asset, Employee, CheckOut

User = get_user_model()


class ConcurrencyTestCase(TransactionTestCase):
    """
    Tests Rule 7: If two check-out requests for the same asset arrive at the same moment,
    exactly one must succeed (201) and the other must receive 409 Conflict.
    Solves concurrency at the database level with row-level locks.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='concurrency_tester', password='password')
        self.token = Token.objects.create(user=self.user)
        self.asset = Asset.objects.create(
            asset_tag='RACE-LAP-01',
            name='Race Condition Laptop',
            category=Asset.Category.LAPTOP,
            status=Asset.Status.AVAILABLE,
            purchase_date=date(2024, 1, 1),
        )
        self.emp1 = Employee.objects.create(
            employee_code='EMP-RACE-1',
            full_name='Racer One',
            email='racer1@artikate.local',
            is_active=True,
        )
        self.emp2 = Employee.objects.create(
            employee_code='EMP-RACE-2',
            full_name='Racer Two',
            email='racer2@artikate.local',
            is_active=True,
        )

    def test_concurrent_checkouts_of_same_asset(self):
        due = timezone.now() + timedelta(days=5)

        def make_checkout_request(emp_code):
            # Close existing connection to ensure separate thread connection
            connection.close()
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
            return client.post('/api/v1/checkouts/', {
                'asset_tag': self.asset.asset_tag,
                'employee_code': emp_code,
                'due_at': due.isoformat(),
            })

        # Submit two checkout requests concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(make_checkout_request, self.emp1.employee_code)
            future2 = executor.submit(make_checkout_request, self.emp2.employee_code)

            res1 = future1.result()
            res2 = future2.result()

        status_codes = [res1.status_code, res2.status_code]

        # Exactly one must succeed with 201, and one must fail with 409
        self.assertEqual(status_codes.count(status.HTTP_201_CREATED), 1)
        self.assertEqual(status_codes.count(status.HTTP_409_CONFLICT), 1)

        # In the database, exactly one checkout row must exist
        self.assertEqual(CheckOut.objects.filter(asset=self.asset).count(), 1)

        # Asset status must be CHECKED_OUT
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.Status.CHECKED_OUT)
