import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User
from .models import Notification

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):

        # 暫時先允許所有連線，之後再加入使用者驗證
        self.room_group_name = f"user_{self.scope['url_route']['kwargs']['user_id']}_notifications"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
        print(f"User {self.scope['url_route']['kwargs']['user_id']} connected to notifications.")

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            print(f"User disconnected from notifications: {self.room_group_name}")

    # Receive message from WebSocket (not typically used for server-to-client notifications)
    async def receive(self, text_data):
        # text_data_json = json.loads(text_data)
        # message = text_data_json['message']
        # print(f"Received message: {message} from {self.room_group_name}")
        pass # 通常通知是由伺服器主動發送，而不是接收來自客戶端的訊息

    # Receive message from room group
    async def send_notification(self, event):
        print(f"[consumers.py] send_notification called for group {self.room_group_name}. Event received: {json.dumps(event)}") # 詳細 log

        original_message_payload = event['message'] # This is usually a dictionary

        # Save notification to database
        try:
            user_id = self.scope['url_route']['kwargs']['user_id']
            await self._save_notification_db(user_id, original_message_payload)
        except Exception as e:
            print(f"Error saving notification to DB: {e}")

        # Prepare message for WebSocket client
        # The client expects a 'type' (e.g., 'new_video') and a 'message' payload
        client_message_type = original_message_payload.get('type', 'generic_notification')

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': client_message_type,
            'message': original_message_payload
        }))
        print(f"[consumers.py] Sent notification data: {json.dumps(original_message_payload)} to client in group {self.room_group_name}")

    @database_sync_to_async
    def _save_notification_db(self, user_id, message_payload):
        try:
            recipient_user = User.objects.get(id=user_id)

            # Extract message text and link from the payload
            # Assuming message_payload is a dict with 'text' and optional 'url'
            notification_text = "Notification" # Default message
            if isinstance(message_payload, dict):
                notification_text = message_payload.get('text', json.dumps(message_payload))
                notification_link = message_payload.get('url', None)
            elif isinstance(message_payload, str):
                notification_text = message_payload # If it's just a string
                notification_link = None
            else:
                notification_text = str(message_payload) # Fallback
                notification_link = None

            Notification.objects.create(
                recipient=recipient_user,
                message=notification_text,
                link=notification_link
                # Optionally, you could add notification_type if you implement it in the model
                # notification_type=message_payload.get('type')
            )
            print(f"Notification saved for user {user_id}: {notification_text[:50]}")
        except User.DoesNotExist:
            print(f"User with id {user_id} not found. Notification not saved.")
        except Exception as e:
            print(f"Failed to save notification for user {user_id}: {e}")
