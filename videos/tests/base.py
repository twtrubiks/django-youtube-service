"""共用測試基礎：測試常量與 BaseVideoTestCase。"""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from videos.models import Category, Video


class TestConstants:
    """測試用常量"""

    DEFAULT_PASSWORD = "password123"
    VIDEO_CONTENT = b"dummy video content"
    # process_video 的 ffprobe 預檢需要 probe 回傳有效結果才能進入轉檔流程
    VALID_PROBE_RESULT = {
        "streams": [{"codec_type": "video", "width": 1280, "height": 720}],
        "format": {"duration": "120.0"},
    }
    # 來源已是 H.264/AAC，轉檔應走 stream copy（remux）路徑
    H264_AAC_PROBE_RESULT = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "120.0"},
    }
    VALID_PNG_CONTENT = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd7c`\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc\x33\x00\x00\x00\x00IEND\xaeB`\x82"
    )


class BaseVideoTestCase(TestCase):
    """基礎測試類別，提供共用的設置方法"""

    def create_test_user(self, username="testuser", is_staff=False):
        """創建測試用戶"""
        return User.objects.create_user(username=username, password=TestConstants.DEFAULT_PASSWORD, is_staff=is_staff)

    def create_test_category(self, name="Test Category", slug=None):
        """創建測試分類"""
        return Category.objects.create(name=name, slug=slug)

    def create_test_video_file(self, filename="test.mp4"):
        """創建測試影片文件"""
        return SimpleUploadedFile(filename, TestConstants.VIDEO_CONTENT, content_type="video/mp4")

    def create_test_image_file(self, filename="test.png"):
        """創建測試圖片文件"""
        return SimpleUploadedFile(filename, TestConstants.VALID_PNG_CONTENT, content_type="image/png")

    def create_test_video(self, title="Test Video", uploader=None, category=None, **kwargs):
        """創建測試影片"""
        if uploader is None:
            uploader = self.create_test_user()

        defaults = {
            "title": title,
            "uploader": uploader,
            "video_file": self.create_test_video_file(),
            "visibility": "public",
        }
        defaults.update(kwargs)

        if category:
            defaults["category"] = category

        return Video.objects.create(**defaults)
