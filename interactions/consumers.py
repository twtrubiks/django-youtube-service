# 標準庫 imports
import json
import logging

# 第三方庫 imports
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket 消費者，處理即時通知功能。"""

    async def connect(self):
        """處理 WebSocket 連線。"""
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close()
            return

        self.room_group_name = f"user_{user.id}_notifications"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info("User %s connected to notifications.", user.id)

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
        """接收來自房間群組的訊息並轉發給前端（通知已於來源端持久化，見 services.notify）。

        event["notification"] 與歷史通知 API 的單筆形狀一致（Notification.to_client_dict），
        前端因此共用同一條渲染路徑。
        """
        await self.send(text_data=json.dumps({"notification": event["notification"]}))
