# 標準庫 imports
import json

# 第三方庫 imports
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

# Django imports
from django.contrib.auth.models import User

# 本地應用 imports
from .models import Notification

class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket 消費者，處理即時通知功能。"""

    async def connect(self):
        """處理 WebSocket 連線。"""
        # 暫時先允許所有連線，之後再加入使用者驗證
        user_id = self.scope['url_route']['kwargs']['user_id']
        self.room_group_name = f"user_{user_id}_notifications"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        print(f"User {user_id} connected to notifications.")

    async def disconnect(self, close_code):
        """處理 WebSocket 斷線。"""
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            print(f"User disconnected from notifications: {self.room_group_name}")

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
        print(f"[consumers.py] send_notification called for group "
              f"{self.room_group_name}. Event received: {json.dumps(event)}")

        original_message_payload = event['message']  # This is usually a dictionary

        # Save notification to database
        try:
            user_id = self.scope['url_route']['kwargs']['user_id']
            await self._save_notification_db(user_id, original_message_payload)
        except Exception as e:
            print(f"Error saving notification to DB: {e}")

        # Prepare message for WebSocket client
        # The client expects a 'type' (e.g., 'new_video') and a 'message' payload
        client_message_type = original_message_payload.get(
            'type', 'generic_notification'
        )

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': client_message_type,
            'message': original_message_payload
        }))
        print(f"[consumers.py] Sent notification data: "
              f"{json.dumps(original_message_payload)} to client in group "
              f"{self.room_group_name}")

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
                notification_text = message_payload.get(
                    'text', json.dumps(message_payload)
                )
                notification_link = message_payload.get('url', None)
            elif isinstance(message_payload, str):
                notification_text = message_payload  # If it's just a string
                notification_link = None
            else:
                notification_text = str(message_payload)  # Fallback
                notification_link = None

            Notification.objects.create(
                recipient=recipient_user,
                message=notification_text,
                link=notification_link
                # Optionally, you could add notification_type if you implement it
                # notification_type=message_payload.get('type')
            )
            print(f"Notification saved for user {user_id}: "
                  f"{notification_text[:50]}")
        except User.DoesNotExist:
            print(f"User with id {user_id} not found. Notification not saved.")
        except Exception as e:
            print(f"Failed to save notification for user {user_id}: {e}")
