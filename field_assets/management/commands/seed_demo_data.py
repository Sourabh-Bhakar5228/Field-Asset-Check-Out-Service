from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from field_assets.models import Asset, Employee, CheckOut, OverdueNotice


class Command(BaseCommand):
    help = "Populate the database with demo assets, employees, checkouts, and admin API credentials."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding demonstration data..."))

        with transaction.atomic():
            # 1. Create superuser and DRF API Token
            User = get_user_model()
            admin_user, created = User.objects.get_or_create(
                username="admin",
                defaults={
                    "email": "admin@artikate.internal",
                    "is_staff": True,
                    "is_superuser": True,
                }
            )
            if created:
                admin_user.set_password("adminpassword123")
                admin_user.save()

            token, _ = Token.objects.get_or_create(user=admin_user)

            # 2. Seed Employees (at least 4, of whom one is inactive)
            employees_data = [
                {
                    "employee_code": "EMP001",
                    "full_name": "Priya Sharma",
                    "email": "priya.sharma@artikate.internal",
                    "is_active": True,
                },
                {
                    "employee_code": "EMP002",
                    "full_name": "Rohan Mehta",
                    "email": "rohan.mehta@artikate.internal",
                    "is_active": True,
                },
                {
                    "employee_code": "EMP003",
                    "full_name": "Ananya Rao",
                    "email": "ananya.rao@artikate.internal",
                    "is_active": True,
                },
                {
                    "employee_code": "EMP004",
                    "full_name": "Vikram Malhotra",
                    "email": "vikram.malhotra@artikate.internal",
                    "is_active": False,  # INACTIVE employee
                },
                {
                    "employee_code": "EMP005",
                    "full_name": "Rajesh Verma",
                    "email": "rajesh.verma@artikate.internal",
                    "is_active": True,
                },
            ]

            emp_map = {}
            for emp_d in employees_data:
                emp, _ = Employee.objects.update_or_create(
                    employee_code=emp_d["employee_code"],
                    defaults=emp_d,
                )
                emp_map[emp.employee_code] = emp

            # 3. Seed Assets (at least 8 across all four categories)
            assets_data = [
                # CAMERA
                {
                    "asset_tag": "CAM-001",
                    "name": "Sony Alpha 7 IV Mirrorless",
                    "category": Asset.Category.CAMERA,
                    "status": Asset.Status.AVAILABLE,
                    "purchase_date": date(2024, 3, 15),
                },
                {
                    "asset_tag": "CAM-002",
                    "name": "RED Komodo 6K Cinema Camera",
                    "category": Asset.Category.CAMERA,
                    "status": Asset.Status.CHECKED_OUT,
                    "purchase_date": date(2023, 11, 20),
                },
                # LAPTOP
                {
                    "asset_tag": "LAP-001",
                    "name": "MacBook Pro 16 M3 Max",
                    "category": Asset.Category.LAPTOP,
                    "status": Asset.Status.CHECKED_OUT,
                    "purchase_date": date(2024, 1, 10),
                },
                {
                    "asset_tag": "LAP-002",
                    "name": "ThinkPad X1 Carbon Gen 11",
                    "category": Asset.Category.LAPTOP,
                    "status": Asset.Status.AVAILABLE,
                    "purchase_date": date(2023, 8, 5),
                },
                {
                    "asset_tag": "LAP-003",
                    "name": "Dell XPS 15 9530",
                    "category": Asset.Category.LAPTOP,
                    "status": Asset.Status.AVAILABLE,
                    "purchase_date": date(2023, 5, 22),
                },
                # SENSOR
                {
                    "asset_tag": "SEN-001",
                    "name": "Velodyne VLP-16 LiDAR Puck",
                    "category": Asset.Category.SENSOR,
                    "status": Asset.Status.CHECKED_OUT,
                    "purchase_date": date(2023, 9, 1),
                },
                {
                    "asset_tag": "SEN-002",
                    "name": "FLIR Boson Longwave Thermal Sensor",
                    "category": Asset.Category.SENSOR,
                    "status": Asset.Status.MAINTENANCE,
                    "purchase_date": date(2022, 12, 14),
                },
                # VEHICLE
                {
                    "asset_tag": "VEH-001",
                    "name": "Toyota Hilux 4x4 Field Survey Truck",
                    "category": Asset.Category.VEHICLE,
                    "status": Asset.Status.AVAILABLE,
                    "purchase_date": date(2022, 6, 18),
                },
                {
                    "asset_tag": "VEH-002",
                    "name": "Mahindra Scorpio Field Rover",
                    "category": Asset.Category.VEHICLE,
                    "status": Asset.Status.CHECKED_OUT,
                    "purchase_date": date(2023, 2, 10),
                },
            ]

            asset_map = {}
            for a_d in assets_data:
                asset, _ = Asset.objects.update_or_create(
                    asset_tag=a_d["asset_tag"],
                    defaults=a_d,
                )
                asset_map[asset.asset_tag] = asset

            # 4. Check-outs
            # Requirements:
            # - At least two currently overdue
            # - At least two returned on time
            # - At least one returned late
            now = timezone.now()

            # Clean existing checkouts if re-seeding to keep exact deterministic states
            CheckOut.objects.all().delete()

            # Overdue 1: CAM-002 to EMP001 (due 4 days ago, open)
            co1 = CheckOut.objects.create(
                asset=asset_map["CAM-002"],
                employee=emp_map["EMP001"],
                due_at=now - timedelta(days=4),
                returned_at=None,
                condition_note="Field test in rough terrain",
            )
            CheckOut.objects.filter(id=co1.id).update(checked_out_at=now - timedelta(days=12))

            # Overdue 2: SEN-001 to EMP002 (due 2 days ago, open)
            co2 = CheckOut.objects.create(
                asset=asset_map["SEN-001"],
                employee=emp_map["EMP002"],
                due_at=now - timedelta(days=2),
                returned_at=None,
                condition_note="Drone lidar mapping",
            )
            CheckOut.objects.filter(id=co2.id).update(checked_out_at=now - timedelta(days=8))

            # Returned on time 1: LAP-002 to EMP001 (checked out 15 days ago, due 5 days ago, returned 8 days ago)
            co3 = CheckOut.objects.create(
                asset=asset_map["LAP-002"],
                employee=emp_map["EMP001"],
                due_at=now - timedelta(days=5),
                returned_at=now - timedelta(days=8),
                condition_note="Returned in perfect condition",
            )
            CheckOut.objects.filter(id=co3.id).update(checked_out_at=now - timedelta(days=15))

            # Returned on time 2: VEH-001 to EMP003 (checked out 20 days ago, due 10 days ago, returned 12 days ago)
            co4 = CheckOut.objects.create(
                asset=asset_map["VEH-001"],
                employee=emp_map["EMP003"],
                due_at=now - timedelta(days=10),
                returned_at=now - timedelta(days=12),
                condition_note="Odometer 45200 km, clean",
            )
            CheckOut.objects.filter(id=co4.id).update(checked_out_at=now - timedelta(days=20))

            # Returned late 1: LAP-003 to EMP002 (checked out 25 days ago, due 15 days ago, returned 10 days ago)
            co5 = CheckOut.objects.create(
                asset=asset_map["LAP-003"],
                employee=emp_map["EMP002"],
                due_at=now - timedelta(days=15),
                returned_at=now - timedelta(days=10),
                condition_note="Delayed return due to project extension",
            )
            CheckOut.objects.filter(id=co5.id).update(checked_out_at=now - timedelta(days=25))

            # Active on-schedule 1: LAP-001 to EMP001 (due in 14 days)
            co6 = CheckOut.objects.create(
                asset=asset_map["LAP-001"],
                employee=emp_map["EMP001"],
                due_at=now + timedelta(days=14),
                returned_at=None,
                condition_note="Assigned for quarterly sprint",
            )
            CheckOut.objects.filter(id=co6.id).update(checked_out_at=now - timedelta(days=2))

            # Active on-schedule 2: VEH-002 to EMP003 (due in 7 days)
            co7 = CheckOut.objects.create(
                asset=asset_map["VEH-002"],
                employee=emp_map["EMP003"],
                due_at=now + timedelta(days=7),
                returned_at=None,
                condition_note="Site visit to Gurgaon sector 47",
            )
            CheckOut.objects.filter(id=co7.id).update(checked_out_at=now - timedelta(days=1))

            # Ensure asset statuses accurately match current checkouts
            for asset in Asset.objects.all():
                if asset.asset_tag == "SEN-002":
                    asset.status = Asset.Status.MAINTENANCE
                elif asset.checkouts.filter(returned_at__isnull=True).exists():
                    asset.status = Asset.Status.CHECKED_OUT
                else:
                    asset.status = Asset.Status.AVAILABLE
                asset.save()

        self.stdout.write(self.style.SUCCESS("Demo data successfully seeded!"))
        self.stdout.write("--------------------------------------------------")
        self.stdout.write(f"API User: {admin_user.username}")
        self.stdout.write(f"API Token: {token.key}")
        self.stdout.write(f"Header: Authorization: Token {token.key}")
        self.stdout.write(f"Assets created: {Asset.objects.count()} (across CAMERA, LAPTOP, SENSOR, VEHICLE)")
        self.stdout.write(f"Employees created: {Employee.objects.count()} (including inactive EMP004)")
        self.stdout.write(f"Checkouts: {CheckOut.objects.count()} total (2 overdue, 2 returned on time, 1 returned late, 2 active)")
        self.stdout.write("--------------------------------------------------")
