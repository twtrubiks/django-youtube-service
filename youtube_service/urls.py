"""
URL configuration for youtube_service project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health_check(request):
    status = {"status": "ok"}
    try:
        connection.ensure_connection()
    except Exception:
        status["db"] = "unavailable"
        status["status"] = "degraded"
    return JsonResponse(status)


urlpatterns = [
    path("health/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("users/", include("users.urls", namespace="users")),
    path("videos/", include("videos.urls", namespace="videos")),
    path("interactions/", include("interactions.urls", namespace="interactions")),
]

if settings.ENABLE_PROMETHEUS:
    urlpatterns.insert(1, path("", include("django_prometheus.urls")))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
