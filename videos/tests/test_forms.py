"""表單測試：CategoryForm、VideoUploadForm、VideoEditForm。"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from videos.forms import CategoryForm, VideoEditForm, VideoUploadForm
from videos.models import Category, Video

from .base import BaseVideoTestCase


class CategoryFormTests(BaseVideoTestCase):
    """分類表單測試"""

    def test_category_form_valid_data(self):
        """測試有效的分類表單數據"""
        form_data = {"name": "New Category"}
        form = CategoryForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_category_form_missing_name(self):
        """測試缺少名稱的表單驗證"""
        form_data = {}
        form = CategoryForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_category_form_name_already_exists(self):
        """測試重複名稱的表單驗證"""
        Category.objects.create(name="Existing Category")
        form_data = {"name": "Existing Category"}
        form = CategoryForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)


class VideoUploadFormTests(BaseVideoTestCase):
    """影片上傳表單測試"""

    def setUp(self):
        """設置測試數據"""
        self.user = self.create_test_user("formtestuser")
        self.category = self.create_test_category("Form Test Category")
        self.video_file = self.create_test_video_file("form_video.mp4")
        self.thumbnail_file = self.create_test_image_file("form_thumb.png")

    def test_video_upload_form_valid_data_all_fields(self):
        form_data = {
            "title": "Test Upload Video",
            "description": "A description for upload.",
            "visibility": "public",
            "category": self.category.id,
            "tags": "tag1, tag2",
        }
        file_data = {
            "video_file": self.video_file,
            "thumbnail": self.thumbnail_file,
        }
        form = VideoUploadForm(data=form_data, files=file_data)
        if not form.is_valid():
            print("VideoUploadForm errors (all_fields):", form.errors.as_json())
        self.assertTrue(form.is_valid(), msg=f"Form errors (all_fields): {form.errors.as_json()}")

    def test_video_upload_form_valid_data_minimum_fields(self):
        form_data = {
            "title": "Minimal Video",
            "visibility": "public",
        }
        file_data = {"video_file": self.video_file}

        form = VideoUploadForm(data=form_data, files=file_data)
        if not form.is_valid():
            print("VideoUploadForm errors (minimum_fields):", form.errors.as_json())
        self.assertTrue(form.is_valid(), msg=f"Form errors (minimum_fields): {form.errors.as_json()}")

    def test_video_upload_form_missing_title_uses_filename(self):
        """未填標題時，自動以檔名（去副檔名）作為預設標題"""
        form_data = {"visibility": "public"}
        file_data = {"video_file": self.video_file}
        form = VideoUploadForm(data=form_data, files=file_data)
        self.assertTrue(form.is_valid(), msg=f"Form errors: {form.errors.as_json()}")
        self.assertEqual(form.cleaned_data["title"], "form_video")

    def test_video_upload_form_missing_video_file_for_new_instance(self):
        form_data = {"title": "Video without file"}
        form = VideoUploadForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("video_file", form.errors)

    def test_video_edit_form_has_no_video_file_field(self):
        """編輯表單不含 video_file 欄位（影片檔上傳後不可更換）"""
        existing_video = Video.objects.create(
            title="Existing Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("existing.mp4", b"content", "video/mp4"),
        )
        form_data = {
            "title": "Updated Existing Video Title",
            "description": "Updated description.",
            "visibility": "private",
        }
        form = VideoEditForm(data=form_data, instance=existing_video)
        self.assertTrue(form.is_valid(), msg=f"Form errors (editing): {form.errors.as_json()}")
        self.assertNotIn("video_file", form.fields)
        self.assertFalse(form.fields["thumbnail"].required)

    def test_video_upload_form_rejects_oversized_file(self):
        """超過大小上限的影片檔應被拒絕"""
        with override_settings(VIDEO_UPLOAD_MAX_SIZE_MB=1):
            big_file = SimpleUploadedFile("big.mp4", b"x" * (1024 * 1024 + 1), content_type="video/mp4")
            form = VideoUploadForm(data={"title": "Big", "visibility": "public"}, files={"video_file": big_file})
            self.assertFalse(form.is_valid())
            self.assertIn("video_file", form.errors)
            self.assertIn("too large", form.errors["video_file"][0])

    def test_video_upload_form_rejects_disallowed_extension(self):
        """不在允許清單內的副檔名應被拒絕"""
        bad_file = SimpleUploadedFile("notavideo.exe", b"content", content_type="video/mp4")
        form = VideoUploadForm(data={"title": "Bad", "visibility": "public"}, files={"video_file": bad_file})
        self.assertFalse(form.is_valid())
        self.assertIn("video_file", form.errors)
        self.assertIn("Unsupported file format", form.errors["video_file"][0])

    def test_video_upload_form_invalid_category(self):
        form_data = {
            "title": "Video with Invalid Category",
            "category": 999,
        }
        file_data = {"video_file": self.video_file}
        form = VideoUploadForm(data=form_data, files=file_data)
        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)
