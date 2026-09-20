from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='index.html'), name='dashboard'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('field_assets.urls')),
]
