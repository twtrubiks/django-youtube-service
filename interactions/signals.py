# 標準庫 imports
import logging

# Django imports
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

# 本地應用 imports
from .models import Comment
from .services import notify

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Comment)
def new_comment_or_reply_handler(sender, instance, created, **kwargs):
    """處理新評論和回覆的通知（先持久化再推播，見 services.notify）。"""
    if not created:
        return

    video = instance.video
    video_url = reverse("videos:video_detail", kwargs={"video_id": video.id})
    comment_content = instance.content[:100] + "..." if len(instance.content) > 100 else instance.content

    if instance.parent_comment:
        # 回覆「回覆」會被 re-root 到頂層留言（見 views.add_comment），
        # _reply_to_user 保留實際被回覆的人，確保通知送對對象
        recipient = getattr(instance, "_reply_to_user", None) or instance.parent_comment.user
        if recipient == instance.user:
            return
        logger.debug("Reply signal triggered for Comment ID: %s", instance.id)
        notify(
            recipient,
            {
                "type": "new_reply",
                "video_title": video.title,
                "video_id": video.id,
                "replier_name": instance.user.username,
                "replier_id": instance.user.id,
                "comment_content": comment_content,
                "parent_comment_id": instance.parent_comment.id,
                # 留言已分頁，?comment= 讓 video_detail 把該串釘選在最上方並展開回覆
                "url": f"{video_url}?comment={instance.parent_comment.id}#comment-{instance.id}",
            },
            sender=instance.user,
        )
    else:
        recipient = video.uploader
        if recipient == instance.user:
            return
        logger.debug("New top-level comment signal triggered for Comment ID: %s", instance.id)
        notify(
            recipient,
            {
                "type": "new_comment_on_video",
                "video_title": video.title,
                "video_id": video.id,
                "comment_id": instance.id,
                "commenter_name": instance.user.username,
                "commenter_id": instance.user.id,
                "comment_content": comment_content,
                "url": f"{video_url}?comment={instance.id}#comment-{instance.id}",
            },
            sender=instance.user,
        )
