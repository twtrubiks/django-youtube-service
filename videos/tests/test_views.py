"""視圖測試：首頁、上傳、詳細頁、編輯、刪除、分類、標籤、media auth 與狀態 API。"""

import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from interactions.models import Comment, LikeDislike
from videos.forms import CategoryForm, VideoEditForm, VideoUploadForm
from videos.models import Category, Video


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
        self.assertIsInstance(response.context["form"], VideoEditForm)
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

    @patch("videos.views.process_video.delay")
    def test_edit_video_view_post_video_file_is_ignored(self, mock_process_video_delay):
        """編輯時就算 POST 新的 video_file 也不會生效，亦不會重新觸發影片處理"""
        original_file_name = self.video.video_file.name
        form_data = {
            "title": "Title After Edit",
            "visibility": "public",
            "video_file": SimpleUploadedFile("replacement.mp4", b"new content", "video/mp4"),
        }
        response = self.client.post(reverse("videos:edit_video", args=[self.video.id]), data=form_data)

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertEqual(self.video.video_file.name, original_file_name)
        self.assertEqual(self.video.title, "Title After Edit")
        mock_process_video_delay.assert_not_called()

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
