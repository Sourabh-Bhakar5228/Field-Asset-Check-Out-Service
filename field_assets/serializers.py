from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers

from .models import Asset, Employee, CheckOut, OverdueNotice


class CurrentHolderSerializer(serializers.Serializer):
    employee_code = serializers.CharField()
    full_name = serializers.CharField()


class AssetSerializer(serializers.ModelSerializer):
    current_holder = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = [
            'id',
            'asset_tag',
            'name',
            'category',
            'status',
            'purchase_date',
            'created_at',
            'updated_at',
            'current_holder',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'current_holder']

    def get_current_holder(self, obj):
        if obj.status != Asset.Status.CHECKED_OUT:
            return None
        # Retrieve the currently active checkout
        active_checkout = (
            obj.checkouts.filter(returned_at__isnull=True)
            .select_related('employee')
            .order_by('-id')
            .first()
        )
        if active_checkout and active_checkout.employee:
            return {
                'employee_code': active_checkout.employee.employee_code,
                'full_name': active_checkout.employee.full_name,
            }
        return None


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'email', 'is_active']


class CheckOutSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    employee_code = serializers.CharField(source='employee.employee_code', read_only=True)
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)

    class Meta:
        model = CheckOut
        fields = [
            'id',
            'asset',
            'asset_tag',
            'asset_name',
            'employee',
            'employee_code',
            'employee_name',
            'checked_out_at',
            'due_at',
            'returned_at',
            'condition_note',
        ]
        read_only_fields = ['id', 'checked_out_at', 'returned_at']


class CheckOutCreateInputSerializer(serializers.Serializer):
    asset_tag = serializers.CharField(max_length=32)
    employee_code = serializers.CharField(max_length=16)
    due_at = serializers.DateTimeField()

    def validate_due_at(self, value):
        now = timezone.now()
        # Rule 4: due_at must be in the future and no more than 30 days ahead of now
        if value <= now:
            raise serializers.ValidationError("due_at must be strictly in the future.")
        if value > now + timedelta(days=30):
            raise serializers.ValidationError("due_at cannot be more than 30 days in the future.")
        return value


class CheckOutReturnInputSerializer(serializers.Serializer):
    condition_note = serializers.CharField(required=False, allow_blank=True, default="")
    needs_maintenance = serializers.BooleanField(required=False, default=False)


class OverdueReportRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    asset_name = serializers.CharField()
    asset_tag = serializers.CharField()
    employee_code = serializers.CharField()
    employee_name = serializers.CharField()
    due_at = serializers.DateTimeField()
    days_overdue = serializers.IntegerField()


class EmployeeSummaryResponseSerializer(serializers.Serializer):
    employee_code = serializers.CharField()
    full_name = serializers.CharField()
    lifetime_checkouts = serializers.IntegerField()
    currently_held = serializers.IntegerField()
    currently_overdue = serializers.IntegerField()
    mean_hold_duration_days = serializers.FloatField(allow_null=True)
