# 標準庫 imports
import logging
import os
import time

# 第三方庫 imports
import ffmpeg
from celery import shared_task

# Django imports
from django.conf import settings
from django.core.files import File

# 本地應用 imports
from .models import Video

logger = logging.getLogger(__name__)


def _get_exception_message(e):
    """
    安全地從異常中提取錯誤訊息，處理 MagicMock 和 bytes 類型。

    Args:
        e: 異常物件

    Returns:
        str: 錯誤訊息字符串
    """
    if hasattr(e, "stderr"):
        if hasattr(e.stderr, "_decode_return_value"):
            try:
                return str(e.stderr._decode_return_value)
            except Exception as inner_e:
                logger.error(f"Error decoding _decode_return_value: {inner_e}")
                return f"Error: {type(e.stderr._decode_return_value).__name__} - {object.__repr__(e.stderr._decode_return_value)}"
        elif hasattr(e.stderr, "decode") and callable(e.stderr.decode):
            try:
                return e.stderr.decode("utf-8", errors="replace")
            except Exception as inner_e:
                logger.error(f"Error decoding stderr bytes: {inner_e}")
                return f"Error: {type(e.stderr).__name__} - {object.__repr__(e.stderr)}"
        else:
            # Fallback for stderr that is not bytes and not our mock
            return str(e.stderr)

    # For generic exceptions or when stderr is not present/handled,
    # ensure a string representation is always returned.
    # Use object.__repr__ to avoid issues with mocked __str__ methods.
    return f"{type(e).__name__}: {object.__repr__(e)}"


def transcode_video(video, original_file_path, file_name_without_ext):
    """轉檔影片為 MP4 格式，回傳輸出檔案路徑。"""
    processed_file_name = f"{file_name_without_ext}_processed.mp4"
    output_dir = os.path.join(settings.MEDIA_ROOT, "videos", "processed_videos")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, processed_file_name)

    logger.info("影片 %s (ID: %s) 開始轉檔...", video.title, video.id)
    start_time = time.time()

    try:
        ffmpeg.input(original_file_path).output(
            output_path, vcodec="libx264", acodec="aac", strict="experimental", movflags="faststart"
        ).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
    except Exception as e:
        if isinstance(e, ffmpeg.Error):
            error_msg = _get_exception_message(e)
            logger.error("影片 %s (ID: %s) 轉檔失敗: %s", video.title, video.id, error_msg)
            video.processing_status = "failed"
            video.save(update_fields=["processing_status"])
            raise
        raise

    elapsed = time.time() - start_time
    logger.info("影片 %s (ID: %s) 轉檔完成，耗時: %.2f 秒", video.title, video.id, elapsed)

    with open(output_path, "rb") as f:
        video.video_file.save(processed_file_name, File(f), save=False)
    video.processing_status = "transcoding_complete"
    video.save(update_fields=["processing_status", "video_file"])
    return output_path


def generate_thumbnail(video, input_file_path, file_name_without_ext):
    """從影片擷取縮圖，回傳縮圖檔案路徑。"""
    thumbnail_file_name = f"{video.id}_{file_name_without_ext}_thumb.jpg"
    thumbnail_dir = os.path.join(settings.MEDIA_ROOT, "thumbnails")
    os.makedirs(thumbnail_dir, exist_ok=True)
    thumbnail_path = os.path.join(thumbnail_dir, thumbnail_file_name)

    logger.info("影片 %s (ID: %s) 開始產生縮圖...", video.title, video.id)
    start_time = time.time()

    try:
        ffmpeg.input(input_file_path).output(
            thumbnail_path, vframes=1, format="image2", vcodec="mjpeg", ss="00:00:01.000"
        ).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
    except Exception as e:
        error_msg = _get_exception_message(e)
        logger.error("影片 %s (ID: %s) 縮圖產生失敗: %s", video.title, video.id, error_msg)
        video.processing_status = "failed"
        video.save(update_fields=["processing_status"])
        raise

    elapsed = time.time() - start_time
    logger.info("影片 %s (ID: %s) 縮圖產生完成，耗時: %.2f 秒", video.title, video.id, elapsed)

    with open(thumbnail_path, "rb") as f:
        video.thumbnail.save(thumbnail_file_name, File(f), save=False)
    video.processing_status = "thumbnail_generated"
    video.save(update_fields=["processing_status", "thumbnail"])
    return thumbnail_path


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_video(self, video_id):
    """
    處理影片任務：包含影片轉檔、縮圖產生，以及 HLS 串流格式轉換。

    Args:
        video_id (int): 要處理的影片 ID

    Returns:
        str: 處理結果訊息
    """
    try:
        video = Video.objects.get(id=video_id)

        if video.processing_status == "completed":
            return f"影片 {video_id} 已處理完成，跳過重複處理。"

        video.processing_status = "processing"
        video.save(update_fields=["processing_status"])

        original_file_path = video.video_file.path
        file_name_without_ext = os.path.splitext(os.path.basename(original_file_path))[0]

        # Step 1: 轉檔
        output_path = transcode_video(video, original_file_path, file_name_without_ext)

        # Step 2: 產生 HLS（非同步，不阻塞主流程）
        generate_hls_files.delay(video_id, output_path, file_name_without_ext)

        # Step 3: 產生縮圖
        generate_thumbnail(video, output_path, file_name_without_ext)

        video.processing_status = "completed"
        video.save(update_fields=["processing_status"])
        logger.info("影片 %s (ID: %s) 所有處理完成", video.title, video_id)
        return f"影片 {video.title} (ID: {video_id}) 處理成功。"

    except Video.DoesNotExist:
        logger.error("找不到 ID 為 %s 的影片", video_id)
        return f"錯誤：找不到 ID 為 {video_id} 的影片。"
    except ffmpeg.Error as e:
        error_msg = _get_exception_message(e)
        logger.error("影片 %s 處理失敗 (ffmpeg): %s", video_id, error_msg)
        try:
            Video.objects.filter(id=video_id).update(processing_status="failed")
        except Exception:
            logger.exception("設定影片 %s 失敗狀態時發生錯誤", video_id)
        return f"影片 {video_id} 轉檔失敗: {error_msg}"
    except OSError as e:
        raise self.retry(exc=e) from e
    except Exception as e:
        error_msg = _get_exception_message(e)
        logger.exception("處理影片 %s 時發生未預期錯誤: %s", video_id, error_msg)
        try:
            Video.objects.filter(id=video_id).update(processing_status="failed")
        except Exception:
            logger.exception("設定影片 %s 失敗狀態時發生錯誤", video_id)
        return f"處理影片 {video_id} 時發生未預期錯誤。詳見伺服器日誌。"


@shared_task
def generate_hls_files(video_id, input_file_path, file_name_without_ext):
    """生成 HLS (HTTP Live Streaming) 文件（獨立 Celery 任務）。"""
    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.error("HLS 生成失敗：找不到影片 ID %s", video_id)
        return False

    try:
        hls_dir_name = "hls"
        video_hls_dir = f"{video.id}_{file_name_without_ext}"
        hls_output_directory = os.path.join(str(settings.MEDIA_ROOT), hls_dir_name, video_hls_dir)
        os.makedirs(hls_output_directory, exist_ok=True)

        playlist_filename = "playlist.m3u8"
        playlist_path = os.path.join(hls_output_directory, playlist_filename)

        logger.info("開始為影片 %s (ID: %s) 生成 HLS 文件...", video.title, video.id)
        start_time = time.time()

        (
            ffmpeg.input(input_file_path)
            .output(
                playlist_path,
                format="hls",
                hls_time=10,
                hls_list_size=0,
                hls_segment_filename=os.path.join(str(hls_output_directory), "segment_%03d.ts"),
            )
            .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        )

        elapsed = time.time() - start_time
        logger.info("影片 %s (ID: %s) HLS 文件生成完成，耗時: %.2f 秒", video.title, video.id, elapsed)

        video.hls_path = os.path.join(hls_dir_name, video_hls_dir, playlist_filename)
        video.save(update_fields=["hls_path"])
        return True

    except Exception:
        logger.exception("生成 HLS 文件失敗 (影片 ID: %s)", video.id)
        return False
