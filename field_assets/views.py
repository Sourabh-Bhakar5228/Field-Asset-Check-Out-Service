from datetime import timedelta
from django.db import connection, transaction, IntegrityError, OperationalError
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Asset, Employee, CheckOut
from .serializers import (
    AssetSerializer,
    CheckOutSerializer,
    CheckOutCreateInputSerializer,
    CheckOutReturnInputSerializer,
    OverdueReportRowSerializer,
    EmployeeSummaryResponseSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AssetListCreateView(generics.ListCreateAPIView):
    """
    POST /api/v1/assets/ - Create an asset.
    GET /api/v1/assets/ - List assets with category, status filter and search.
    """
    serializer_class = AssetSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Asset.objects.all().prefetch_related('checkouts__employee')
        status_param = self.request.query_params.get('status')
        category_param = self.request.query_params.get('category')
        search_param = self.request.query_params.get('search')

        if status_param:
            queryset = queryset.filter(status=status_param.upper())
        if category_param:
            queryset = queryset.filter(category=category_param.upper())
        if search_param:
            queryset = queryset.filter(
                Q(name__icontains=search_param) | Q(asset_tag__icontains=search_param)
            )

        return queryset.order_by('-id')


class AssetDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/assets/{id}/ - Retrieve one asset, including current_holder.
    """
    queryset = Asset.objects.all().prefetch_related('checkouts__employee')
    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'


class CheckOutCreateView(APIView):
    """
    POST /api/v1/checkouts/ - Create a new check-out.
    Enforces business rules 1-5, 7, and 8 with database-level row locking.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckOutCreateInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        asset_tag = serializer.validated_data['asset_tag']
        employee_code = serializer.validated_data['employee_code']
        due_at = serializer.validated_data['due_at']

        max_retries = 5
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Rule 8: Unknown asset_tag or employee_code -> 404 Not Found
                    try:
                        asset = Asset.objects.select_for_update().get(asset_tag=asset_tag)
                    except Asset.DoesNotExist:
                        return Response(
                            {'detail': f"Asset with tag '{asset_tag}' not found."},
                            status=status.HTTP_404_NOT_FOUND
                        )

                    try:
                        employee = Employee.objects.select_for_update().get(employee_code=employee_code)
                    except Employee.DoesNotExist:
                        return Response(
                            {'detail': f"Employee with code '{employee_code}' not found."},
                            status=status.HTTP_404_NOT_FOUND
                        )

                    # Rule 2: Employee with is_active=False cannot check out anything -> 400 Bad Request
                    if not employee.is_active:
                        return Response(
                            {'detail': f"Employee '{employee_code}' is inactive."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # Rule 1 & 7: Asset status must be AVAILABLE -> 409 Conflict
                    if asset.status != Asset.Status.AVAILABLE:
                        return Response(
                            {'detail': f"Asset '{asset_tag}' is not available (current status: {asset.status})."},
                            status=status.HTTP_409_CONFLICT
                        )

                    # Rule 3: Employee may hold at most three open check-outs -> 4th attempt -> 409 Conflict
                    open_count = CheckOut.objects.filter(
                        employee=employee,
                        returned_at__isnull=True
                    ).count()
                    if open_count >= 3:
                        return Response(
                            {'detail': f"Employee '{employee_code}' already holds 3 open check-outs."},
                            status=status.HTTP_409_CONFLICT
                        )

                    # Atomic check-and-set on asset status to guarantee concurrency isolation
                    rows_updated = Asset.objects.filter(
                        id=asset.id,
                        status=Asset.Status.AVAILABLE
                    ).update(status=Asset.Status.CHECKED_OUT, updated_at=timezone.now())
                    if rows_updated == 0:
                        return Response(
                            {'detail': f"Asset '{asset_tag}' is not available (current status: {asset.status})."},
                            status=status.HTTP_409_CONFLICT
                        )

                    # Rule 5: Successful check-out creates CheckOut row
                    checkout = CheckOut.objects.create(
                        asset=asset,
                        employee=employee,
                        due_at=due_at
                    )
                response_serializer = CheckOutSerializer(checkout)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)

            except IntegrityError:
                # Enforced by database unique constraint on (asset, returned_at IS NULL)
                return Response(
                    {'detail': f"Asset '{asset_tag}' is already checked out."},
                    status=status.HTTP_409_CONFLICT
                )
            except OperationalError:
                # Retry transient lock contention (particularly on SQLite)
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.05 * (attempt + 1))
                    continue
                return Response(
                    {'detail': f"Asset '{asset_tag}' checkout could not be processed due to a concurrent conflict."},
                    status=status.HTTP_409_CONFLICT
                )


class CheckOutReturnView(APIView):
    """
    POST /api/v1/checkouts/{id}/return/ - Return a check-out.
    Enforces Rule 6: sets returned_at to now and asset to AVAILABLE or MAINTENANCE.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = CheckOutReturnInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        condition_note = serializer.validated_data.get('condition_note', '')
        needs_maintenance = serializer.validated_data.get('needs_maintenance', False)

        with transaction.atomic():
            try:
                checkout = CheckOut.objects.select_for_update().select_related('asset').get(pk=pk)
            except CheckOut.DoesNotExist:
                return Response(
                    {'detail': f"Check-out #{pk} not found."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Rule 6: Returning an already-returned check-out -> 409 Conflict
            if checkout.returned_at is not None:
                return Response(
                    {'detail': f"Check-out #{pk} has already been returned."},
                    status=status.HTTP_409_CONFLICT
                )

            now = timezone.now()
            checkout.returned_at = now
            if condition_note:
                checkout.condition_note = condition_note
            checkout.save(update_fields=['returned_at', 'condition_note'])

            # Update asset status
            asset = Asset.objects.select_for_update().get(id=checkout.asset_id)
            if needs_maintenance:
                asset.status = Asset.Status.MAINTENANCE
            else:
                asset.status = Asset.Status.AVAILABLE
            asset.save(update_fields=['status', 'updated_at'])

        response_serializer = CheckOutSerializer(checkout)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class EmployeeSummaryView(APIView):
    """
    GET /api/v1/employees/{employee_code}/summary/
    Returns lifetime check-out count, count currently held, count currently overdue,
    and mean hold duration in days across returned items.
    Computed by the database in a single query using ORM aggregation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, employee_code):
        try:
            employee = Employee.objects.get(employee_code=employee_code)
        except Employee.DoesNotExist:
            return Response(
                {'detail': f"Employee '{employee_code}' not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        now = timezone.now()

        # Single ORM aggregation query directly executed in the database
        agg_result = CheckOut.objects.filter(employee_id=employee.id).aggregate(
            lifetime_checkouts=Count('id'),
            currently_held=Count('id', filter=Q(returned_at__isnull=True)),
            currently_overdue=Count('id', filter=Q(returned_at__isnull=True, due_at__lte=now)),
            mean_hold_duration=Avg(
                ExpressionWrapper(
                    F('returned_at') - F('checked_out_at'),
                    output_field=DurationField()
                ),
                filter=Q(returned_at__isnull=False)
            )
        )

        mean_duration = agg_result['mean_hold_duration']
        if mean_duration is not None:
            # Convert timedelta to float days rounded to 2 decimal places
            mean_days = round(mean_duration.total_seconds() / 86400.0, 2)
        else:
            mean_days = None

        data = {
            'employee_code': employee.employee_code,
            'full_name': employee.full_name,
            'lifetime_checkouts': agg_result['lifetime_checkouts'] or 0,
            'currently_held': agg_result['currently_held'] or 0,
            'currently_overdue': agg_result['currently_overdue'] or 0,
            'mean_hold_duration_days': mean_days,
        }

        serializer = EmployeeSummaryResponseSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OverdueReportView(APIView):
    """
    GET /api/v1/reports/overdue/
    All open check-outs past their due_at, most overdue first.
    Uses select_related to avoid N+1 queries.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        # Single query with select_related on asset and employee
        overdue_checkouts = (
            CheckOut.objects.filter(returned_at__isnull=True, due_at__lte=now)
            .select_related('asset', 'employee')
            .order_by('due_at')
        )

        rows = []
        for checkout in overdue_checkouts:
            # Calculate days overdue from due_at to now
            diff_seconds = (now - checkout.due_at).total_seconds()
            days_overdue = max(0, int(diff_seconds // 86400))
            rows.append({
                'id': checkout.id,
                'asset_name': checkout.asset.name,
                'asset_tag': checkout.asset.asset_tag,
                'employee_code': checkout.employee.employee_code,
                'employee_name': checkout.employee.full_name,
                'due_at': checkout.due_at,
                'days_overdue': days_overdue,
            })

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        if page is not None:
            serializer = OverdueReportRowSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = OverdueReportRowSerializer(rows, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class HealthCheckView(APIView):
    """
    GET /api/v1/health/ - Unauthenticated health check reporting database connectivity.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return Response(
                {"status": "ok", "database": "connected"},
                status=status.HTTP_200_OK
            )
        except Exception as exc:
            return Response(
                {"status": "error", "database": "disconnected", "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
