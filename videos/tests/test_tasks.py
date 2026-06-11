"""Celery 任務測試：轉檔 codec 判斷、process_video 與 HLS 生成。"""

import os
from unittest.mock import MagicMock, mock_open, patch

import ffmpeg
from celery.exceptions import MaxRetriesExceededError, Retry
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from videos.models import Video
from videos.tasks import _resolve_transcode_codecs, generate_hls_files, process_video

from .base import TestConstants


class ResolveTranscodeCodecsTests(TestCase):
    """轉檔 codec 判斷測試：來源相容時 stream copy，否則重新編碼"""

    def _probe(self, video_stream, audio_stream=None):
        streams = [dict(video_stream, codec_type="video")]
        if audio_stream:
            streams.append(dict(audio_stream, codec_type="audio"))
        return {"streams": streams, "format": {"duration": "10.0"}}

    def test_h264_aac_source_copies_both(self):
        probe = self._probe({"codec_name": "h264", "pix_fmt": "yuv420p"}, {"codec_name": "aac"})
        self.assertEqual(_resolve_transcode_codecs(probe), ("copy", "copy"))

    def test_non_aac_audio_still_copies_video(self):
        probe = self._probe({"codec_name": "h264", "pix_fmt": "yuv420p"}, {"codec_name": "mp3"})
        self.assertEqual(_resolve_transcode_codecs(probe), ("copy", "aac"))

    def test_10bit_h264_reencodes_video(self):
        """High 10（10-bit）瀏覽器播不了，不能 remux"""
        probe = self._probe({"codec_name": "h264", "pix_fmt": "yuv420p10le"}, {"codec_name": "aac"})
        self.assertEqual(_resolve_transcode_codecs(probe), ("libx264", "copy"))

    def test_non_h264_source_reencodes(self):
        probe = self._probe({"codec_name": "vp9", "pix_fmt": "yuv420p"}, {"codec_name": "opus"})
        self.assertEqual(_resolve_transcode_codecs(probe), ("libx264", "aac"))

    def test_h264_without_audio_copies_video(self):
        probe = self._probe({"codec_name": "h264", "pix_fmt": "yuv420p"})
        self.assertEqual(_resolve_transcode_codecs(probe), ("copy", "aac"))


class ProcessVideoTaskTests(TestCase):
    """影片處理任務測試"""

    def setUp(self):
        """設置測試數據"""
        self.user = User.objects.create_user(username="task_user_videos", password="password123")

        self.video_file_content = b"dummy video content for task in videos app"
        self.original_video_filename = f"original_for_task_{timezone.now().timestamp()}.mp4"
        self.original_video_file = SimpleUploadedFile(
            self.original_video_filename, self.video_file_content, "video/mp4"
        )

        self.video = Video.objects.create(
            title="Video for Task Processing in Videos App", uploader=self.user, video_file=self.original_video_file
        )

    @patch("interactions.tasks.notify_subscribers_of_new_video.delay")
    @patch("videos.tasks.generate_hls_files")
    @patch("videos.tasks.ffmpeg")
    @patch("videos.tasks.os.path.exists")
    @patch("videos.tasks.os.makedirs")
    @patch("videos.tasks.open", new_callable=mock_open)
    def test_process_video_successful(
        self,
        mock_open_file,
        mock_os_makedirs,
        mock_os_path_exists,
        mock_ffmpeg_module,
        mock_generate_hls,
        mock_notify_subscribers,
    ):
        """測試影片處理成功的情況"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.VALID_PROBE_RESULT
        mock_os_path_exists.return_value = True
        mock_generate_hls.return_value = True

        mock_run_method = MagicMock(
            side_effect=[(b"stdout_transcode", b"stderr_transcode"), (b"stdout_thumbnail", b"stderr_thumbnail")]
        )

        mock_output_stream = MagicMock()
        mock_output_stream.run = mock_run_method

        mock_input_stream = MagicMock()
        mock_input_stream.output.return_value = mock_output_stream

        mock_ffmpeg_module.input.return_value = mock_input_stream

        # 設定 mock_open 的行為，確保能正確處理檔案讀取
        # 第一次呼叫：讀取處理後的影片檔案
        # 第二次呼叫：寫入處理後的影片檔案
        # 第三次呼叫：讀取縮圖檔案
        # 第四次呼叫：寫入縮圖檔案
        mock_open_file.return_value.read.side_effect = [
            b"dummy processed video content",
            b"",
            b"dummy thumbnail content",
            b"",
        ]
        mock_open_file.return_value.write.return_value = None

        # 使用 patch 來避免實際的檔案操作
        with patch("django.db.models.fields.files.FieldFile.save", autospec=True) as mock_file_save:
            result = process_video(self.video.id)
            self.video.refresh_from_db()

            self.assertEqual(
                self.video.processing_status,
                "completed",
                f"Processing status was {self.video.processing_status}, expected 'completed'. Result: {result}",
            )

            # 驗證 FieldFile.save 被調用了兩次（影片檔案和縮圖檔案）
            self.assertEqual(mock_file_save.call_count, 2)

            # 驗證第一次調用是保存處理後的影片檔案
            first_call_args = mock_file_save.call_args_list[0]
            self.assertTrue(first_call_args[0][1].endswith("_processed.mp4"))

            # 驗證第二次調用是保存縮圖檔案
            second_call_args = mock_file_save.call_args_list[1]
            self.assertTrue(second_call_args[0][1].endswith("_thumb.jpg"))

            self.assertEqual(mock_ffmpeg_module.input.call_count, 2)
            self.assertIn(f"影片 {self.video.title} (ID: {self.video.id}) 處理成功。", result)

            # 處理完成後應派發訂閱者通知 fan-out 任務
            mock_notify_subscribers.assert_called_once_with(self.video.id)

    @patch("videos.tasks.ffmpeg")
    @patch("videos.tasks.os.path.exists", MagicMock(return_value=True))
    @patch("videos.tasks.os.makedirs", MagicMock())
    def test_process_video_transcoding_fails(self, mock_ffmpeg_module):
        """測試影片轉檔失敗的情況"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.VALID_PROBE_RESULT
        mock_ffmpeg_module.input.return_value.output.return_value.run.side_effect = ffmpeg.Error(
            "ffmpeg_run", stdout=b"", stderr=b"Transcoding failed error message from mock"
        )

        result = process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "failed")
        self.assertIn("轉檔失敗", result)
        self.assertIn("Transcoding failed error message from mock", result)
        self.assertEqual(mock_ffmpeg_module.input.call_count, 1)

    @patch("interactions.tasks.notify_subscribers_of_new_video.delay", MagicMock())
    @patch("videos.tasks.generate_hls_files", MagicMock())
    @patch("videos.tasks.os.path.exists", MagicMock(return_value=True))
    @patch("videos.tasks.os.makedirs", MagicMock())
    @patch("videos.tasks.open", mock_open())
    @patch("videos.tasks.ffmpeg")
    def test_process_video_remuxes_h264_aac_source(self, mock_ffmpeg_module):
        """來源已是 H.264/AAC 時，轉檔改用 stream copy（remux），不重新編碼"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.H264_AAC_PROBE_RESULT
        mock_ffmpeg_module.input.return_value.output.return_value.run.return_value = (b"", b"")

        with patch("django.db.models.fields.files.FieldFile.save", autospec=True):
            process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "completed")

        transcode_kwargs = mock_ffmpeg_module.input.return_value.output.call_args_list[0][1]
        self.assertEqual(transcode_kwargs["vcodec"], "copy")
        self.assertEqual(transcode_kwargs["acodec"], "copy")

    @patch("interactions.tasks.notify_subscribers_of_new_video.delay", MagicMock())
    @patch("videos.tasks.generate_hls_files", MagicMock())
    @patch("videos.tasks.os.path.exists", MagicMock(return_value=True))
    @patch("videos.tasks.os.makedirs", MagicMock())
    @patch("videos.tasks.open", mock_open())
    @patch("videos.tasks.ffmpeg")
    def test_process_video_falls_back_to_reencode_when_remux_fails(self, mock_ffmpeg_module):
        """remux 失敗時自動退回完整重新編碼，處理仍成功"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.H264_AAC_PROBE_RESULT
        mock_ffmpeg_module.input.return_value.output.return_value.run.side_effect = [
            ffmpeg.Error("remux", stdout=b"", stderr=b"copy failed"),  # remux 嘗試失敗
            (b"", b""),  # 退回重新編碼成功
            (b"", b""),  # 縮圖
        ]

        with patch("django.db.models.fields.files.FieldFile.save", autospec=True):
            process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "completed")

        output_calls = mock_ffmpeg_module.input.return_value.output.call_args_list
        self.assertEqual(output_calls[0][1]["vcodec"], "copy")
        self.assertEqual(output_calls[1][1]["vcodec"], "libx264")
        self.assertEqual(output_calls[1][1]["acodec"], "aac")

    @patch("videos.tasks.ffmpeg")
    def test_process_video_rejects_unparseable_file(self, mock_ffmpeg_module):
        """ffprobe 解不開的檔案在預檢階段直接標記失敗，不進入轉檔"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.side_effect = ffmpeg.Error("ffprobe", stdout=b"", stderr=b"Invalid data found")

        result = process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "failed")
        self.assertIn("無法解析影片檔案", result)
        mock_ffmpeg_module.input.assert_not_called()

    @patch("videos.tasks.ffmpeg")
    def test_process_video_rejects_file_without_video_stream(self, mock_ffmpeg_module):
        """沒有影片軌的檔案（如純音訊）在預檢階段直接標記失敗"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "60.0"},
        }

        result = process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "failed")
        self.assertIn("沒有影片軌", result)
        mock_ffmpeg_module.input.assert_not_called()

    @patch("videos.tasks.ffmpeg")
    def test_process_video_rejects_too_long_video(self, mock_ffmpeg_module):
        """超過時長上限的影片在預檢階段直接標記失敗"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = {
            "streams": [{"codec_type": "video", "width": 1280, "height": 720}],
            "format": {"duration": "61.0"},
        }

        with override_settings(VIDEO_UPLOAD_MAX_DURATION_SECONDS=60):
            result = process_video(self.video.id)

        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "failed")
        self.assertIn("超過上限", result)
        mock_ffmpeg_module.input.assert_not_called()

    @patch("videos.tasks.generate_hls_files")
    @patch("videos.tasks.os.path.exists")
    @patch("videos.tasks.os.makedirs")
    @patch("videos.tasks.open", new_callable=mock_open)
    @patch("videos.tasks.ffmpeg")
    def test_process_video_thumbnail_fails(
        self,
        mock_ffmpeg_module,
        mock_open_file,
        mock_os_makedirs,
        mock_os_path_exists,
        mock_generate_hls,
    ):
        """測試縮圖產生失敗的情況"""
        mock_os_path_exists.return_value = True
        mock_generate_hls.return_value = True
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.VALID_PROBE_RESULT

        thumbnail_error_instance = ffmpeg.Error(
            "ffmpeg_thumb_cmd_for_test",
            stdout=b"mock_stdout_bytes",
            stderr=b"Thumbnail generation failed specific message",
        )

        mock_open_file.return_value.read.side_effect = [
            b"dummy processed video content",
            b"",
            b"dummy thumbnail content",
            b"",
        ]

        ffmpeg_run_mock = MagicMock()
        ffmpeg_run_mock.side_effect = [(None, None), thumbnail_error_instance]
        mock_ffmpeg_module.input.return_value.output.return_value.run = ffmpeg_run_mock

        with patch("django.db.models.fields.files.FieldFile.save", autospec=True) as mock_video_file_save:
            process_video(self.video.id)

            self.video.refresh_from_db()
            self.assertEqual(self.video.processing_status, "failed", f"Actual status: {self.video.processing_status}")

            mock_video_file_save.assert_called_once()
            self.assertTrue(mock_video_file_save.call_args[0][1].endswith("_processed.mp4"))

            self.assertFalse(self.video.thumbnail, f"thumbnail was '{self.video.thumbnail.name}', expected empty.")

            self.assertEqual(mock_ffmpeg_module.input.call_count, 2)

    @patch("interactions.tasks.notify_subscribers_of_new_video.delay")
    @patch("videos.tasks.generate_hls_files")
    @patch("videos.tasks.ffmpeg")
    @patch("videos.tasks.os.makedirs")
    @patch("videos.tasks.open", new_callable=mock_open)
    def test_process_video_removes_original_file_after_transcode(
        self, mock_open_file, mock_os_makedirs, mock_ffmpeg_module, mock_generate_hls, mock_notify_subscribers
    ):
        """轉檔成功並存入 storage 後，原始上傳檔應被刪除"""
        mock_ffmpeg_module.Error = ffmpeg.Error
        mock_ffmpeg_module.probe.return_value = TestConstants.VALID_PROBE_RESULT
        mock_ffmpeg_module.input.return_value.output.return_value.run.return_value = (b"", b"")

        original_path = self.video.video_file.path
        self.assertTrue(os.path.exists(original_path))

        def fake_field_file_save(field_file, name, content, save=True):
            # 模擬 storage 存入新檔案後，FieldFile 指向新路徑
            field_file.name = f"videos/{name}"

        with patch("django.db.models.fields.files.FieldFile.save", autospec=True, side_effect=fake_field_file_save):
            process_video(self.video.id)

        self.assertFalse(os.path.exists(original_path))

    def test_process_video_video_does_not_exist(self):
        """測試處理不存在的影片"""
        result = process_video(99999888777)
        self.assertIn("錯誤：找不到 ID 為 99999888777 的影片。", result)

    def test_process_video_generic_exception_updates_status_to_failed(self):
        """測試處理過程中發生一般異常的情況"""
        self.video.processing_status = "pending"
        self.video.save()

        with (
            patch("videos.tasks.ffmpeg.probe", return_value=TestConstants.VALID_PROBE_RESULT),
            patch("videos.tasks.ffmpeg.input", side_effect=Exception("Unexpected generic error during processing")),
        ):
            result = process_video(self.video.id)

        self.assertIn(f"處理影片 {self.video.id} 時發生未預期錯誤", result)
        self.video.refresh_from_db()
        self.assertEqual(self.video.processing_status, "failed")

    def tearDown(self):
        """清理測試數據"""
        if self.video and self.video.video_file:
            try:
                original_path = os.path.join(settings.MEDIA_ROOT, self.original_video_filename)
                if os.path.exists(original_path):
                    os.remove(original_path)
            except Exception:
                pass


class HLSFunctionalityTests(TestCase):
    """
    測試 HLS (HTTP Live Streaming) 相關功能
    """

    def setUp(self):
        self.user = User.objects.create_user(username="hls_user", password="password123")
        self.video = Video.objects.create(
            title="HLS Test Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("hls_test.mp4", b"video content", content_type="video/mp4"),
            visibility="public",
        )

    def test_video_hls_path_field_exists(self):
        """
        測試 Video 模型是否有 hls_path 欄位
        """
        self.assertTrue(hasattr(self.video, "hls_path"))
        self.assertIsNone(self.video.hls_path)  # 預設應該是 None

    def test_video_hls_path_can_be_set(self):
        """
        測試可以設定 hls_path
        """
        hls_path = "hls/1_test_video/playlist.m3u8"
        self.video.hls_path = hls_path
        self.video.save()

        self.video.refresh_from_db()
        self.assertEqual(self.video.hls_path, hls_path)

    def test_generate_hls_files_function_exists(self):
        """
        測試 generate_hls_files 函數是否存在
        """
        from videos.tasks import generate_hls_files

        # 測試函數存在
        self.assertTrue(callable(generate_hls_files))

    @patch("videos.tasks.settings.MEDIA_ROOT", "/fake/media")
    @patch("videos.tasks.os.makedirs")
    @patch("videos.tasks.os.path.exists", return_value=True)
    @patch("videos.tasks.open", new_callable=mock_open)
    def test_generate_hls_files_with_mock(self, mock_open_file, mock_exists, mock_makedirs):
        """
        測試 generate_hls_files 函數的完整功能（1080p 來源產生 720p + 1080p 兩種畫質）
        """
        from videos.tasks import generate_hls_files

        with patch("videos.tasks.ffmpeg") as mock_ffmpeg:
            # 設定 ffprobe 與 ffmpeg 調用鏈的模擬
            mock_ffmpeg.probe.return_value = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]}
            mock_input_stream = mock_ffmpeg.input.return_value
            mock_output_stream = mock_input_stream.output.return_value
            mock_output_stream.run.return_value = (b"stdout", b"stderr")

            # 執行 HLS 生成
            result = generate_hls_files(self.video.id, "/fake/input/path.mp4", "test_video")

            # 驗證結果
            self.assertTrue(result)

            # 每個畫質各跑一次 ffmpeg
            self.assertEqual(mock_ffmpeg.input.call_count, 2)
            self.assertEqual(mock_output_stream.run.call_count, 2)

            # master.m3u8 應串接兩種畫質的子 playlist
            written = "".join(call.args[0] for call in mock_open_file().write.call_args_list)
            self.assertIn("720p/playlist.m3u8", written)
            self.assertIn("1080p/playlist.m3u8", written)
            self.assertIn("RESOLUTION=1280x720", written)
            self.assertIn("RESOLUTION=1920x1080", written)

            # 驗證影片的 hls_path 與 hls_status 被設置
            self.video.refresh_from_db()
            self.assertIn("master.m3u8", self.video.hls_path)
            self.assertEqual(self.video.hls_status, "completed")

    def test_generate_hls_files_retries_on_failure(self):
        """測試 generate_hls_files 失敗時會觸發重試"""
        with (
            patch("videos.tasks.ffmpeg") as mock_ffmpeg,
            patch("videos.tasks.os.makedirs"),
            patch.object(generate_hls_files, "retry", side_effect=Retry("retrying")) as mock_retry,
        ):
            mock_ffmpeg.probe.return_value = {"streams": [{"codec_type": "video", "width": 1280, "height": 720}]}
            mock_ffmpeg.input.side_effect = Exception("Mock ffmpeg error")

            # 還有重試額度時，retry 會拋出 Retry 交由 Celery 重新排程
            with self.assertRaises(Retry):
                generate_hls_files(self.video.id, "/fake/path.mp4", "test")

            mock_retry.assert_called_once()

    def test_generate_hls_files_marks_failed_when_retries_exhausted(self):
        """測試重試耗盡後 hls_status 標記為 failed 且回傳 False"""
        with (
            patch("videos.tasks.ffmpeg") as mock_ffmpeg,
            patch("videos.tasks.os.makedirs"),
            patch.object(generate_hls_files, "retry", side_effect=MaxRetriesExceededError()),
        ):
            mock_ffmpeg.probe.return_value = {"streams": [{"codec_type": "video", "width": 1280, "height": 720}]}
            mock_ffmpeg.input.side_effect = Exception("Mock ffmpeg error")

            result = generate_hls_files(self.video.id, "/fake/path.mp4", "test")

            self.assertFalse(result)
            self.video.refresh_from_db()
            self.assertEqual(self.video.hls_status, "failed")

    @patch("videos.tasks.open", new_callable=mock_open)
    @patch("videos.tasks.os.makedirs")
    def test_generate_hls_files_removes_input_copy_on_success(self, mock_makedirs, mock_open_file):
        """HLS 生成成功後，processed_videos 中的轉檔暫存副本應被刪除"""
        processed_dir = os.path.join(settings.MEDIA_ROOT, "videos", "processed_videos")
        os.makedirs(processed_dir, exist_ok=True)
        input_copy = os.path.join(processed_dir, "hls_input_test_processed.mp4")
        with open(input_copy, "wb") as f:
            f.write(b"processed content")

        with patch("videos.tasks.ffmpeg") as mock_ffmpeg:
            mock_ffmpeg.probe.return_value = {"streams": [{"codec_type": "video", "width": 1280, "height": 720}]}
            mock_ffmpeg.input.return_value.output.return_value.run.return_value = (b"", b"")
            result = generate_hls_files(self.video.id, input_copy, "hls_input_test")

        self.assertTrue(result)
        self.assertFalse(os.path.exists(input_copy))

    @patch("videos.tasks.open", new_callable=mock_open)
    @patch("videos.tasks.os.makedirs")
    def test_generate_hls_files_keeps_input_outside_processed_dir(self, mock_makedirs, mock_open_file):
        """輸入檔不在 processed_videos 內（如 admin 重新生成）時，不應被刪除"""
        input_path = self.video.video_file.path  # 位於 media/videos/

        with patch("videos.tasks.ffmpeg") as mock_ffmpeg:
            mock_ffmpeg.probe.return_value = {"streams": [{"codec_type": "video", "width": 1280, "height": 720}]}
            mock_ffmpeg.input.return_value.output.return_value.run.return_value = (b"", b"")
            result = generate_hls_files(self.video.id, input_path, "hls_keep_test")

        self.assertTrue(result)
        self.assertTrue(os.path.exists(input_path))

    def test_generate_hls_files_skips_when_already_completed(self):
        """測試 HLS 已完成時跳過重複生成（冪等保護）"""
        self.video.hls_path = "hls/1_test/playlist.m3u8"
        self.video.hls_status = "completed"
        self.video.save()

        with patch("videos.tasks.ffmpeg") as mock_ffmpeg:
            result = generate_hls_files(self.video.id, "/fake/path.mp4", "test")

            self.assertTrue(result)
            mock_ffmpeg.input.assert_not_called()

    def test_select_renditions_no_upscale(self):
        """測試畫質挑選不會向上放大：來源高度決定產出的畫質清單"""
        from videos.tasks import _select_renditions

        self.assertEqual([r["name"] for r in _select_renditions(720)], ["720p"])
        self.assertEqual([r["name"] for r in _select_renditions(1080)], ["720p", "1080p"])
        self.assertEqual([r["name"] for r in _select_renditions(2160)], ["720p", "1080p"])

    def test_select_renditions_low_resolution_source(self):
        """測試來源低於 720p 時，以來源高度輸出單一畫質"""
        from videos.tasks import _select_renditions

        renditions = _select_renditions(480)
        self.assertEqual(len(renditions), 1)
        self.assertEqual(renditions[0]["name"], "480p")
        self.assertEqual(renditions[0]["height"], 480)

    def test_admin_regenerate_hls_action(self):
        """測試 admin 重新生成 HLS action 會重設狀態並排程任務"""
        from django.contrib.admin.sites import AdminSite

        from videos.admin import VideoAdmin

        self.video.hls_status = "failed"
        self.video.save()

        model_admin = VideoAdmin(Video, AdminSite())
        with (
            patch("videos.admin.generate_hls_files.delay") as mock_delay,
            patch.object(VideoAdmin, "message_user") as mock_message,
        ):
            model_admin.regenerate_hls(None, Video.objects.filter(id=self.video.id))

        self.video.refresh_from_db()
        self.assertEqual(self.video.hls_status, "pending")
        mock_delay.assert_called_once()
        self.assertEqual(mock_delay.call_args[0][0], self.video.id)
        mock_message.assert_called_once()

    def test_media_auth_url_pattern(self):
        """
        測試 nginx auth_request 子請求端點的 URL 模式（需與 nginx.conf 的 proxy_pass 一致）
        """
        from django.urls import reverse

        self.assertEqual(reverse("videos:media_auth"), "/videos/media-auth/")

    def test_video_hls_url_property(self):
        """
        測試 hls_url property 組出 nginx 直接服務的媒體 URL
        """
        self.assertIsNone(self.video.hls_url)
        self.video.hls_path = "hls/1_test_video/master.m3u8"
        self.assertEqual(self.video.hls_url, "/media/hls/1_test_video/master.m3u8")

    def test_video_hls_url_property_encodes_unicode_path(self):
        """
        測試 hls_url 對中文路徑做百分比編碼
        """
        self.video.hls_path = "hls/1_中文影片/master.m3u8"
        self.assertEqual(self.video.hls_url, "/media/hls/1_%E4%B8%AD%E6%96%87%E5%BD%B1%E7%89%87/master.m3u8")
