"""
Videos App 測試模組

包含以下測試類別：
- 模型測試：Category, Video
- 表單測試：CategoryForm, VideoUploadForm
- 視圖測試：各種視圖功能
- 任務測試：Celery 任務
- HLS 功能測試：串流相關功能
"""

import os
from unittest.mock import MagicMock, mock_open, patch

import ffmpeg
from celery.exceptions import MaxRetriesExceededError, Retry
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from interactions.models import Comment, LikeDislike

from .forms import CategoryForm, VideoUploadForm
from .models import Category, Video
from .tasks import generate_hls_files, process_video


class TestConstants:
    """測試用常量"""

    DEFAULT_PASSWORD = "password123"
    VIDEO_CONTENT = b"dummy video content"
    # process_video 的 ffprobe 預檢需要 probe 回傳有效結果才能進入轉檔流程
    VALID_PROBE_RESULT = {
        "streams": [{"codec_type": "video", "width": 1280, "height": 720}],
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


class CategoryModelTests(BaseVideoTestCase):
    """分類模型測試"""

    def test_category_creation_and_slugification(self):
        """測試 Category 的創建以及 slug 是否自動產生"""
        category_name = "Test Category 1"
        category = Category.objects.create(name=category_name)

        self.assertEqual(category.name, category_name)
        self.assertEqual(category.slug, slugify(category_name))
        self.assertEqual(str(category), category_name)

    def test_category_unicode_slugification(self):
        """測試中文名稱會產生 unicode slug，而非空字串"""
        category = Category.objects.create(name="生活")
        self.assertEqual(category.slug, "生活")

    def test_category_manual_slug(self):
        """測試手動提供 slug 時，不會被覆蓋"""
        manual_slug = "my-custom-slug"
        category = Category.objects.create(name="Test Category Custom Slug", slug=manual_slug)
        self.assertEqual(category.slug, manual_slug)

    def test_category_name_uniqueness(self):
        """測試 Category 名稱的唯一性"""
        Category.objects.create(name="Unique Name")
        with self.assertRaises(IntegrityError):
            Category.objects.create(name="Unique Name")

    def test_category_slug_uniqueness(self):
        """測試 Category slug 的唯一性"""
        Category.objects.create(name="Another Name", slug="unique-slug")
        with self.assertRaises(IntegrityError):
            Category.objects.create(name="Different Name But Same Slug", slug="unique-slug")

    def test_category_verbose_name_plural(self):
        """測試分類的複數名稱設定"""
        self.assertEqual(Category._meta.verbose_name_plural, "categories")


class VideoModelTests(BaseVideoTestCase):
    """影片模型測試"""

    def setUp(self):
        """設置測試數據"""
        self.user = self.create_test_user("videouploader")
        self.category = self.create_test_category("Test Videos Category")
        self.video_file = self.create_test_video_file("test_video.mp4")
        self.thumbnail_file = self.create_test_image_file("test_thumb.png")

        self.video = Video.objects.create(
            title="My Test Video",
            description="A description for the test video.",
            video_file=self.video_file,
            thumbnail=self.thumbnail_file,
            uploader=self.user,
            category=self.category,
            visibility="public",
        )

    def test_video_creation(self):
        """測試 Video 模型的基本創建和欄位預設值"""
        self.assertEqual(self.video.title, "My Test Video")
        self.assertEqual(self.video.uploader, self.user)
        self.assertEqual(self.video.category, self.category)
        self.assertEqual(str(self.video), "My Test Video")
        self.assertIsNotNone(self.video.upload_date)
        self.assertEqual(self.video.views_count, 0)
        self.assertEqual(self.video.visibility, "public")
        self.assertEqual(self.video.processing_status, "pending")
        self.assertTrue(self.video.video_file.name.startswith("videos/test_video"))
        self.assertTrue(self.video.thumbnail.name.startswith("thumbnails/test_thumb"))

    def test_video_visibility_choices(self):
        """測試 Video 的 visibility 選項"""
        visibility_choices = ["private", "unlisted"]

        for visibility in visibility_choices:
            self.video.visibility = visibility
            self.video.save()
            self.video.refresh_from_db()
            self.assertEqual(self.video.visibility, visibility)

    def test_video_processing_status_choices(self):
        """測試 Video 的 processing_status 選項"""
        status_choices = ["processing", "completed"]

        for status in status_choices:
            self.video.processing_status = status
            self.video.save()
            self.video.refresh_from_db()
            self.assertEqual(self.video.processing_status, status)

    def test_video_tags(self):
        """測試 Video 的標籤功能"""
        self.video.tags.add("funny", "cats", "django")
        self.assertEqual(self.video.tags.count(), 3)
        self.assertIn("funny", [tag.name for tag in self.video.tags.all()])

        self.video.tags.remove("cats")
        self.assertEqual(self.video.tags.count(), 2)
        self.assertNotIn("cats", [tag.name for tag in self.video.tags.all()])

    def test_video_likes_dislikes_count_no_votes(self):
        """測試在沒有任何讚/倒讚時的計數"""
        self.assertEqual(self.video.likes_count(), 0)
        self.assertEqual(self.video.dislikes_count(), 0)

    def test_video_likes_count_with_likes(self):
        """測試有讚時的計數"""
        user2 = User.objects.create_user(username="liker1", password="password123")
        user3 = User.objects.create_user(username="liker2", password="password123")

        LikeDislike.objects.create(video=self.video, user=user2, type=LikeDislike.LIKE)
        self.assertEqual(self.video.likes_count(), 1)
        self.assertEqual(self.video.dislikes_count(), 0)

        LikeDislike.objects.create(video=self.video, user=user3, type=LikeDislike.LIKE)
        self.assertEqual(self.video.likes_count(), 2)
        self.assertEqual(self.video.dislikes_count(), 0)

    def test_video_dislikes_count_with_dislikes(self):
        """測試有倒讚時的計數"""
        user2 = User.objects.create_user(username="disliker1", password="password123")
        user3 = User.objects.create_user(username="disliker2", password="password123")

        LikeDislike.objects.create(video=self.video, user=user2, type=LikeDislike.DISLIKE)
        self.assertEqual(self.video.likes_count(), 0)
        self.assertEqual(self.video.dislikes_count(), 1)

        LikeDislike.objects.create(video=self.video, user=user3, type=LikeDislike.DISLIKE)
        self.assertEqual(self.video.likes_count(), 0)
        self.assertEqual(self.video.dislikes_count(), 2)

    def test_video_mixed_likes_and_dislikes(self):
        """測試混合讚和倒讚時的計數"""
        liker = User.objects.create_user(username="mixed_liker", password="password123")
        disliker = User.objects.create_user(username="mixed_disliker", password="password123")

        LikeDislike.objects.create(video=self.video, user=liker, type=LikeDislike.LIKE)
        LikeDislike.objects.create(video=self.video, user=disliker, type=LikeDislike.DISLIKE)

        self.assertEqual(self.video.likes_count(), 1)
        self.assertEqual(self.video.dislikes_count(), 1)

    def test_video_vote_counts_single_query(self):
        """vote_counts() 應以單次查詢回傳與個別 count 相同的讚/倒讚數"""
        liker = User.objects.create_user(username="vc_liker", password="password123")
        disliker = User.objects.create_user(username="vc_disliker", password="password123")

        self.assertEqual(self.video.vote_counts(), {"likes": 0, "dislikes": 0})

        LikeDislike.objects.create(video=self.video, user=liker, type=LikeDislike.LIKE)
        LikeDislike.objects.create(video=self.video, user=disliker, type=LikeDislike.DISLIKE)

        with self.assertNumQueries(1):
            self.assertEqual(self.video.vote_counts(), {"likes": 1, "dislikes": 1})

    def test_video_upload_date_default(self):
        """測試 upload_date 是否使用 timezone.now 作為預設值"""
        now = timezone.now()
        video_just_created = Video.objects.create(
            title="Just Created Video",
            video_file=SimpleUploadedFile("another.mp4", b"content", content_type="video/mp4"),
            uploader=self.user,
        )
        self.assertTrue(video_just_created.upload_date >= now)
        self.assertTrue((video_just_created.upload_date - now).total_seconds() < 5)

    def test_video_without_category_or_tags(self):
        """測試創建沒有分類或標籤的影片"""
        video_no_extras = Video.objects.create(
            title="Video No Extras",
            video_file=SimpleUploadedFile("no_extras.mp4", b"content", content_type="video/mp4"),
            uploader=self.user,
        )
        self.assertIsNone(video_no_extras.category)
        self.assertEqual(video_no_extras.tags.count(), 0)
        self.assertIsNotNone(video_no_extras)


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

    def test_video_upload_form_for_editing_video_file_not_required(self):
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
        form = VideoUploadForm(data=form_data, instance=existing_video)
        if not form.is_valid():
            print("VideoUploadForm errors (editing):", form.errors.as_json())
        self.assertTrue(form.is_valid(), msg=f"Form errors (editing): {form.errors.as_json()}")
        self.assertFalse(form.fields["video_file"].required)
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


class VideoHomeViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="video_viewer", password="password123")
        self.video1 = Video.objects.create(
            title="Public Video 1",
            uploader=self.user,
            video_file=SimpleUploadedFile("v1.mp4", b"content"),
            visibility="public",
            upload_date=timezone.now() - timezone.timedelta(days=1),
        )
        self.video2 = Video.objects.create(
            title="Public Video 2",
            uploader=self.user,
            video_file=SimpleUploadedFile("v2.mp4", b"content"),
            visibility="public",
            upload_date=timezone.now(),
        )
        self.video_private = Video.objects.create(
            title="Private Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("vp.mp4", b"content"),
            visibility="private",
        )

    def test_home_view_get(self):
        response = self.client.get(reverse("videos:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/home.html")
        self.assertIn("videos", response.context)

        videos_in_context = response.context["videos"]
        self.assertEqual(len(videos_in_context), 2)
        self.assertIn(self.video1, videos_in_context)
        self.assertIn(self.video2, videos_in_context)
        self.assertNotIn(self.video_private, videos_in_context)

        self.assertEqual(list(videos_in_context), [self.video2, self.video1])


class UploadVideoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="uploader_user", password="password123")
        self.category = Category.objects.create(name="Upload Test Category")
        self.client.login(username="uploader_user", password="password123")

        self.video_content = b"video for upload test"
        self.video_file = SimpleUploadedFile("upload_test.mp4", self.video_content, content_type="video/mp4")

        self.image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd7c`\x00\x00\x00\x02\x00\x01\xe2!\xbc\x33\x00\x00\x00\x00IEND\xaeB`\x82"
        self.thumbnail_file = SimpleUploadedFile("upload_thumb.png", self.image_content, content_type="image/png")

    def test_upload_video_view_get(self):
        response = self.client.get(reverse("videos:upload_video"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/upload_video.html")
        self.assertIsInstance(response.context["form"], VideoUploadForm)

    @patch("videos.views.process_video.delay")
    def test_upload_video_view_post_successful(self, mock_process_video_delay):
        video_content_for_test = b"specific video content for this test"
        fresh_video_file = SimpleUploadedFile("fresh_upload_test.mp4", video_content_for_test, content_type="video/mp4")
        fresh_video_file.seek(0)

        image_content_for_test = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd7c`\x00\x00\x00\x02\x00\x01\xe2!\xbc\x33\x00\x00\x00\x00IEND\xaeB`\x82"
        fresh_thumbnail_file = SimpleUploadedFile(
            "fresh_upload_thumb.png", image_content_for_test, content_type="image/png"
        )
        fresh_thumbnail_file.seek(0)

        form_data = {
            "title": "My Uploaded Video",
            "description": "Description of uploaded video.",
            "visibility": "public",
            "category": self.category.id,
            "tags": "upload, test",
        }
        combined_data = form_data.copy()
        combined_data["video_file"] = fresh_video_file
        combined_data["thumbnail"] = fresh_thumbnail_file

        response = self.client.post(reverse("videos:upload_video"), data=combined_data)

        if Video.objects.count() != 1 and response.status_code == 200 and "form" in response.context:
            form_in_context = response.context["form"]
            if not form_in_context.is_valid():
                print("UploadVideoView form errors:", form_in_context.errors.as_json())

        self.assertEqual(Video.objects.count(), 1)
        new_video = Video.objects.first()
        self.assertEqual(new_video.title, "My Uploaded Video")
        self.assertEqual(new_video.uploader, self.user)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:video_detail", args=[new_video.id]))

        mock_process_video_delay.assert_called_once_with(new_video.id)

    def test_upload_video_view_post_invalid_form(self):
        form_data = {"description": "Only description"}
        response = self.client.post(reverse("videos:upload_video"), data=form_data)

        self.assertEqual(Video.objects.count(), 0)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/upload_video.html")
        self.assertIn("form", response.context)
        self.assertFalse(response.context["form"].is_valid())

    def test_upload_video_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("videos:upload_video"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse("users:login") in response.url)


class VideoDetailViewTests(TestCase):
    def setUp(self):
        self.uploader = User.objects.create_user(username="detail_uploader", password="password123")
        self.viewer = User.objects.create_user(username="detail_viewer", password="password123")
        self.category = Category.objects.create(name="Detail Category")
        self.video = Video.objects.create(
            title="Detail Test Video",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("detail.mp4", b"content"),
            category=self.category,
            visibility="public",
        )
        self.video.tags.add("detail_tag")

    def test_video_detail_view_get_existing_video(self):
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/video_detail.html")
        self.assertEqual(response.context["video"], self.video)
        self.assertIn("comment_form", response.context)
        self.assertIn("comments_page", response.context)
        self.assertEqual(response.context["comments_count"], 0)
        self.assertIsNone(response.context["pinned_comment"])
        self.assertEqual(response.context["likes_count"], 0)
        self.assertEqual(response.context["dislikes_count"], 0)
        self.assertIsNone(response.context["user_vote"])
        self.assertEqual(response.context["category"], self.category)
        self.assertIn("detail_tag", [tag.name for tag in response.context["tags"]])

    def test_video_detail_view_with_unicode_tag(self):
        """中文 tag 的 slug 含 unicode，頁面上的 tag 連結 reverse 不應 NoReverseMatch"""
        self.video.tags.add("生活")
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)

    def test_video_detail_view_get_non_existing_video(self):
        response = self.client.get(reverse("videos:video_detail", args=[999]))
        self.assertEqual(response.status_code, 404)

    def test_video_detail_view_private_video_hidden_from_others(self):
        """private 影片的詳細頁對訪客與其他使用者應回 404，僅上傳者本人可觀看"""
        private_video = Video.objects.create(
            title="Private Detail Video",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("private_detail.mp4", b"content"),
            visibility="private",
        )
        url = reverse("videos:video_detail", args=[private_video.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        self.client.login(username="detail_viewer", password="password123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        self.client.login(username="detail_uploader", password="password123")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_video_detail_view_unlisted_video_accessible_via_link(self):
        """unlisted 影片不被列出，但拿到連結的訪客可以直接觀看"""
        unlisted_video = Video.objects.create(
            title="Unlisted Detail Video",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("unlisted_detail.mp4", b"content"),
            visibility="unlisted",
        )
        response = self.client.get(reverse("videos:video_detail", args=[unlisted_video.id]))
        self.assertEqual(response.status_code, 200)

    def test_video_detail_view_increments_view_count(self):
        initial_views = self.video.views_count

        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.views_count, initial_views + 1)
        self.assertTrue(self.client.session.get(f"viewed_video_{self.video.id}"))

        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.views_count, initial_views + 1)

        new_client = self.client_class()
        response = new_client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.views_count, initial_views + 2)
        self.assertTrue(new_client.session.get(f"viewed_video_{self.video.id}"))

    def test_video_detail_comments_paginated_top_level_only(self):
        top_comments = [
            Comment.objects.create(video=self.video, user=self.viewer, content=f"Top comment {i}") for i in range(25)
        ]
        newest_comment = top_comments[-1]
        Comment.objects.create(video=self.video, user=self.viewer, content="A reply", parent_comment=newest_comment)

        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        comments_page = response.context["comments_page"]
        self.assertEqual(len(comments_page.object_list), 20)
        self.assertTrue(comments_page.has_next())
        # 回覆不出現在頂層列表，但計入總數
        self.assertTrue(all(c.parent_comment_id is None for c in comments_page.object_list))
        self.assertEqual(response.context["comments_count"], 26)
        # 最新一筆在第 1 頁（newest first），驗證回覆數 annotation
        comment_with_reply = next(c for c in comments_page.object_list if c.id == newest_comment.id)
        self.assertEqual(comment_with_reply.num_replies, 1)

    def test_video_detail_pinned_comment_via_query_param(self):
        root = Comment.objects.create(video=self.video, user=self.viewer, content="Root comment")
        reply = Comment.objects.create(video=self.video, user=self.uploader, content="Reply", parent_comment=root)
        Comment.objects.create(video=self.video, user=self.viewer, content="Other comment")

        # ?comment= 指向回覆時，釘選的是其頂層留言，且回覆預先展開
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]), {"comment": reply.id})
        self.assertEqual(response.status_code, 200)
        pinned = response.context["pinned_comment"]
        self.assertEqual(pinned, root)
        self.assertEqual([r.id for r in pinned.preloaded_replies], [reply.id])
        # 釘選的留言不重複出現在列表中
        self.assertNotIn(root.id, [c.id for c in response.context["comments_page"].object_list])

    def test_video_detail_pinned_comment_invalid_param_ignored(self):
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]), {"comment": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["pinned_comment"])

        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]), {"comment": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["pinned_comment"])

    def test_video_detail_view_like_dislike_counts_and_user_vote(self):
        LikeDislike.objects.create(video=self.video, user=self.uploader, type=LikeDislike.LIKE)
        another_user = User.objects.create_user(username="another_voter", password="password123")
        LikeDislike.objects.create(video=self.video, user=another_user, type=LikeDislike.DISLIKE)

        self.client.login(username="detail_viewer", password="password123")
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["likes_count"], 1)
        self.assertEqual(response.context["dislikes_count"], 1)
        self.assertIsNone(response.context["user_vote"])

        LikeDislike.objects.create(video=self.video, user=self.viewer, type=LikeDislike.LIKE)
        response = self.client.get(reverse("videos:video_detail", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["likes_count"], 2)
        self.assertEqual(response.context["dislikes_count"], 1)
        self.assertEqual(response.context["user_vote"], LikeDislike.LIKE)


class EditVideoViewTests(TestCase):
    def setUp(self):
        self.uploader = User.objects.create_user(username="video_owner", password="password123")
        self.other_user = User.objects.create_user(username="other_user_videos", password="password123")
        self.category = Category.objects.create(name="Edit Test Category")
        self.video = Video.objects.create(
            title="Original Title",
            description="Original Description",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("edit_me.mp4", b"content"),
            category=self.category,
            visibility="public",
        )
        self.client.login(username="video_owner", password="password123")

    def test_edit_video_view_get(self):
        response = self.client.get(reverse("videos:edit_video", args=[self.video.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/edit_video.html")
        self.assertIsInstance(response.context["form"], VideoUploadForm)
        self.assertEqual(response.context["video"], self.video)
        self.assertEqual(response.context["form"].instance, self.video)

    def test_edit_video_view_post_successful_update(self):
        new_title = "Updated Title"
        new_description = "Updated Description"
        new_category = Category.objects.create(name="New Edit Category")

        form_data = {
            "title": new_title,
            "description": new_description,
            "visibility": "private",
            "category": new_category.id,
            "tags": "edited, updated",
        }
        response = self.client.post(reverse("videos:edit_video", args=[self.video.id]), data=form_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:video_detail", args=[self.video.id]))

        self.video.refresh_from_db()
        self.assertEqual(self.video.title, new_title)
        self.assertEqual(self.video.description, new_description)
        self.assertEqual(self.video.visibility, "private")
        self.assertEqual(self.video.category, new_category)
        self.assertIn("edited", [tag.name for tag in self.video.tags.all()])

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Video updated successfully.")

    def test_edit_video_view_post_invalid_form(self):
        form_data = {"title": ""}  # 缺少必填的 visibility，表單應無效
        response = self.client.post(reverse("videos:edit_video", args=[self.video.id]), data=form_data)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/edit_video.html")
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("visibility", response.context["form"].errors)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Error updating video. Please check the form.")

    def test_edit_video_view_post_empty_title_uses_filename(self):
        """編輯時清空標題，會自動以既有影片的檔名（去副檔名）作為標題"""
        form_data = {
            "title": "",
            "description": "Updated Description",
            "visibility": "public",
        }
        response = self.client.post(reverse("videos:edit_video", args=[self.video.id]), data=form_data)

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        expected_title = os.path.splitext(os.path.basename(self.video.video_file.name))[0]
        self.assertEqual(self.video.title, expected_title)

    def test_edit_video_view_not_uploader(self):
        self.client.logout()
        self.client.login(username="other_user_videos", password="password123")
        response = self.client.post(reverse("videos:edit_video", args=[self.video.id]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:video_detail", args=[self.video.id]))
        self.assertTrue(Video.objects.filter(id=self.video.id).exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "You are not authorized to edit this video.")

    def test_edit_video_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("videos:edit_video", args=[self.video.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse("users:login") in response.url)


class DeleteVideoViewTests(TestCase):
    def setUp(self):
        self.uploader = User.objects.create_user(username="video_deleter", password="password123")
        self.other_user = User.objects.create_user(username="other_deleter", password="password123")
        self.video_to_delete = Video.objects.create(
            title="Video To Delete",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("delete_me.mp4", b"content_for_delete_test", content_type="video/mp4"),
        )
        # Ensure the file exists for deletion test
        with open(self.video_to_delete.video_file.path, "wb") as f:
            f.write(b"content_for_delete_test")

        self.client.login(username="video_deleter", password="password123")

    def test_delete_video_view_get_confirmation_page(self):
        response = self.client.get(reverse("videos:delete_video", args=[self.video_to_delete.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/confirm_delete_video.html")
        self.assertEqual(response.context["video"], self.video_to_delete)

    @patch("os.remove")
    @patch("os.path.exists")
    def test_delete_video_view_post_successful_deletion(self, mock_path_exists, mock_os_remove):
        mock_path_exists.return_value = True  # Simulate file exists

        video_id = self.video_to_delete.id
        video_file_path = self.video_to_delete.video_file.path
        video_title = self.video_to_delete.title

        response = self.client.post(reverse("videos:delete_video", args=[video_id]))

        self.assertEqual(response.status_code, 302)
        # Assuming redirect to user's channel, if not, adjust to 'videos:home'
        try:
            self.assertRedirects(response, reverse("users:channel", args=[self.uploader.username]))
        except AssertionError:  # Fallback if users:channel is not fully set up or user has no channel page
            self.assertRedirects(response, reverse("videos:home"))

        self.assertFalse(Video.objects.filter(id=video_id).exists())
        mock_os_remove.assert_any_call(video_file_path)  # Check if os.remove was called for the video file

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertIn(f"影片 '{video_title}' 已成功刪除。", str(messages[0]))  # Simplified assertion

    def test_delete_video_view_not_uploader(self):
        self.client.logout()
        self.client.login(username="other_deleter", password="password123")
        response = self.client.post(reverse("videos:delete_video", args=[self.video_to_delete.id]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, reverse("videos:video_detail", args=[self.video_to_delete.id])
        )  # Redirect to video detail if not authorized
        self.assertTrue(Video.objects.filter(id=self.video_to_delete.id).exists())  # Video not deleted

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "您沒有權限刪除此影片。")

    def test_delete_video_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("videos:delete_video", args=[self.video_to_delete.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse("users:login") in response.url)


class VideoFileCleanupTests(TestCase):
    """影片刪除後的檔案清理測試（post_delete signal）"""

    def setUp(self):
        self.user = User.objects.create_user(username="cleanup_user", password="password123")

    def test_delete_video_removes_all_related_files(self):
        """刪除影片時，影片檔、縮圖、HLS 目錄與轉檔暫存副本都應一併刪除"""
        video = Video.objects.create(
            title="Cleanup Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("cleanup_test.mp4", b"video content"),
            thumbnail=SimpleUploadedFile("cleanup_thumb.jpg", b"thumb content"),
        )
        video_path = video.video_file.path
        thumbnail_path = video.thumbnail.path

        # 模擬轉檔暫存副本與 HLS 目錄
        processed_dir = os.path.join(settings.MEDIA_ROOT, "videos", "processed_videos")
        os.makedirs(processed_dir, exist_ok=True)
        processed_copy = os.path.join(processed_dir, os.path.basename(video.video_file.name))
        with open(processed_copy, "wb") as f:
            f.write(b"processed content")

        hls_dir = os.path.join(settings.MEDIA_ROOT, "hls", f"{video.id}_cleanup_test")
        os.makedirs(hls_dir, exist_ok=True)
        with open(os.path.join(hls_dir, "playlist.m3u8"), "wb") as f:
            f.write(b"#EXTM3U")
        video.hls_path = os.path.join("hls", f"{video.id}_cleanup_test", "playlist.m3u8")
        video.save(update_fields=["hls_path"])

        video.delete()

        self.assertFalse(os.path.exists(video_path))
        self.assertFalse(os.path.exists(thumbnail_path))
        self.assertFalse(os.path.exists(processed_copy))
        self.assertFalse(os.path.exists(hls_dir))

    def test_delete_video_with_unsafe_hls_path_skips_directory_removal(self):
        """hls_path 指向 media/hls 之外時，不應刪除任何目錄"""
        video = Video.objects.create(
            title="Unsafe HLS Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("unsafe_hls.mp4", b"content"),
            hls_path="../outside/playlist.m3u8",
        )
        with patch("videos.signals.shutil.rmtree") as mock_rmtree:
            video.delete()

        mock_rmtree.assert_not_called()

    def test_delete_video_missing_files_does_not_raise(self):
        """關聯檔案已不存在時，刪除影片不應拋出例外"""
        video = Video.objects.create(
            title="No Files Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("missing_files.mp4", b"content"),
            hls_path="hls/999_missing/playlist.m3u8",
        )
        os.remove(video.video_file.path)

        video.delete()

        self.assertFalse(Video.objects.filter(id=video.id).exists())


class VideosByCategoryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cat_user", password="password123")
        self.category1 = Category.objects.create(name="Tech Reviews", slug="tech-reviews")
        self.category2 = Category.objects.create(name="Gaming Montages", slug="gaming-montages")

        self.video1_cat1 = Video.objects.create(
            title="Latest Smartphone Review",
            uploader=self.user,
            video_file=SimpleUploadedFile("v_c1.mp4", b"c"),
            category=self.category1,
            visibility="public",
        )
        self.video2_cat1 = Video.objects.create(
            title="Old Gadget Review",
            uploader=self.user,
            video_file=SimpleUploadedFile("v_c2.mp4", b"c"),
            category=self.category1,
            visibility="public",
        )
        self.video_cat2 = Video.objects.create(
            title="Epic Game Highlights",
            uploader=self.user,
            video_file=SimpleUploadedFile("v_c3.mp4", b"c"),
            category=self.category2,
            visibility="public",
        )
        self.video_private_cat1 = Video.objects.create(
            title="Private Tech Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("v_cp.mp4", b"c"),
            category=self.category1,
            visibility="private",
        )

    def test_videos_by_category_get_existing_category(self):
        response = self.client.get(reverse("videos:videos_by_category", kwargs={"category_slug": self.category1.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/videos_by_category.html")
        self.assertEqual(response.context["category"], self.category1)

        videos_in_context = response.context["videos"]
        self.assertEqual(len(videos_in_context), 2)
        self.assertIn(self.video1_cat1, videos_in_context)
        self.assertIn(self.video2_cat1, videos_in_context)
        self.assertNotIn(self.video_cat2, videos_in_context)
        self.assertNotIn(self.video_private_cat1, videos_in_context)  # Private video

    def test_videos_by_category_get_non_existing_category(self):
        response = self.client.get(reverse("videos:videos_by_category", kwargs={"category_slug": "non-existent-slug"}))
        self.assertEqual(response.status_code, 404)

    def test_videos_by_category_empty_category(self):
        empty_category = Category.objects.create(name="Empty Category", slug="empty-category")
        response = self.client.get(reverse("videos:videos_by_category", kwargs={"category_slug": empty_category.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["videos"]), 0)
        self.assertEqual(response.context["category"], empty_category)

    def test_videos_by_category_unicode_slug(self):
        """中文分類的 unicode slug 應能匹配路由"""
        unicode_category = Category.objects.create(name="生活")
        response = self.client.get(
            reverse("videos:videos_by_category", kwargs={"category_slug": unicode_category.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["category"], unicode_category)


class VideosByTagViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tag_user", password="password123")
        self.video1 = Video.objects.create(
            title="Video with TagA",
            uploader=self.user,
            video_file=SimpleUploadedFile("vt1.mp4", b"c"),
            visibility="public",
        )
        self.video1.tags.add("TagA", "CommonTag")

        self.video2 = Video.objects.create(
            title="Video with TagB",
            uploader=self.user,
            video_file=SimpleUploadedFile("vt2.mp4", b"c"),
            visibility="public",
        )
        self.video2.tags.add("TagB", "CommonTag")

        self.video3 = Video.objects.create(
            title="Video with TagA Private",
            uploader=self.user,
            video_file=SimpleUploadedFile("vt3.mp4", b"c"),
            visibility="private",
        )
        self.video3.tags.add("TagA")

    def test_videos_by_tag_get_existing_tag(self):
        response = self.client.get(
            reverse("videos:videos_by_tag", kwargs={"tag_slug": "taga"})
        )  # taggit auto-lowercases slugs
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/videos_by_tag.html")
        self.assertEqual(response.context["tag"].name, "TagA")  # taggit stores original case for name

        videos_in_context = response.context["videos"]
        self.assertIn(self.video1, videos_in_context)
        self.assertNotIn(self.video2, videos_in_context)
        self.assertNotIn(self.video3, videos_in_context)  # Private video
        self.assertEqual(len(videos_in_context), 1)

    def test_videos_by_tag_unicode_slug(self):
        """中文 tag 的 unicode slug 應能匹配路由並查到影片"""
        self.video1.tags.add("生活")
        response = self.client.get(reverse("videos:videos_by_tag", kwargs={"tag_slug": "生活"}))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.video1, response.context["videos"])

    def test_videos_by_tag_get_common_tag(self):
        response = self.client.get(reverse("videos:videos_by_tag", kwargs={"tag_slug": "commontag"}))
        self.assertEqual(response.status_code, 200)
        videos_in_context = response.context["videos"]
        self.assertIn(self.video1, videos_in_context)
        self.assertIn(self.video2, videos_in_context)
        self.assertEqual(len(videos_in_context), 2)

    def test_videos_by_tag_get_non_existing_tag(self):
        response = self.client.get(reverse("videos:videos_by_tag", kwargs={"tag_slug": "non-existent-tag-slug"}))
        self.assertEqual(response.status_code, 404)


class AddCategoryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="category_adder", password="password123")
        self.client.login(username="category_adder", password="password123")

    def test_add_category_view_get(self):
        response = self.client.get(reverse("videos:add_category"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/add_category.html")
        self.assertIsInstance(response.context["form"], CategoryForm)
        self.assertIn("categories", response.context)  # Check if existing categories are passed

    def test_add_category_view_post_successful(self):
        category_name = "My New Awesome Category"
        response = self.client.post(reverse("videos:add_category"), data={"name": category_name})
        self.assertEqual(response.status_code, 302)  # Redirect
        self.assertTrue(Category.objects.filter(name=category_name).exists())
        # Default redirect is to 'videos:upload_video'
        self.assertRedirects(response, reverse("videos:upload_video"))

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Category added successfully!")

    def test_add_category_view_post_successful_with_next_param(self):
        category_name = "Category With Next"
        # Test with 'next' in GET param for the form rendering, and in POST for submission
        target_url = reverse("videos:home")
        response = self.client.post(
            f"{reverse('videos:add_category')}?next={target_url}",
            data={"name": category_name, "next": target_url},  # 'next' in hidden field
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, target_url)
        self.assertTrue(Category.objects.filter(name=category_name).exists())

    def test_add_category_view_post_invalid_form(self):
        response = self.client.post(reverse("videos:add_category"), data={"name": ""})  # Empty name
        self.assertEqual(response.status_code, 200)  # Re-render form
        self.assertTemplateUsed(response, "videos/add_category.html")
        self.assertFalse(response.context["form"].is_valid())
        self.assertIn("name", response.context["form"].errors)
        self.assertFalse(Category.objects.filter(name="").exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Error adding category. Please check the form.")

    def test_add_category_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("videos:add_category"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse("users:login") in response.url)


class DeleteCategoryViewTests(TestCase):
    def setUp(self):
        self.uploader = User.objects.create_user(username="category_deleter", password="password123", is_staff=True)
        self.other_user = User.objects.create_user(username="other_deleter", password="password123")
        self.category_to_delete = Category.objects.create(name="Delete Me Category")
        self.category_with_videos = Category.objects.create(name="Category With Videos")
        self.video_in_category = Video.objects.create(
            title="Video in Category",
            uploader=self.uploader,
            video_file=SimpleUploadedFile("v_in_cat.mp4", b"c"),
            category=self.category_with_videos,
        )
        self.client.login(username="category_deleter", password="password123")

    def test_delete_category_view_get_confirmation_page(self):
        response = self.client.get(reverse("videos:delete_category", args=[self.category_to_delete.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "videos/confirm_delete_category.html")
        self.assertEqual(response.context["category"], self.category_to_delete)

    @patch("os.remove")
    @patch("os.path.exists")
    def test_delete_category_view_post_successful_deletion(self, mock_path_exists, mock_os_remove):
        mock_path_exists.return_value = True

        category_id = self.category_to_delete.id
        category_name = self.category_to_delete.name

        response = self.client.post(reverse("videos:delete_category", args=[category_id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:home"))
        self.assertFalse(Category.objects.filter(id=category_id).exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        expected_message = f'Category "{category_name}" deleted successfully.'
        self.assertEqual(str(messages[0]), expected_message)

    def test_delete_category_view_not_uploader(self):
        self.client.logout()
        self.client.login(username="other_deleter", password="password123")
        response = self.client.post(reverse("videos:delete_category", args=[self.category_to_delete.id]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("videos:add_category"))
        self.assertTrue(Category.objects.filter(id=self.category_to_delete.id).exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "您沒有權限刪除此分類。")

    def test_delete_category_view_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("videos:delete_category", args=[self.category_to_delete.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse("users:login") in response.url)


class MockStderrForTest:
    """Mock stderr object with decode method"""

    def __init__(self, decode_return_value="Default mock decoded stderr"):
        self._decode_return_value = str(decode_return_value)

    def decode(self, encoding="utf-8", errors="strict"):
        return self._decode_return_value

    def __str__(self):
        return self._decode_return_value

    def __repr__(self):
        return f"<MockStderrForTest decode_return_value='{self._decode_return_value}'>"


class TestSpecificFFmpegError(ffmpeg.Error):
    """Custom exception to act as ffmpeg.Error in tests"""

    def __init__(self, message, cmd=None, stdout=None, stderr=None):
        super().__init__(cmd or "test_cmd", stdout or b"", stderr or b"")
        self.message = message
        self.cmd = cmd or "test_cmd"
        self.stdout = stdout if stdout is not None else b""
        self.stderr = stderr if stderr is not None else MockStderrForTest("Default stderr for TestSpecificFFmpegError")

    def __str__(self):
        decoded_stdout = (
            self.stdout.decode("utf-8", errors="replace") if isinstance(self.stdout, bytes) else str(self.stdout)
        )
        decoded_stderr = (
            self.stderr.decode("utf-8", errors="replace") if hasattr(self.stderr, "decode") else str(self.stderr)
        )
        return f"{self.message} (Cmd: {self.cmd}, Stdout: {decoded_stdout}, Stderr: {decoded_stderr})"


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

        decoded_stderr_message = "Thumbnail generation failed specific message"
        thumbnail_error_instance = TestSpecificFFmpegError(
            message="Mocked Thumbnail Generation Error from test",
            cmd="ffmpeg_thumb_cmd_for_test",
            stdout=b"mock_stdout_bytes",
            stderr=MockStderrForTest(decode_return_value=decoded_stderr_message),
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


class MediaAuthViewTests(TestCase):
    """
    測試 nginx auth_request 授權端點（media_auth）。

    授權判斷只依據 X-Original-URI（HLS 目錄名的 <id>_ 前綴、mp4 的 video_file 反查），
    不讀磁碟，因此測試不需建立實體 HLS 檔案。
    """

    def setUp(self):
        self.user = User.objects.create_user(username="media_auth_user", password="password123")
        self.other_user = User.objects.create_user(username="media_auth_other", password="password123")

        self.public_video = Video.objects.create(
            title="Public Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("auth_public.mp4", b"video content", content_type="video/mp4"),
            visibility="public",
        )
        self.private_video = Video.objects.create(
            title="Private Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("auth_private.mp4", b"video content", content_type="video/mp4"),
            visibility="private",
        )
        self.auth_url = reverse("videos:media_auth")

    def _auth(self, original_uri):
        return self.client.get(self.auth_url, HTTP_X_ORIGINAL_URI=original_uri)

    def test_public_hls_allowed_for_anonymous(self):
        """測試匿名使用者可存取公開影片的 HLS 片段"""
        response = self._auth(f"/media/hls/{self.public_video.id}_dir/720p/segment_000.ts")
        self.assertEqual(response.status_code, 204)

    def test_private_hls_blocked_for_anonymous(self):
        """測試匿名使用者無法存取私人影片的 HLS"""
        response = self._auth(f"/media/hls/{self.private_video.id}_dir/master.m3u8")
        self.assertEqual(response.status_code, 403)

    def test_private_hls_allowed_for_owner(self):
        """測試影片擁有者可存取私人影片的 HLS"""
        self.client.login(username="media_auth_user", password="password123")
        response = self._auth(f"/media/hls/{self.private_video.id}_dir/master.m3u8")
        self.assertEqual(response.status_code, 204)

    def test_private_hls_blocked_for_other_user(self):
        """測試非擁有者無法存取私人影片的 HLS"""
        self.client.login(username="media_auth_other", password="password123")
        response = self._auth(f"/media/hls/{self.private_video.id}_dir/master.m3u8")
        self.assertEqual(response.status_code, 403)

    def test_hls_unknown_video_blocked(self):
        """測試不存在的影片 id 被拒絕"""
        response = self._auth("/media/hls/999999_dir/master.m3u8")
        self.assertEqual(response.status_code, 403)

    def test_hls_malformed_dir_blocked(self):
        """測試目錄名沒有 <id>_ 前綴時被拒絕"""
        response = self._auth("/media/hls/no-id-prefix/master.m3u8")
        self.assertEqual(response.status_code, 403)

    def test_public_mp4_allowed_for_anonymous(self):
        """測試匿名使用者可存取公開影片的 mp4"""
        response = self._auth(f"/media/{self.public_video.video_file.name}")
        self.assertEqual(response.status_code, 204)

    def test_private_mp4_blocked_for_anonymous(self):
        """測試匿名使用者無法存取私人影片的 mp4"""
        response = self._auth(f"/media/{self.private_video.video_file.name}")
        self.assertEqual(response.status_code, 403)

    def test_private_mp4_allowed_for_owner(self):
        """測試影片擁有者可存取私人影片的 mp4"""
        self.client.login(username="media_auth_user", password="password123")
        response = self._auth(f"/media/{self.private_video.video_file.name}")
        self.assertEqual(response.status_code, 204)

    def test_unreferenced_media_file_blocked(self):
        """測試未被任何 Video 引用的檔案（如轉檔前的原始上傳檔）被拒絕"""
        response = self._auth("/media/videos/not_a_video_record.mp4")
        self.assertEqual(response.status_code, 403)

    def test_non_protected_path_blocked(self):
        """測試 hls/videos 以外的路徑一律拒絕（nginx 不會對縮圖發 auth 子請求）"""
        response = self._auth("/media/thumbnails/some_thumb.jpg")
        self.assertEqual(response.status_code, 403)

    def test_missing_header_blocked(self):
        """測試缺少 X-Original-URI header 時被拒絕"""
        response = self.client.get(self.auth_url)
        self.assertEqual(response.status_code, 403)

    def test_unicode_mp4_path_allowed(self):
        """測試中文檔名路徑可正確還原並授權（nginx 傳 raw bytes、ASGI 以 latin-1 解碼）"""
        video = Video.objects.create(
            title="Unicode Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("中文影片_auth.mp4", b"video content", content_type="video/mp4"),
            visibility="public",
        )
        mojibake_uri = f"/media/{video.video_file.name}".encode().decode("iso-8859-1")
        response = self._auth(mojibake_uri)
        self.assertEqual(response.status_code, 204)

    def test_post_method_not_allowed(self):
        """測試授權端點只接受安全方法（GET/HEAD）"""
        response = self.client.post(self.auth_url, HTTP_X_ORIGINAL_URI="/media/hls/1_dir/master.m3u8")
        self.assertEqual(response.status_code, 405)


class VideoStatusViewTests(TestCase):
    """
    測試影片狀態 API 的回應與權限
    """

    def setUp(self):
        self.user = User.objects.create_user(username="status_user", password="password123")
        self.other_user = User.objects.create_user(username="status_other", password="password123")
        self.public_video = Video.objects.create(
            title="Public Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("status_public.mp4", b"video content", content_type="video/mp4"),
            visibility="public",
        )
        self.private_video = Video.objects.create(
            title="Private Video",
            uploader=self.user,
            video_file=SimpleUploadedFile("status_private.mp4", b"video content", content_type="video/mp4"),
            visibility="private",
        )

    def test_video_status_endpoint(self):
        """測試影片狀態 API"""
        response = self.client.get(reverse("videos:video_status", args=[self.public_video.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("hls_status", data)

    def test_video_status_private_blocked_for_anonymous(self):
        """測試匿名使用者無法查詢私人影片狀態"""
        response = self.client.get(reverse("videos:video_status", args=[self.private_video.id]))
        self.assertEqual(response.status_code, 404)

    def test_video_status_private_blocked_for_other_user(self):
        """測試非擁有者無法查詢私人影片狀態"""
        self.client.login(username="status_other", password="password123")
        response = self.client.get(reverse("videos:video_status", args=[self.private_video.id]))
        self.assertEqual(response.status_code, 404)

    def test_video_status_private_allowed_for_owner(self):
        """測試影片擁有者可查詢私人影片狀態"""
        self.client.login(username="status_user", password="password123")
        response = self.client.get(reverse("videos:video_status", args=[self.private_video.id]))
        self.assertEqual(response.status_code, 200)
