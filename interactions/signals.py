# 標準庫 imports
import json

# 第三方庫 imports
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

# Django imports
from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

# 本地應用 imports
from videos.models import Video
from .models import Comment, Subscription

# 自訂訊號 (雖然我們這裡主要用 post_save，但保留以供未來擴展)
# new_video_signal = Signal()  # 提供 ['video_instance', 'uploader']
# new_reply_signal = Signal()  # 提供 ['reply_instance', 'parent_comment_author']


@receiver(post_save, sender=Video)
def video_published_handler(sender, instance, created, **kwargs):
    """
    當有新影片被建立且狀態為 public 時，通知所有訂閱該影片上傳者的使用者。

    Args:
        sender: 發送訊號的模型類別
        instance: 影片實例
        created: 是否為新建立的實例
        **kwargs: 其他關鍵字參數
    """
    if created and instance.visibility == 'public':
        uploader = instance.uploader
        subscribers = Subscription.objects.filter(subscribed_to=uploader)
        channel_layer = get_channel_layer()

        for sub_entry in subscribers:
            subscriber_user = sub_entry.subscriber
            if subscriber_user.is_active:  # 確保使用者是活躍的
                group_name = f"user_{subscriber_user.id}_notifications"
                message_content = {
                    # 這個 type 對應 consumer 中的方法名
                    'type': 'send_notification',
                    'message': {
                        # 這是傳給前端的通知類型
                        'type': 'new_video',
                        'video_title': instance.title,
                        'video_id': instance.id,
                        'uploader_name': uploader.username,
                        'uploader_id': uploader.id,
                        'thumbnail_url': (instance.thumbnail.url
                                        if instance.thumbnail else None),
                    }
                }
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    message_content
                )
                print(f"Sent new video notification to group: {group_name} "
                      f"for video: {instance.title}")

@receiver(post_save, sender=Comment)
def new_comment_or_reply_handler(sender, instance, created, **kwargs):
    """
    處理新評論和回覆的通知。

    為影片擁有者發送新評論通知，為父評論作者發送新回覆通知。

    Args:
        sender: 發送訊號的模型類別
        instance: 評論實例
        created: 是否為新建立的實例
        **kwargs: 其他關鍵字參數
    """
    print(f"[signals.py] new_comment_or_reply_handler triggered for "
          f"Comment ID: {instance.id}. Created: {created}. "
          f"Parent Comment: {instance.parent_comment}")

    if created:
        channel_layer = get_channel_layer()
        video_owner = instance.video.uploader # The owner of the video

        if instance.parent_comment:
            # This is a REPLY
            print(f"[signals.py] Conditions met for a REPLY on "
                  f"Comment ID: {instance.id}")
            parent_comment_author = instance.parent_comment.user
            # Notify parent_comment_author if they are not the one replying and are active
            if (parent_comment_author != instance.user and
                parent_comment_author.is_active):
                group_name = f"user_{parent_comment_author.id}_notifications"
                message_content = {
                    # This type matches the consumer method name
                    'type': 'send_notification',
                    # This is the actual payload for the client
                    'message': {
                        # This type is for the frontend to distinguish notifications
                        'type': 'new_reply',
                        'video_title': instance.video.title,
                        'video_id': instance.video.id,
                        'replier_name': instance.user.username,
                        'replier_id': instance.user.id,
                        'comment_content': (instance.content[:100] + '...'
                                          if len(instance.content) > 100
                                          else instance.content),
                        'parent_comment_id': instance.parent_comment.id,
                    }
                }
                print(f"[signals.py] Attempting to send NEW_REPLY notification "
                      f"to group: {group_name}, message: {json.dumps(message_content)}")
                async_to_sync(channel_layer.group_send)(group_name, message_content)
                print(f"[signals.py] Successfully called group_send for "
                      f"NEW_REPLY to group: {group_name}")

        else:
            # This is a new TOP-LEVEL COMMENT
            print(f"[signals.py] Conditions met for a NEW TOP-LEVEL COMMENT "
                  f"on Comment ID: {instance.id}")
            # Notify the video owner if they are not the one commenting and are active
            if video_owner != instance.user and video_owner.is_active:
                group_name = f"user_{video_owner.id}_notifications"
                message_content = {
                    # This type matches the consumer method name
                    'type': 'send_notification',
                    # This is the actual payload for the client
                    'message': {
                        # New notification type for frontend
                        'type': 'new_comment_on_video',
                        'video_title': instance.video.title,
                        'video_id': instance.video.id,
                        # Add the ID of the new comment
                        'comment_id': instance.id,
                        'commenter_name': instance.user.username,
                        'commenter_id': instance.user.id,
                        'comment_content': (instance.content[:100] + '...'
                                          if len(instance.content) > 100
                                          else instance.content),
                    }
                }
                print(f"[signals.py] Attempting to send NEW_COMMENT_ON_VIDEO "
                      f"notification to group: {group_name}, "
                      f"message: {json.dumps(message_content)}")
                async_to_sync(channel_layer.group_send)(group_name, message_content)
                print(f"[signals.py] Successfully called group_send for "
                      f"NEW_COMMENT_ON_VIDEO to group: {group_name}")