# 標準庫 imports
import json

# 本地應用 imports
from .models import Notification
from .tasks import send_channel_notification


def notify(recipient, payload, *, sender=None):
    """先持久化通知，再排程 WebSocket 推播（persist-then-push）。

    message 欄位存 payload 的 JSON 字串（前端通知面板會解析渲染），
    link 取 payload 的 url；推播訊息額外帶上 id 供前端標記已讀。
    """
    if not recipient.is_active:
        return None

    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        message=json.dumps(payload),
        link=payload.get("url"),
    )
    send_channel_notification.delay(
        f"user_{recipient.id}_notifications",
        {"type": "send_notification", "message": {**payload, "id": notification.id}},
    )
    return notification
