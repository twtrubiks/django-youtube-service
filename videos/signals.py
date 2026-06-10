import logging
import os
import shutil

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Video

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Video)
def cleanup_video_files(sender, instance, **kwargs):
    """影片刪除後清理所有關聯檔案；admin 刪除與帳號級聯刪除也會經過這裡。"""
    if instance.video_file:
        _remove_processed_copy(instance.video_file.name)
        try:
            instance.video_file.delete(save=False)
        except OSError:
            logger.exception("刪除影片檔案失敗: %s", instance.video_file.name)

    if instance.thumbnail:
        try:
            instance.thumbnail.delete(save=False)
        except OSError:
            logger.exception("刪除縮圖檔案失敗: %s", instance.thumbnail.name)

    if instance.hls_path:
        _remove_hls_directory(instance.hls_path)


def _remove_processed_copy(video_file_name):
    """刪除 ffmpeg 轉檔輸出的暫存副本（正常流程在 HLS 完成後已刪，這裡兜底）。"""
    processed_copy = os.path.join(settings.MEDIA_ROOT, "videos", "processed_videos", os.path.basename(video_file_name))
    try:
        if os.path.exists(processed_copy):
            os.remove(processed_copy)
    except OSError:
        logger.exception("刪除轉檔暫存副本失敗: %s", processed_copy)


def _remove_hls_directory(hls_path):
    """刪除影片的 HLS 目錄；realpath 檢查確保只刪 media/hls 底下的目錄。"""
    hls_dir = os.path.realpath(os.path.dirname(os.path.join(settings.MEDIA_ROOT, hls_path)))
    hls_root = os.path.realpath(os.path.join(settings.MEDIA_ROOT, "hls"))
    if not hls_dir.startswith(hls_root + os.sep):
        logger.warning("HLS 路徑不在預期目錄內，跳過刪除: %s", hls_path)
        return
    try:
        shutil.rmtree(hls_dir)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("刪除 HLS 目錄失敗: %s", hls_dir)
