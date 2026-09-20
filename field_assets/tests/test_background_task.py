from datetime import date, timedelta
import pytest
from django.utils import timezone

from field_assets.models import Asset, Employee, CheckOut, OverdueNotice
from field_assets.tasks import flag_overdue_checkouts


@pytest.mark.django_db
def test_background_task_idempotency_run_twice_assert_one_notice():
    """
    Tests A5 requirement:
    the background task's idempotency — run it twice, assert one notice.
    """
    asset = Asset.objects.create(
        asset_tag='TASK-CAM-01',
        name='Task Test Camera',
        category=Asset.Category.CAMERA,
        status=Asset.Status.CHECKED_OUT,
        purchase_date=date(2024, 1, 1),
    )
    emp = Employee.objects.create(
        employee_code='EMP-TASK-1',
        full_name='Task Worker',
        email='taskworker@artikate.local',
        is_active=True,
    )
    checkout = CheckOut.objects.create(
        asset=asset,
        employee=emp,
        due_at=timezone.now() - timedelta(days=3),
        returned_at=None,
    )

    # First run of the task
    res1 = flag_overdue_checkouts()
    assert OverdueNotice.objects.filter(checkout=checkout).count() == 1
    notice = OverdueNotice.objects.get(checkout=checkout)
    assert notice.notice_date == timezone.now().date()

    # Second run on the same day must not create a duplicate notice
    res2 = flag_overdue_checkouts()
    assert OverdueNotice.objects.filter(checkout=checkout).count() == 1

    # Third run directly verifies idempotency
    res3 = flag_overdue_checkouts()
    assert OverdueNotice.objects.filter(checkout=checkout).count() == 1
