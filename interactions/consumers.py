# 標準庫 imports
import json
import logging

# 第三方庫 imports
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

# Django imports
from django.contrib.auth.models import User

# 本地應用 imports
from .models import Notification

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket 消費者，處理即時通知功能。"""

    async def connect(self):
        """處理 WebSocket 連線。"""
        user = self.scope.get("user")
        user_id = self.scope["url_route"]["kwargs"]["user_id"]

        if not user or not user.is_authenticated or user.id != int(user_id):
            await self.close()
            return

        self.room_group_name = f"user_{user_id}_notifications"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info("User %s connected to notifications.", user_id)

    async def disconnect(self, close_code):
        """處理 WebSocket 斷線。"""
        # Leave room group
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            logger.info("User disconnected from notifications: %s", self.room_group_name)

    async def receive(self, text_data):
        """
        接收來自 WebSocket 的訊息。

        注意：通常通知是由伺服器主動發送，而不是接收來自客戶端的訊息。
        """
        # text_data_json = json.loads(text_data)
        # message = text_data_json['message']
        # print(f"Received message: {message} from {self.room_group_name}")
        pass

    async def send_notification(self, event):
        """
        接收來自房間群組的訊息並發送通知。

        Args:
            event: 包含通知資料的事件字典
        """
        original_message_payload = event["message"]

        try:
            user_id = self.scope["url_route"]["kwargs"]["user_id"]
            await self._save_notification_db(user_id, original_message_payload)
        except Exception:
            logger.exception("Error saving notification to DB for group %s", self.room_group_name)

        client_message_type = original_message_payload.get("type", "generic_notification")
        await self.send(text_data=json.dumps({"type": client_message_type, "message": original_message_payload}))

    @database_sync_to_async
    def _save_notification_db(self, user_id, message_payload):
        """
        將通知儲存到資料庫。

        Args:
            user_id: 接收通知的使用者 ID
            message_payload: 通知訊息內容
        """
        try:
            recipient_user = User.objects.get(id=user_id)

            # Extract message text and link from the payload
            # Assuming message_payload is a dict with 'text' and optional 'url'
            notification_text = "Notification"  # Default message
            if isinstance(message_payload, dict):
                notification_text = message_payload.get("text", json.dumps(message_payload))
                notification_link = message_payload.get("url", None)
            elif isinstance(message_payload, str):
                notification_text = message_payload  # If it's just a string
                notification_link = None
            else:
                notification_text = str(message_payload)  # Fallback
                notification_link = None

            Notification.objects.create(
                recipient=recipient_user,
                message=notification_text,
                link=notification_link,
                # Optionally, you could add notification_type if you implement it
                # notification_type=message_payload.get('type')
            )
            logger.debug("Notification saved for user %s: %s", user_id, notification_text[:50])
        except User.DoesNotExist:
            logger.warning("User with id %s not found. Notification not saved.", user_id)
        except Exception:
            logger.exception("Failed to save notification for user %s", user_id)
