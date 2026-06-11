# 本地應用 imports
from .models import Notification
from .tasks import send_channel_notification


def notify(recipient, payload, *, sender=None):
    """先持久化通知，再排程 WebSocket 推播（persist-then-push）。

    message 欄位直接存 payload（jsonb，前端通知面板渲染用），
    link 取 payload 的 url；推播訊息額外帶上 id 供前端標記已讀。
    """
    if not recipient.is_active:
        return None

    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        message=payload,
        link=payload.get("url"),
    )
    send_channel_notification.delay(
        f"user_{recipient.id}_notifications",
        {"type": "send_notification", "message": {**payload, "id": notification.id}},
    )
    return notification
