import os
from celery import Celery

# 設定 Django settings 模組給 Celery。
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'youtube_service.settings')

app = Celery('youtube_service')

# 使用 Django settings 來設定 Celery。
# namespace='CELERY' 表示所有 Celery 相關的設定鍵都應該以 'CELERY_' 開頭。
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自動從所有已註冊的 Django app 中載入 task 模組。
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')