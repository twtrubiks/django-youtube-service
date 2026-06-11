"""模型測試：Category、Video、檔案清理 signal 與存取權限規則。"""

import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone
from django.utils.text import slugify

from interactions.models import LikeDislike
from videos.models import Category, Video

from .base import BaseVideoTestCase


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


class VideoAccessPolicyTests(TestCase):
    """Video.is_accessible_by 與 VideoQuerySet.listable 的權限規則單元測試。"""

    def setUp(self):
        self.owner = User.objects.create_user(username="policy_owner", password="password123")
        self.other_user = User.objects.create_user(username="policy_other", password="password123")
        self.videos = {
            visibility: Video.objects.create(
                title=f"{visibility} video",
                uploader=self.owner,
                video_file=SimpleUploadedFile(f"policy_{visibility}.mp4", b"video content", content_type="video/mp4"),
                visibility=visibility,
            )
            for visibility in ["public", "private", "unlisted"]
        }

    def test_public_and_unlisted_accessible_by_anyone(self):
        from django.contrib.auth.models import AnonymousUser

        for visibility in ["public", "unlisted"]:
            video = self.videos[visibility]
            self.assertTrue(video.is_accessible_by(AnonymousUser()))
            self.assertTrue(video.is_accessible_by(self.other_user))
            self.assertTrue(video.is_accessible_by(self.owner))

    def test_private_accessible_only_by_owner(self):
        from django.contrib.auth.models import AnonymousUser

        video = self.videos["private"]
        self.assertFalse(video.is_accessible_by(AnonymousUser()))
        self.assertFalse(video.is_accessible_by(self.other_user))
        self.assertTrue(video.is_accessible_by(self.owner))

    def test_listable_only_includes_public(self):
        """unlisted 可存取但不可被列出，listable 僅含 public。"""
        listable = Video.objects.listable()
        self.assertIn(self.videos["public"], listable)
        self.assertNotIn(self.videos["unlisted"], listable)
        self.assertNotIn(self.videos["private"], listable)
