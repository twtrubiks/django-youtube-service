from django.dispatch import Signal, receiver
from django.db.models.signals import post_save
from django.contrib.auth.models import User
from videos.models import Video
from .models import Comment, Subscription
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json

# 自訂訊號 (雖然我們這裡主要用 post_save，但保留以供未來擴展)
# new_video_signal = Signal() # 提供 ['video_instance', 'uploader']
# new_reply_signal = Signal() # 提供 ['reply_instance', 'parent_comment_author']

@receiver(post_save, sender=Video)
def video_published_handler(sender, instance, created, **kwargs):
    """
    當有新影片被建立且狀態為 public 時，通知所有訂閱該影片上傳者的使用者。
    """
    if created and instance.visibility == 'public':
        uploader = instance.uploader
        subscribers = Subscription.objects.filter(subscribed_to=uploader)
        channel_layer = get_channel_layer()

        for sub_entry in subscribers:
            subscriber_user = sub_entry.subscriber
            if subscriber_user.is_active: # 確保使用者是活躍的
                group_name = f"user_{subscriber_user.id}_notifications"
                message_content = {
                    'type': 'send_notification', # 這個 type 對應 consumer 中的方法名
                    'message': {
                        'type': 'new_video', # 這是傳給前端的通知類型
                        'video_title': instance.title,
                        'video_id': instance.id,
                        'uploader_name': uploader.username,
                        'uploader_id': uploader.id,
                        'thumbnail_url': instance.thumbnail.url if instance.thumbnail else None,
                    }
                }
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    message_content
                )
                print(f"Sent new video notification to group: {group_name} for video: {instance.title}")

@receiver(post_save, sender=Comment)
def new_comment_or_reply_handler(sender, instance, created, **kwargs): # Renamed for clarity
    """
    Handles notifications for new comments (to video owner) and new replies (to parent comment author).
    """
    print(f"[signals.py] new_comment_or_reply_handler triggered for Comment ID: {instance.id}. Created: {created}. Parent Comment: {instance.parent_comment}")

    if created:
        channel_layer = get_channel_layer()
        video_owner = instance.video.uploader # The owner of the video

        if instance.parent_comment:
            # This is a REPLY
            print(f"[signals.py] Conditions met for a REPLY on Comment ID: {instance.id}")
            parent_comment_author = instance.parent_comment.user
            # Notify parent_comment_author if they are not the one replying and are active
            if parent_comment_author != instance.user and parent_comment_author.is_active:
                group_name = f"user_{parent_comment_author.id}_notifications"
                message_content = {
                    'type': 'send_notification', # This type matches the consumer method name
                    'message': { # This is the actual payload for the client
                        'type': 'new_reply', # This type is for the frontend to distinguish notifications
                        'video_title': instance.video.title,
                        'video_id': instance.video.id,
                        'replier_name': instance.user.username,
                        'replier_id': instance.user.id,
                        'comment_content': instance.content[:100] + '...' if len(instance.content) > 100 else instance.content,
                        'parent_comment_id': instance.parent_comment.id,
                    }
                }
                print(f"[signals.py] Attempting to send NEW_REPLY notification to group: {group_name}, message: {json.dumps(message_content)}")
                async_to_sync(channel_layer.group_send)(group_name, message_content)
                print(f"[signals.py] Successfully called group_send for NEW_REPLY to group: {group_name}")

        else:
            # This is a new TOP-LEVEL COMMENT
            print(f"[signals.py] Conditions met for a NEW TOP-LEVEL COMMENT on Comment ID: {instance.id}")
            # Notify the video owner if they are not the one commenting and are active
            if video_owner != instance.user and video_owner.is_active:
                group_name = f"user_{video_owner.id}_notifications"
                message_content = {
                    'type': 'send_notification', # This type matches the consumer method name
                    'message': { # This is the actual payload for the client
                        'type': 'new_comment_on_video', # New notification type for frontend
                        'video_title': instance.video.title,
                        'video_id': instance.video.id,
                        'comment_id': instance.id, # Add the ID of the new comment
                        'commenter_name': instance.user.username,
                        'commenter_id': instance.user.id,
                        'comment_content': instance.content[:100] + '...' if len(instance.content) > 100 else instance.content,
                    }
                }
                print(f"[signals.py] Attempting to send NEW_COMMENT_ON_VIDEO notification to group: {group_name}, message: {json.dumps(message_content)}")
                async_to_sync(channel_layer.group_send)(group_name, message_content)
                print(f"[signals.py] Successfully called group_send for NEW_COMMENT_ON_VIDEO to group: {group_name}")