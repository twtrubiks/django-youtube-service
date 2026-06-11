# 標準庫 imports
import logging
from itertools import batched

# 第三方庫 imports
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer

# Django imports
from django.urls import reverse

# 本地應用 imports
from .models import Notification, Subscription

logger = logging.getLogger(__name__)

# 每批持久化與推播的訂閱者數量
NOTIFY_BATCH_SIZE = 500


@shared_task
def send_channel_notification(group_name, message_content):
    """透過 Channel Layer 發送 WebSocket 通知（非同步，不阻塞請求）。"""
    channel_layer = get_channel_layer()
    try:
        async_to_sync(channel_layer.group_send)(group_name, message_content)
    except Exception:
        logger.exception("Failed to send notification to group %s", group_name)


@shared_task
def notify_subscribers_of_new_video(video_id):
    """新影片發布的訂閱者通知 fan-out：分批 bulk_create 持久化後，逐一推播給在線使用者。"""
    from videos.models import Video  # 函式內 import，避免跨 app 的模組層級循環相依

    try:
        video = Video.objects.select_related("uploader").get(id=video_id)
    except Video.DoesNotExist:
        logger.error("新影片通知失敗：找不到影片 ID %s", video_id)
        return

    if video.visibility != "public":
        return

    video_url = reverse("videos:video_detail", kwargs={"video_id": video.id})
    payload = {
        "type": "new_video",
        "video_title": video.title,
        "video_id": video.id,
        "uploader_name": video.uploader.username,
        "uploader_id": video.uploader.id,
        "thumbnail_url": video.thumbnail.url if video.thumbnail else None,
        "url": video_url,
    }
    channel_layer = get_channel_layer()

    subscriber_ids = (
        Subscription.objects.filter(subscribed_to=video.uploader, subscriber__is_active=True)
        .values_list("subscriber_id", flat=True)
        .iterator(chunk_size=NOTIFY_BATCH_SIZE)
    )
    for batch in batched(subscriber_ids, NOTIFY_BATCH_SIZE, strict=False):
        notifications = Notification.objects.bulk_create(
            Notification(recipient_id=subscriber_id, sender=video.uploader, message=payload, link=video_url)
            for subscriber_id in batch
        )
        for notification in notifications:
            try:
                async_to_sync(channel_layer.group_send)(
                    f"user_{notification.recipient_id}_notifications",
                    {"type": "send_notification", "message": {**payload, "id": notification.id}},
                )
            except Exception:
                logger.exception("推播新影片通知給使用者 %s 失敗", notification.recipient_id)
