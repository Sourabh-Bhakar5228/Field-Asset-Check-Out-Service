from django.urls import path

from .views import (
    AssetListCreateView,
    AssetDetailView,
    CheckOutCreateView,
    CheckOutReturnView,
    EmployeeSummaryView,
    OverdueReportView,
    HealthCheckView,
)

app_name = 'field_assets'

urlpatterns = [
    path('assets/', AssetListCreateView.as_view(), name='asset-list-create'),
    path('assets/<int:pk>/', AssetDetailView.as_view(), name='asset-detail'),
    path('checkouts/', CheckOutCreateView.as_view(), name='checkout-create'),
    path('checkouts/<int:pk>/return/', CheckOutReturnView.as_view(), name='checkout-return'),
    path('employees/<str:employee_code>/summary/', EmployeeSummaryView.as_view(), name='employee-summary'),
    path('reports/overdue/', OverdueReportView.as_view(), name='overdue-report'),
    path('health/', HealthCheckView.as_view(), name='health-check'),
]
