# Standard library imports
from unittest.mock import patch

# Django imports
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from interactions.models import Subscription
from videos.models import Video

# Local imports
from .forms import UserEditForm, UserLoginForm, UserProfileForm, UserRegistrationForm

# Test constants
TEST_PASSWORD = "password123"
TEST_IMAGE_CONTENT = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="testuser1", password=TEST_PASSWORD)
        self.profile1 = self.user1.profile

        self.user2 = User.objects.create_user(username="testuser2", password=TEST_PASSWORD)
        self.profile2 = self.user2.profile

        self.user3 = User.objects.create_user(username="testuser3", password=TEST_PASSWORD)

    def test_user_profile_is_created_on_user_creation(self):
        """
        測試 UserProfile 是否在 User 創建時自動創建。
        """
        self.assertIsNotNone(self.profile1)
        self.assertEqual(self.profile1.user, self.user1)

    def test_user_profile_str_method(self):
        """
        測試 UserProfile 的 __str__ 方法。
        """
        self.assertEqual(str(self.profile1), self.user1.username)

    def test_subscribers_count_no_subscribers(self):
        """
        測試 subscribers_count 方法在沒有訂閱者時的情況。
        """
        self.assertEqual(self.profile1.subscribers_count(), 0)

    def test_subscribers_count_with_subscribers(self):
        """
        測試 subscribers_count 方法在有訂閱者時的情況。
        """
        Subscription.objects.create(subscriber=self.user2, subscribed_to=self.user1)
        self.profile1.refresh_subscriber_count()
        self.assertEqual(self.profile1.subscribers_count(), 1)

        Subscription.objects.create(subscriber=self.user3, subscribed_to=self.user1)
        self.profile1.refresh_subscriber_count()
        self.assertEqual(self.profile1.subscribers_count(), 2)

        Subscription.objects.create(subscriber=self.user1, subscribed_to=self.user2)
        self.profile1.refresh_subscriber_count()
        self.profile2.refresh_subscriber_count()
        self.assertEqual(self.profile1.subscribers_count(), 2)
        self.assertEqual(self.profile2.subscribers_count(), 1)

    def test_channel_description_default_blank(self):
        """
        測試 channel_description 欄位的預設值。
        """
        self.assertEqual(self.profile1.channel_description, "")

    def test_profile_picture_and_banner_image_defaults(self):
        """
        測試圖片欄位的預設值 (應為 None 或空)。
        """
        self.assertIsNone(self.profile1.profile_picture.name)
        self.assertEqual(self.profile1.profile_picture, None)
        self.assertIsNone(self.profile1.banner_image.name)
        self.assertEqual(self.profile1.banner_image, None)

    def test_user_profile_updates_with_user(self):
        """
        測試 UserProfile 是否與 User 實例保持同步。
        """
        self.profile1.channel_description = "A new channel description"
        self.profile1.save()

        user_reloaded = User.objects.get(username="testuser1")
        user_reloaded.save()

        self.profile1.refresh_from_db()
        self.assertEqual(self.profile1.channel_description, "A new channel description")


class UserRegistrationFormTests(TestCase):
    def test_registration_form_valid_data(self):
        form_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "SecureP@ss2026!",
            "password2": "SecureP@ss2026!",
        }
        form = UserRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_registration_form_password_mismatch(self):
        form_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "password123",
            "password2": "differentpassword",
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)
        self.assertEqual(form.errors["password2"][0], "Passwords don't match.")

    def test_registration_form_missing_required_fields(self):
        form_data = {"password": "password123", "password2": "password123"}
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
        self.assertIn("email", form.errors)

    def test_registration_form_missing_email_only(self):
        """測試僅缺少 email 欄位的情況"""
        form_data = {
            "username": "testuser_no_email",
            "first_name": "Test",
            "last_name": "User",
            "password": "password123",
            "password2": "password123",
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertEqual(form.errors["email"][0], "This field is required.")

    def test_registration_form_invalid_email(self):
        form_data = {
            "username": "newuser",
            "email": "not-an-email",
            "password": "password123",
            "password2": "password123",
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_registration_form_duplicate_email(self):
        """已註冊的 email 不可重複註冊（不分大小寫）。"""
        User.objects.create_user(username="existinguser", email="taken@example.com", password=TEST_PASSWORD)
        form_data = {
            "username": "newuser",
            "email": "TAKEN@example.com",
            "password": "SecureP@ss2026!",
            "password2": "SecureP@ss2026!",
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertEqual(form.errors["email"][0], "A user with that email already exists.")


class EmailUniqueIndexTests(TestCase):
    def test_db_index_blocks_duplicate_email_case_insensitive(self):
        """LOWER(email) 部分唯一索引：表單層 clean_email 競態的最後防線。"""
        User.objects.create_user(username="user1", email="dup@example.com", password=TEST_PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="user2", email="DUP@example.com", password=TEST_PASSWORD)

    def test_db_index_allows_multiple_empty_emails(self):
        """空 email（createsuperuser 等路徑）不受唯一索引限制。"""
        User.objects.create_user(username="noemail1", password=TEST_PASSWORD)
        User.objects.create_user(username="noemail2", password=TEST_PASSWORD)
        self.assertEqual(User.objects.filter(email="").count(), 2)


class UserLoginFormTests(TestCase):
    def test_login_form_valid_data(self):
        form_data = {"username": "testuser", "password": "password123"}
        form = UserLoginForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_login_form_missing_fields(self):
        form_data = {}
        form = UserLoginForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
        self.assertIn("password", form.errors)


class UserProfileFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testprofileuser", password="password123")
        self.profile = self.user.profile

    def test_profile_form_valid_data(self):
        profile_pic = SimpleUploadedFile("test_profile.gif", TEST_IMAGE_CONTENT, content_type="image/gif")
        banner_pic = SimpleUploadedFile("test_banner.gif", TEST_IMAGE_CONTENT, content_type="image/gif")

        form_data = {"channel_description": "This is a test channel."}
        file_data = {"profile_picture": profile_pic, "banner_image": banner_pic}

        form = UserProfileForm(data=form_data, files=file_data, instance=self.profile)
        if not form.is_valid():
            print("UserProfileForm errors:", form.errors.as_json())
        self.assertTrue(form.is_valid())

    def test_profile_form_channel_description_only(self):
        form_data = {"channel_description": "Another test description."}
        form = UserProfileForm(data=form_data, instance=self.profile)
        self.assertTrue(form.is_valid())


class UserEditFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="edituser",
            email="edituser@example.com",
            first_name="Edit",
            last_name="User",
            password="password123",
        )

    def test_user_edit_form_valid_data(self):
        form_data = {"first_name": "Edited", "last_name": "Name", "email": "edited@example.com"}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_user_edit_form_invalid_email(self):
        form_data = {"first_name": "Edited", "last_name": "Name", "email": "not-an-email"}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_user_edit_form_duplicate_email(self):
        """不可把 email 改成別人已使用的（不分大小寫）。"""
        User.objects.create_user(
            username="otheruser",
            email="taken@example.com",
            password="password123",
        )
        form_data = {"first_name": "Edited", "last_name": "Name", "email": "Taken@Example.com"}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_user_edit_form_keep_own_email(self):
        """保留自己原本的 email 不應被自己擋下。"""
        form_data = {"first_name": "Edited", "last_name": "Name", "email": "edituser@example.com"}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_user_edit_form_partial_update(self):
        form_data = {"first_name": "JustFirstName"}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertTrue(form.is_valid())
        updated_user = form.save(commit=False)
        self.assertEqual(updated_user.first_name, "JustFirstName")
        self.assertEqual(updated_user.last_name, self.user.last_name)
        self.assertEqual(updated_user.email, self.user.email)


class UserRegisterViewTests(TestCase):
    def test_register_view_get(self):
        """
        測試註冊頁面的 GET 請求。
        """
        response = self.client.get(reverse("users:register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/register.html")
        self.assertIsInstance(response.context["form"], UserRegistrationForm)

    def test_register_view_post_successful_registration(self):
        """
        測試成功註冊的 POST 請求。
        """
        user_data = {
            "username": "newtestuser",
            "email": "newtestuser@example.com",
            "first_name": "New",
            "last_name": "Test",
            "password": "complexpassword123",
            "password2": "complexpassword123",
        }
        response = self.client.post(reverse("users:register"), data=user_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("users:login"))
        self.assertTrue(User.objects.filter(username="newtestuser").exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Registration successful. Please log in.")

    def test_register_view_post_password_mismatch(self):
        """
        測試密碼不匹配時的 POST 請求。
        """
        user_data = {
            "username": "anotheruser",
            "email": "another@example.com",
            "password": "password123",
            "password2": "wrongpassword",
        }
        response = self.client.post(reverse("users:register"), data=user_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/register.html")
        form = response.context["form"]
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)
        self.assertFalse(User.objects.filter(username="anotheruser").exists())

    def test_register_view_post_existing_username(self):
        """
        測試使用已存在的用戶名進行註冊。
        """
        User.objects.create_user(username="existinguser", password="password123")
        user_data = {
            "username": "existinguser",
            "email": "newemail@example.com",
            "password": "password123",
            "password2": "password123",
        }
        response = self.client.post(reverse("users:register"), data=user_data)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_register_view_duplicate_email_race_returns_form_error(self):
        """
        模擬 clean_email 通過後、寫入前才出現重複 email 的併發競態：
        DB 唯一索引擋下，view 回填表單錯誤而非 500。
        """
        User.objects.create_user(username="firstuser", email="race@example.com", password=TEST_PASSWORD)
        user_data = {
            "username": "seconduser",
            "email": "race@example.com",
            "password": "complexpassword123",
            "password2": "complexpassword123",
        }
        # 讓 clean_email 放行，重現「檢查通過但 DB 已有人」的競態時序
        with patch.object(UserRegistrationForm, "clean_email", lambda self: self.cleaned_data["email"]):
            response = self.client.post(reverse("users:register"), data=user_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="seconduser").exists())


class UserLoginViewTests(TestCase):
    def setUp(self):
        self.test_user = User.objects.create_user(username="testloginuser", password="testpassword123")

    def test_login_view_get(self):
        """
        測試登入頁面的 GET 請求。
        """
        response = self.client.get(reverse("users:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/login.html")
        self.assertIsInstance(response.context["form"], UserLoginForm)

    def test_login_view_post_successful_login(self):
        """
        測試成功登入的 POST 請求。
        """
        login_data = {"username": "testloginuser", "password": "testpassword123"}
        response = self.client.post(reverse("users:login"), data=login_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("users:channel", kwargs={"username": self.test_user.username}))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Authenticated successfully")

    def test_login_view_post_invalid_credentials(self):
        """
        測試使用無效憑證登入的 POST 請求。
        """
        login_data = {"username": "testloginuser", "password": "wrongpassword"}
        response = self.client.post(reverse("users:login"), data=login_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/login.html")
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Invalid login")

    def test_login_view_post_inactive_user(self):
        """
        測試嘗試登入已停用帳戶：訊息與帳密錯誤相同，不洩漏帳號狀態（防帳號枚舉）。
        """
        self.test_user.is_active = False
        self.test_user.save()
        login_data = {"username": "testloginuser", "password": "testpassword123"}
        response = self.client.post(reverse("users:login"), data=login_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Invalid login")

    def test_login_sets_csrf_cookie_for_later_ajax_posts(self):
        """
        登入回應本身會重設 csrftoken cookie（login() 內的 rotate_token），
        之後即使只逛無表單頁面，通知「標記已讀」等 AJAX POST 也拿得到 token。
        """
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("users:login"))  # 登入頁渲染 {% csrf_token %}，取得初始 cookie
        login_data = {
            "username": "testloginuser",
            "password": "testpassword123",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }
        response = client.post(reverse("users:login"), data=login_data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("csrftoken", response.cookies)

        client.get(reverse("videos:home"))  # 無表單頁面，不會再送 csrf cookie
        response = client.post(
            reverse("interactions:mark_all_notifications_as_read"),
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)


class UserLogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testlogoutuser", password="password123")

    def test_logout_view_when_logged_in(self):
        """
        測試已登入使用者登出。
        """
        self.client.login(username="testlogoutuser", password="password123")
        self.assertTrue(self.client.session["_auth_user_id"])

        response = self.client.get(reverse("users:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("users:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "You have been successfully logged out.")

    def test_logout_view_when_not_logged_in(self):
        """
        測試未登入使用者訪問登出頁面。
        """
        response = self.client.get(reverse("users:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:logout')}")


class EditProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testedituser",
            password="password123",
            first_name="OriginalFirst",
            last_name="OriginalLast",
            email="original@example.com",
        )
        self.profile = self.user.profile
        self.profile.channel_description = "Original Description"
        self.profile.save()
        self.client.login(username="testedituser", password="password123")

    def test_edit_profile_view_get(self):
        """
        測試編輯個人資料頁面的 GET 請求。
        """
        response = self.client.get(reverse("users:edit_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/edit_profile.html")
        self.assertIsInstance(response.context["user_form"], UserEditForm)
        self.assertIsInstance(response.context["profile_form"], UserProfileForm)
        self.assertEqual(response.context["user_form"].instance, self.user)
        self.assertEqual(response.context["profile_form"].instance, self.profile)

    def test_edit_profile_view_post_successful_update(self):
        """
        測試成功更新個人資料的 POST 請求。
        """
        new_data = {
            "first_name": "UpdatedFirst",
            "last_name": "UpdatedLast",
            "email": "updated@example.com",
            "channel_description": "Updated Description",
        }
        response = self.client.post(reverse("users:edit_profile"), data=new_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("users:channel", kwargs={"username": self.user.username}))

        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertEqual(self.user.first_name, "UpdatedFirst")
        self.assertEqual(self.user.last_name, "UpdatedLast")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertEqual(self.profile.channel_description, "Updated Description")

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Profile updated successfully")

    def test_edit_profile_view_post_invalid_data(self):
        """
        測試使用無效數據更新個人資料的 POST 請求。
        """
        invalid_data = {
            "email": "not-an-email",
            "channel_description": "Trying to update with invalid email",
        }
        response = self.client.post(reverse("users:edit_profile"), data=invalid_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/edit_profile.html")

        user_form = response.context["user_form"]
        self.assertFalse(user_form.is_valid())
        self.assertIn("email", user_form.errors)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "Error updating your profile")

    def test_edit_profile_duplicate_email_race_returns_form_error(self):
        """
        模擬 clean_email 通過後、寫入前 email 才被別人用掉的併發競態：
        DB 唯一索引擋下，view 回填表單錯誤而非 500。
        """
        User.objects.create_user(username="otheruser", email="race@example.com", password="password123")
        new_data = {
            "first_name": "UpdatedFirst",
            "last_name": "UpdatedLast",
            "email": "race@example.com",
            "channel_description": "Updated Description",
        }
        # 讓 clean_email 放行，重現「檢查通過但 DB 已有人」的競態時序
        with patch.object(UserEditForm, "clean_email", lambda self: self.cleaned_data["email"]):
            response = self.client.post(reverse("users:edit_profile"), data=new_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["user_form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "original@example.com")

    def test_edit_profile_view_delete_banner_image(self):
        """
        測試刪除橫幅圖片的功能。
        """
        image_content = b"GIF89a\x01\x00\x01\x00\x00\x00\x00\x00"
        banner_pic = SimpleUploadedFile("banner.gif", image_content, content_type="image/gif")
        self.profile.banner_image = banner_pic
        self.profile.save()
        self.assertIsNotNone(self.profile.banner_image.name)
        self.assertTrue(self.profile.banner_image)

        response = self.client.post(reverse("users:edit_profile"), data={"delete_banner": "1"})

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.banner_image.name, "")
        self.assertFalse(self.profile.banner_image)

        valid_data_for_other_forms = {
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "email": self.user.email,
            "channel_description": self.profile.channel_description,
            "delete_banner": "1",
        }
        response = self.client.post(reverse("users:edit_profile"), data=valid_data_for_other_forms)
        self.assertEqual(response.status_code, 302)

        messages = list(response.wsgi_request._messages)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.banner_image.name, "")
        self.assertFalse(self.profile.banner_image)

        found_banner_message = False
        found_profile_update_message = False
        for msg in messages:
            if str(msg) == "Banner image removed successfully.":
                found_banner_message = True
            if str(msg) == "Profile updated successfully":
                found_profile_update_message = True

        self.assertTrue(found_banner_message, "Banner removal message not found.")
        self.assertTrue(found_profile_update_message, "Profile update message not found.")

    def test_edit_profile_view_requires_login(self):
        """
        測試編輯個人資料頁面需要登入。
        """
        self.client.logout()  # 確保未登入
        response = self.client.get(reverse("users:edit_profile"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:edit_profile')}")


class UserChannelViewTests(TestCase):
    def setUp(self):
        self.channel_owner = User.objects.create_user(username="channelowner", password="password123")
        self.channel_profile = self.channel_owner.profile
        self.channel_profile.channel_description = "Owner's Channel"
        self.channel_profile.save()

        self.viewer = User.objects.create_user(username="viewer", password="password123")

    def test_user_channel_view_get_existing_user(self):
        """
        測試查看存在使用者的頻道頁面。
        """
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/channel.html")
        self.assertEqual(response.context["profile_owner"], self.channel_owner)
        self.assertEqual(response.context["profile"], self.channel_profile)
        self.assertFalse(response.context["is_subscribed"])

    def test_user_channel_view_get_non_existing_user(self):
        """
        測試查看不存在使用者的頻道頁面。
        """
        response = self.client.get(reverse("users:channel", kwargs={"username": "nonexistinguser"}))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("users:login"))
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "User channel not found.")

    def test_user_channel_view_subscription_status_not_subscribed(self):
        """
        測試已登入使用者查看他人頻道時，未訂閱的情況。
        """
        self.client.login(username="viewer", password="password123")
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_subscribed"])

    def test_user_channel_view_subscription_status_subscribed(self):
        """
        測試已登入使用者查看他人頻道時，已訂閱的情況。
        """
        Subscription.objects.create(subscriber=self.viewer, subscribed_to=self.channel_owner)
        self.client.login(username="viewer", password="password123")
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_subscribed"])

    def test_user_channel_view_visitor_only_sees_public_videos(self):
        """
        測試訪客（未登入與其他使用者）查看頻道時，只列出 public 影片。
        """
        public_video = Video.objects.create(
            title="Public Video",
            uploader=self.channel_owner,
            video_file=SimpleUploadedFile("public.mp4", b"content"),
            visibility="public",
        )
        Video.objects.create(
            title="Private Video",
            uploader=self.channel_owner,
            video_file=SimpleUploadedFile("private.mp4", b"content"),
            visibility="private",
        )
        Video.objects.create(
            title="Unlisted Video",
            uploader=self.channel_owner,
            video_file=SimpleUploadedFile("unlisted.mp4", b"content"),
            visibility="unlisted",
        )

        # 未登入訪客
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["user_videos"]), [public_video])

        # 已登入的其他使用者
        self.client.login(username="viewer", password="password123")
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["user_videos"]), [public_video])

    def test_user_channel_view_owner_sees_all_videos(self):
        """
        測試本人查看自己頻道時，列出所有 visibility 的影片。
        """
        for visibility in ["public", "private", "unlisted"]:
            Video.objects.create(
                title=f"{visibility} Video",
                uploader=self.channel_owner,
                video_file=SimpleUploadedFile(f"{visibility}.mp4", b"content"),
                visibility=visibility,
            )

        self.client.login(username="channelowner", password="password123")
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["user_videos"]), 3)

    def test_user_channel_view_own_channel(self):
        """
        測試使用者查看自己的頻道。
        """
        self.client.login(username="channelowner", password="password123")
        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_subscribed"])
        self.assertEqual(response.context["profile_owner"], self.channel_owner)

    def test_user_channel_view_pagination(self):
        """
        測試頻道頁分頁：與其他列表頁一致，每頁 12 部影片。
        """
        for i in range(13):
            Video.objects.create(
                uploader=self.channel_owner,
                title=f"Paginated Video {i}",
                video_file=SimpleUploadedFile(f"paginated_{i}.mp4", b"content"),
                visibility="public",
            )

        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["user_videos"]), 12)
        self.assertEqual(response.context["page_obj"].paginator.count, 13)

        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}), {"page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["user_videos"]), 1)

    def test_user_channel_view_displays_videos(self):
        """
        測試頻道頁面是否顯示使用者的影片。
        """
        video_file_1 = SimpleUploadedFile("test_video_1.mp4", b"video content 1", content_type="video/mp4")
        video_file_2 = SimpleUploadedFile("test_video_2.mp4", b"video content 2", content_type="video/mp4")

        Video.objects.create(
            uploader=self.channel_owner, title="Test Video 1", video_file=video_file_1, visibility="public"
        )
        Video.objects.create(
            uploader=self.channel_owner, title="Test Video 2", video_file=video_file_2, visibility="public"
        )

        response = self.client.get(reverse("users:channel", kwargs={"username": "channelowner"}))
        self.assertEqual(response.status_code, 200)

        self.assertIn("user_videos", response.context)
        user_videos = response.context["user_videos"]

        self.assertEqual(len(user_videos), 2)

        self.assertContains(response, "Test Video 1")
        self.assertContains(response, "Test Video 2")

        video_titles = [video.title for video in user_videos]
        self.assertIn("Test Video 1", video_titles)
        self.assertIn("Test Video 2", video_titles)
