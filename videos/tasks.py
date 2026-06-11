# 標準庫 imports
import logging
import os
import time

# 第三方庫 imports
import ffmpeg
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

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


def _remove_file_if_exists(file_path):
    """刪除檔案，失敗只記 log 不中斷流程。"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        logger.exception("刪除暫存檔案失敗: %s", file_path)


def _remove_hls_input_copy(input_file_path):
    """刪除 HLS 輸入的轉檔暫存副本；僅限 processed_videos 目錄內，避免誤刪 storage 中的影片檔。"""
    processed_dir = os.path.realpath(os.path.join(settings.MEDIA_ROOT, "videos", "processed_videos"))
    real_path = os.path.realpath(input_file_path)
    if real_path.startswith(processed_dir + os.sep):
        _remove_file_if_exists(real_path)


# HLS 多畫質 profile；依來源高度挑選，不向上放大
HLS_RENDITIONS = [
    {
        "name": "720p",
        "height": 720,
        "video_bitrate": "2500k",
        "maxrate": "2675k",
        "bufsize": "3750k",
        "audio_bitrate": "128k",
        "bandwidth": 2800000,
    },
    {
        "name": "1080p",
        "height": 1080,
        "video_bitrate": "5000k",
        "maxrate": "5350k",
        "bufsize": "7500k",
        "audio_bitrate": "192k",
        "bandwidth": 5500000,
    },
]


def _validate_source_video(input_file_path):
    """ffprobe 預檢：確認檔案可解析、含影片軌且不超過時長上限。回傳拒絕原因，通過則回傳 None。"""
    try:
        info = ffmpeg.probe(input_file_path)
    except ffmpeg.Error:
        return "無法解析影片檔案，可能不是有效的影片格式"
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        return "檔案中沒有影片軌"
    duration = float(info.get("format", {}).get("duration", 0))
    max_seconds = settings.VIDEO_UPLOAD_MAX_DURATION_SECONDS
    if duration > max_seconds:
        return f"影片長度 {int(duration)} 秒超過上限 {max_seconds} 秒"
    return None


def _probe_video_dimensions(input_file_path):
    """用 ffprobe 取得影片的寬與高。"""
    info = ffmpeg.probe(input_file_path)
    video_stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
    return int(video_stream["width"]), int(video_stream["height"])


def _select_renditions(source_height):
    """挑選不超過來源高度的畫質；來源低於最低 profile 時，以來源高度輸出單一畫質。"""
    selected = [r for r in HLS_RENDITIONS if r["height"] <= source_height]
    if not selected:
        selected = [dict(HLS_RENDITIONS[0], name=f"{source_height}p", height=source_height)]
    return selected


def _scaled_even_width(source_width, source_height, target_height):
    """依等比例縮放計算寬度，取偶數（libx264 要求寬高為偶數）。"""
    return max(2, 2 * round(source_width * target_height / (source_height * 2)))


def _generate_hls_rendition(input_file_path, rendition_dir, rendition):
    """為單一畫質生成 HLS playlist 與 segments。"""
    os.makedirs(rendition_dir, exist_ok=True)
    playlist_path = os.path.join(rendition_dir, "playlist.m3u8")
    (
        ffmpeg.input(input_file_path)
        .output(
            playlist_path,
            format="hls",
            hls_time=10,
            hls_list_size=0,
            hls_segment_filename=os.path.join(rendition_dir, "segment_%03d.ts"),
            vf=f"scale=-2:{rendition['height']}",
            vcodec="libx264",
            acodec="aac",
            **{
                "b:v": rendition["video_bitrate"],
                "maxrate": rendition["maxrate"],
                "bufsize": rendition["bufsize"],
                "b:a": rendition["audio_bitrate"],
            },
        )
        .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
    )


def _write_master_playlist(hls_output_directory, renditions, source_width, source_height):
    """手寫 master.m3u8，串接各畫質的子 playlist。"""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for rendition in renditions:
        width = _scaled_even_width(source_width, source_height, rendition["height"])
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={rendition['bandwidth']},RESOLUTION={width}x{rendition['height']}")
        lines.append(f"{rendition['name']}/playlist.m3u8")
    master_path = os.path.join(hls_output_directory, "master.m3u8")
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


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

    # 縮圖已存入 storage，刪除 ffmpeg 的暫存輸出
    _remove_file_if_exists(thumbnail_path)
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

        # Step 0: ffprobe 預檢——無效檔案或超長影片直接標記失敗，不進入耗時的轉檔
        rejection = _validate_source_video(original_file_path)
        if rejection:
            video.processing_status = "failed"
            video.save(update_fields=["processing_status"])
            logger.warning("影片 %s (ID: %s) 預檢未通過: %s", video.title, video_id, rejection)
            return f"影片 {video_id} 預檢未通過: {rejection}"

        # Step 1: 轉檔
        output_path = transcode_video(video, original_file_path, file_name_without_ext)

        # 轉檔結果已存入 storage，原始上傳檔不再被引用，刪除以釋放空間
        if original_file_path != video.video_file.path:
            _remove_file_if_exists(original_file_path)

        # Step 2: 產生縮圖
        generate_thumbnail(video, output_path, file_name_without_ext)

        # Step 3: 產生 HLS（非同步，不阻塞主流程）
        # 最後派發：HLS 任務是 output_path 的最後使用者，完成後會負責清理該暫存副本
        generate_hls_files.delay(video_id, output_path, file_name_without_ext)

        video.processing_status = "completed"
        video.save(update_fields=["processing_status"])

        # 處理完成才通知訂閱者，確保點開通知時影片已可播放
        if video.visibility == "public":
            from interactions.tasks import notify_subscribers_of_new_video  # 函式內 import，避免跨 app 循環相依

            notify_subscribers_of_new_video.delay(video.id)

        logger.info("影片 %s (ID: %s) 轉檔與縮圖完成（HLS 仍在背景生成中）", video.title, video_id)
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


@shared_task(bind=True, max_retries=3, default_retry_delay=60, soft_time_limit=3300, time_limit=3600)
def generate_hls_files(self, video_id, input_file_path, file_name_without_ext):
    """生成多畫質 HLS 文件（adaptive bitrate；失敗自動重試，重試耗盡標記 hls_status=failed）。

    每個畫質輸出到獨立子目錄（如 720p/、1080p/），最後手寫 master.m3u8 串接，
    hls_path 指向 master.m3u8。多畫質轉檔耗時較長，任務層級放寬時間限制至 60 分鐘。
    """
    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.error("HLS 生成失敗：找不到影片 ID %s", video_id)
        return False

    if video.hls_status == "completed" and video.hls_path:
        return True

    video.hls_status = "processing"
    video.save(update_fields=["hls_status"])

    try:
        source_width, source_height = _probe_video_dimensions(input_file_path)
        renditions = _select_renditions(source_height)

        hls_dir_name = "hls"
        video_hls_dir = f"{video.id}_{file_name_without_ext}"
        hls_output_directory = os.path.join(str(settings.MEDIA_ROOT), hls_dir_name, video_hls_dir)
        os.makedirs(hls_output_directory, exist_ok=True)

        rendition_names = ", ".join(r["name"] for r in renditions)
        logger.info("開始為影片 %s (ID: %s) 生成 HLS 文件（畫質: %s）...", video.title, video.id, rendition_names)
        start_time = time.time()

        for rendition in renditions:
            rendition_dir = os.path.join(hls_output_directory, rendition["name"])
            _generate_hls_rendition(input_file_path, rendition_dir, rendition)

        _write_master_playlist(hls_output_directory, renditions, source_width, source_height)

        elapsed = time.time() - start_time
        logger.info(
            "影片 %s (ID: %s) HLS 文件生成完成（畫質: %s），耗時: %.2f 秒",
            video.title,
            video.id,
            rendition_names,
            elapsed,
        )

        video.hls_path = os.path.join(hls_dir_name, video_hls_dir, "master.m3u8")
        video.hls_status = "completed"
        video.save(update_fields=["hls_path", "hls_status"])

        # HLS 生成完畢，轉檔暫存副本不再需要
        _remove_hls_input_copy(input_file_path)
        return True

    except Exception as exc:
        logger.exception("生成 HLS 文件失敗 (影片 ID: %s)", video.id)
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error("影片 ID %s 的 HLS 生成已達重試上限，標記為 failed", video_id)
            Video.objects.filter(id=video_id).update(hls_status="failed")
            # 重試已耗盡，暫存副本不再需要（admin 重新生成走 storage 中的影片檔）
            _remove_hls_input_copy(input_file_path)
            return False
