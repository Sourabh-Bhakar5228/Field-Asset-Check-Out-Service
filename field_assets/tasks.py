from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import CheckOut, OverdueNotice


@shared_task(name='field_assets.tasks.flag_overdue_checkouts')
def flag_overdue_checkouts():
    """
    Finds every open, overdue check-out and creates an OverdueNotice for it dated today.
    Idempotent and safe to run repeatedly throughout the day without creating duplicate notices.
    """
    now = timezone.now()
    today = now.date()

    # Query all open check-outs whose due_at has passed
    overdue_checkouts = CheckOut.objects.filter(
        returned_at__isnull=True,
        due_at__lte=now
    )

    if not overdue_checkouts.exists():
        return f"No overdue check-outs found as of {now.isoformat()}."

    # Query existing notices created today for these checkouts
    existing_checkout_ids = set(
        OverdueNotice.objects.filter(
            notice_date=today,
            checkout__in=overdue_checkouts
        ).values_list('checkout_id', flat=True)
    )

    notices_to_create = [
        OverdueNotice(checkout=checkout, notice_date=today)
        for checkout in overdue_checkouts
        if checkout.id not in existing_checkout_ids
    ]

    if notices_to_create:
        with transaction.atomic():
            OverdueNotice.objects.bulk_create(notices_to_create, ignore_conflicts=True)

    created_count = len(notices_to_create)
    return f"Processed {overdue_checkouts.count()} overdue check-outs; created {created_count} new notices for {today}."
