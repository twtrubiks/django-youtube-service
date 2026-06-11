# 本地應用 imports
from .models import Notification
from .tasks import send_channel_notification


def notify(recipient, payload, *, sender=None):
    """先持久化通知，再排程 WebSocket 推播（persist-then-push）。

    message 欄位直接存 payload（jsonb，前端通知面板渲染用），link 取 payload 的 url；
    推播內容與歷史通知 API 同形狀（to_client_dict），前端共用同一條渲染路徑。
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
        {"type": "send_notification", "notification": notification.to_client_dict()},
    )
    return notification
