import logging

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


@shared_task
def send_channel_notification(group_name, message_content):
    """透過 Channel Layer 發送 WebSocket 通知（非同步，不阻塞 signal handler）。"""
    channel_layer = get_channel_layer()
    try:
        async_to_sync(channel_layer.group_send)(group_name, message_content)
    except Exception:
        logger.exception("Failed to send notification to group %s", group_name)
