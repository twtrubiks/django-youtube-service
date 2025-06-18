"""
ASGI config for youtube_service project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack # 若需要使用者驗證
from django.core.asgi import get_asgi_application
import interactions.routing # 匯入 interactions app 的路由

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'youtube_service.settings')

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack( # 若需要使用者驗證，否則直接用 URLRouter
            URLRouter(
                interactions.routing.websocket_urlpatterns
            )
        ),
    }
)
