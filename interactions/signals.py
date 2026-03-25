# 標準庫 imports
import logging

# Django imports
from django.db.models.signals import post_save
from django.dispatch import receiver

# 本地應用 imports
from videos.models import Video

from .models import Comment, Subscription
from .tasks import send_channel_notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Video)
def video_published_handler(sender, instance, created, **kwargs):
    """當有新影片被建立且狀態為 public 時，通知所有訂閱該影片上傳者的使用者。"""
    if created and instance.visibility == "public":
        uploader = instance.uploader
        subscribers = Subscription.objects.filter(subscribed_to=uploader).select_related("subscriber")

        for sub_entry in subscribers:
            subscriber_user = sub_entry.subscriber
            if subscriber_user.is_active:
                group_name = f"user_{subscriber_user.id}_notifications"
                message_content = {
                    "type": "send_notification",
                    "message": {
                        "type": "new_video",
                        "video_title": instance.title,
                        "video_id": instance.id,
                        "uploader_name": uploader.username,
                        "uploader_id": uploader.id,
                        "thumbnail_url": (instance.thumbnail.url if instance.thumbnail else None),
                    },
                }
                send_channel_notification.delay(group_name, message_content)


@receiver(post_save, sender=Comment)
def new_comment_or_reply_handler(sender, instance, created, **kwargs):
    """處理新評論和回覆的通知。"""
    if not created:
        return

    video_owner = instance.video.uploader

    if instance.parent_comment:
        logger.debug("Reply signal triggered for Comment ID: %s", instance.id)
        parent_comment_author = instance.parent_comment.user
        if parent_comment_author != instance.user and parent_comment_author.is_active:
            group_name = f"user_{parent_comment_author.id}_notifications"
            message_content = {
                "type": "send_notification",
                "message": {
                    "type": "new_reply",
                    "video_title": instance.video.title,
                    "video_id": instance.video.id,
                    "replier_name": instance.user.username,
                    "replier_id": instance.user.id,
                    "comment_content": (
                        instance.content[:100] + "..." if len(instance.content) > 100 else instance.content
                    ),
                    "parent_comment_id": instance.parent_comment.id,
                },
            }
            send_channel_notification.delay(group_name, message_content)
    else:
        logger.debug("New top-level comment signal triggered for Comment ID: %s", instance.id)
        if video_owner != instance.user and video_owner.is_active:
            group_name = f"user_{video_owner.id}_notifications"
            message_content = {
                "type": "send_notification",
                "message": {
                    "type": "new_comment_on_video",
                    "video_title": instance.video.title,
                    "video_id": instance.video.id,
                    "comment_id": instance.id,
                    "commenter_name": instance.user.username,
                    "commenter_id": instance.user.id,
                    "comment_content": (
                        instance.content[:100] + "..." if len(instance.content) > 100 else instance.content
                    ),
                },
            }
            send_channel_notification.delay(group_name, message_content)
