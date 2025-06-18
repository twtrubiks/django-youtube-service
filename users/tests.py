# Django imports
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

# Local imports
from .forms import UserRegistrationForm, UserLoginForm, UserProfileForm, UserEditForm
from .models import UserProfile
from interactions.models import Subscription
from videos.models import Video

# Test constants
TEST_PASSWORD = 'password123'
TEST_IMAGE_CONTENT = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

class UserProfileModelTests(TestCase):

    def setUp(self):
        self.user1 = User.objects.create_user(username='testuser1', password=TEST_PASSWORD)
        self.profile1 = self.user1.profile

        self.user2 = User.objects.create_user(username='testuser2', password=TEST_PASSWORD)
        self.profile2 = self.user2.profile

        self.user3 = User.objects.create_user(username='testuser3', password=TEST_PASSWORD)

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
        self.assertEqual(self.profile1.subscribers_count(), 1)

        Subscription.objects.create(subscriber=self.user3, subscribed_to=self.user1)
        self.assertEqual(self.profile1.subscribers_count(), 2)

        Subscription.objects.create(subscriber=self.user1, subscribed_to=self.user2)
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

        user_reloaded = User.objects.get(username='testuser1')
        user_reloaded.save()

        self.profile1.refresh_from_db()
        self.assertEqual(self.profile1.channel_description, "A new channel description")


class UserRegistrationFormTests(TestCase):

    def test_registration_form_valid_data(self):
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'User',
            'password': 'password123',
            'password2': 'password123',
        }
        form = UserRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_registration_form_password_mismatch(self):
        form_data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'password123',
            'password2': 'differentpassword',
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)
        self.assertEqual(form.errors['password2'][0], 'Passwords don\'t match.')

    def test_registration_form_missing_required_fields(self):
        form_data = {'password': 'password123', 'password2': 'password123'}
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
        self.assertIn('email', form.errors)

    def test_registration_form_missing_email_only(self):
        """測試僅缺少 email 欄位的情況"""
        form_data = {
            'username': 'testuser_no_email',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'password123',
            'password2': 'password123',
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertEqual(form.errors['email'][0], 'This field is required.')

    def test_registration_form_invalid_email(self):
        form_data = {
            'username': 'newuser',
            'email': 'not-an-email',
            'password': 'password123',
            'password2': 'password123',
        }
        form = UserRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

class UserLoginFormTests(TestCase):

    def test_login_form_valid_data(self):
        form_data = {'username': 'testuser', 'password': 'password123'}
        form = UserLoginForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_login_form_missing_fields(self):
        form_data = {}
        form = UserLoginForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
        self.assertIn('password', form.errors)

class UserProfileFormTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testprofileuser', password='password123')
        self.profile = self.user.profile

    def test_profile_form_valid_data(self):
        profile_pic = SimpleUploadedFile("test_profile.gif", TEST_IMAGE_CONTENT, content_type="image/gif")
        banner_pic = SimpleUploadedFile("test_banner.gif", TEST_IMAGE_CONTENT, content_type="image/gif")

        form_data = {'channel_description': 'This is a test channel.'}
        file_data = {'profile_picture': profile_pic, 'banner_image': banner_pic}

        form = UserProfileForm(data=form_data, files=file_data, instance=self.profile)
        if not form.is_valid():
            print("UserProfileForm errors:", form.errors.as_json())
        self.assertTrue(form.is_valid())

    def test_profile_form_channel_description_only(self):
        form_data = {'channel_description': 'Another test description.'}
        form = UserProfileForm(data=form_data, instance=self.profile)
        self.assertTrue(form.is_valid())

class UserEditFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='edituser',
            email='edituser@example.com',
            first_name='Edit',
            last_name='User',
            password='password123'
        )

    def test_user_edit_form_valid_data(self):
        form_data = {
            'first_name': 'Edited',
            'last_name': 'Name',
            'email': 'edited@example.com'
        }
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertTrue(form.is_valid())

    def test_user_edit_form_invalid_email(self):
        form_data = {
            'first_name': 'Edited',
            'last_name': 'Name',
            'email': 'not-an-email'
        }
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_user_edit_form_partial_update(self):
        form_data = {'first_name': 'JustFirstName'}
        form = UserEditForm(data=form_data, instance=self.user)
        self.assertTrue(form.is_valid())
        updated_user = form.save(commit=False)
        self.assertEqual(updated_user.first_name, 'JustFirstName')
        self.assertEqual(updated_user.last_name, self.user.last_name)
        self.assertEqual(updated_user.email, self.user.email)


class UserRegisterViewTests(TestCase):

    def test_register_view_get(self):
        """
        測試註冊頁面的 GET 請求。
        """
        response = self.client.get(reverse('users:register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/register.html')
        self.assertIsInstance(response.context['form'], UserRegistrationForm)

    def test_register_view_post_successful_registration(self):
        """
        測試成功註冊的 POST 請求。
        """
        user_data = {
            'username': 'newtestuser',
            'email': 'newtestuser@example.com',
            'first_name': 'New',
            'last_name': 'Test',
            'password': 'complexpassword123',
            'password2': 'complexpassword123',
        }
        response = self.client.post(reverse('users:register'), data=user_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:login'))
        self.assertTrue(User.objects.filter(username='newtestuser').exists())

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Registration successful. Please log in.')

    def test_register_view_post_password_mismatch(self):
        """
        測試密碼不匹配時的 POST 請求。
        """
        user_data = {
            'username': 'anotheruser',
            'email': 'another@example.com',
            'password': 'password123',
            'password2': 'wrongpassword',
        }
        response = self.client.post(reverse('users:register'), data=user_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/register.html')
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('password2', form.errors)
        self.assertFalse(User.objects.filter(username='anotheruser').exists())

    def test_register_view_post_existing_username(self):
        """
        測試使用已存在的用戶名進行註冊。
        """
        User.objects.create_user(username='existinguser', password='password123')
        user_data = {
            'username': 'existinguser',
            'email': 'newemail@example.com',
            'password': 'password123',
            'password2': 'password123',
        }
        response = self.client.post(reverse('users:register'), data=user_data)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)

class UserLoginViewTests(TestCase):

    def setUp(self):
        self.test_user = User.objects.create_user(username='testloginuser', password='testpassword123')

    def test_login_view_get(self):
        """
        測試登入頁面的 GET 請求。
        """
        response = self.client.get(reverse('users:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        self.assertIsInstance(response.context['form'], UserLoginForm)

    def test_login_view_post_successful_login(self):
        """
        測試成功登入的 POST 請求。
        """
        login_data = {'username': 'testloginuser', 'password': 'testpassword123'}
        response = self.client.post(reverse('users:login'), data=login_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:channel', kwargs={'username': self.test_user.username}))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Authenticated successfully')

    def test_login_view_post_invalid_credentials(self):
        """
        測試使用無效憑證登入的 POST 請求。
        """
        login_data = {'username': 'testloginuser', 'password': 'wrongpassword'}
        response = self.client.post(reverse('users:login'), data=login_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/login.html')
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Invalid login')

    def test_login_view_post_inactive_user(self):
        """
        測試嘗試登入已停用帳戶。
        """
        self.test_user.is_active = False
        self.test_user.save()
        login_data = {'username': 'testloginuser', 'password': 'testpassword123'}
        response = self.client.post(reverse('users:login'), data=login_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Disabled account')

class UserLogoutViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testlogoutuser', password='password123')

    def test_logout_view_when_logged_in(self):
        """
        測試已登入使用者登出。
        """
        self.client.login(username='testlogoutuser', password='password123')
        self.assertTrue(self.client.session['_auth_user_id'])

        response = self.client.get(reverse('users:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'You have been successfully logged out.')

    def test_logout_view_when_not_logged_in(self):
        """
        測試未登入使用者訪問登出頁面。
        """
        response = self.client.get(reverse('users:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:logout')}")

class EditProfileViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testedituser', password='password123', first_name='OriginalFirst', last_name='OriginalLast', email='original@example.com')
        self.profile = self.user.profile
        self.profile.channel_description = "Original Description"
        self.profile.save()
        self.client.login(username='testedituser', password='password123')

    def test_edit_profile_view_get(self):
        """
        測試編輯個人資料頁面的 GET 請求。
        """
        response = self.client.get(reverse('users:edit_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/edit_profile.html')
        self.assertIsInstance(response.context['user_form'], UserEditForm)
        self.assertIsInstance(response.context['profile_form'], UserProfileForm)
        self.assertEqual(response.context['user_form'].instance, self.user)
        self.assertEqual(response.context['profile_form'].instance, self.profile)

    def test_edit_profile_view_post_successful_update(self):
        """
        測試成功更新個人資料的 POST 請求。
        """
        new_data = {
            'first_name': 'UpdatedFirst',
            'last_name': 'UpdatedLast',
            'email': 'updated@example.com',
            'channel_description': 'Updated Description',
        }
        response = self.client.post(reverse('users:edit_profile'), data=new_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:channel', kwargs={'username': self.user.username}))

        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertEqual(self.user.first_name, 'UpdatedFirst')
        self.assertEqual(self.user.last_name, 'UpdatedLast')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(self.profile.channel_description, 'Updated Description')

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Profile updated successfully')


    def test_edit_profile_view_post_invalid_data(self):
        """
        測試使用無效數據更新個人資料的 POST 請求。
        """
        invalid_data = {
            'email': 'not-an-email',
            'channel_description': 'Trying to update with invalid email',
        }
        response = self.client.post(reverse('users:edit_profile'), data=invalid_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/edit_profile.html')

        user_form = response.context['user_form']
        self.assertFalse(user_form.is_valid())
        self.assertIn('email', user_form.errors)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'Error updating your profile')


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

        response = self.client.post(reverse('users:edit_profile'), data={'delete_banner': '1'})

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.banner_image.name, '')
        self.assertFalse(self.profile.banner_image)

        valid_data_for_other_forms = {
            'first_name': self.user.first_name,
            'last_name': self.user.last_name,
            'email': self.user.email,
            'channel_description': self.profile.channel_description,
            'delete_banner': '1'
        }
        response = self.client.post(reverse('users:edit_profile'), data=valid_data_for_other_forms)
        self.assertEqual(response.status_code, 302)

        messages = list(response.wsgi_request._messages)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.banner_image.name, '')
        self.assertFalse(self.profile.banner_image)

        found_banner_message = False
        found_profile_update_message = False
        for msg in messages:
            if str(msg) == 'Banner image removed successfully.':
                found_banner_message = True
            if str(msg) == 'Profile updated successfully':
                found_profile_update_message = True

        self.assertTrue(found_banner_message, "Banner removal message not found.")
        self.assertTrue(found_profile_update_message, "Profile update message not found.")


    def test_edit_profile_view_requires_login(self):
        """
        測試編輯個人資料頁面需要登入。
        """
        self.client.logout() # 確保未登入
        response = self.client.get(reverse('users:edit_profile'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{reverse('users:login')}?next={reverse('users:edit_profile')}")

class UserChannelViewTests(TestCase):

    def setUp(self):
        self.channel_owner = User.objects.create_user(username='channelowner', password='password123')
        self.channel_profile = self.channel_owner.profile
        self.channel_profile.channel_description = "Owner's Channel"
        self.channel_profile.save()

        self.viewer = User.objects.create_user(username='viewer', password='password123')

    def test_user_channel_view_get_existing_user(self):
        """
        測試查看存在使用者的頻道頁面。
        """
        response = self.client.get(reverse('users:channel', kwargs={'username': 'channelowner'}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/channel.html')
        self.assertEqual(response.context['profile_owner'], self.channel_owner)
        self.assertEqual(response.context['profile'], self.channel_profile)
        self.assertFalse(response.context['is_subscribed'])

    def test_user_channel_view_get_non_existing_user(self):
        """
        測試查看不存在使用者的頻道頁面。
        """
        response = self.client.get(reverse('users:channel', kwargs={'username': 'nonexistinguser'}))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:login'))
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), 'User channel not found.')

    def test_user_channel_view_subscription_status_not_subscribed(self):
        """
        測試已登入使用者查看他人頻道時，未訂閱的情況。
        """
        self.client.login(username='viewer', password='password123')
        response = self.client.get(reverse('users:channel', kwargs={'username': 'channelowner'}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_subscribed'])

    def test_user_channel_view_subscription_status_subscribed(self):
        """
        測試已登入使用者查看他人頻道時，已訂閱的情況。
        """
        Subscription.objects.create(subscriber=self.viewer, subscribed_to=self.channel_owner)
        self.client.login(username='viewer', password='password123')
        response = self.client.get(reverse('users:channel', kwargs={'username': 'channelowner'}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_subscribed'])

    def test_user_channel_view_own_channel(self):
        """
        測試使用者查看自己的頻道。
        """
        self.client.login(username='channelowner', password='password123')
        response = self.client.get(reverse('users:channel', kwargs={'username': 'channelowner'}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_subscribed'])
        self.assertEqual(response.context['profile_owner'], self.channel_owner)

    def test_user_channel_view_displays_videos(self):
        """
        測試頻道頁面是否顯示使用者的影片。
        """
        video_file_1 = SimpleUploadedFile("test_video_1.mp4", b"video content 1", content_type="video/mp4")
        video_file_2 = SimpleUploadedFile("test_video_2.mp4", b"video content 2", content_type="video/mp4")

        Video.objects.create(
            uploader=self.channel_owner,
            title="Test Video 1",
            video_file=video_file_1,
            visibility='public'
        )
        Video.objects.create(
            uploader=self.channel_owner,
            title="Test Video 2",
            video_file=video_file_2,
            visibility='public'
        )

        response = self.client.get(reverse('users:channel', kwargs={'username': 'channelowner'}))
        self.assertEqual(response.status_code, 200)

        self.assertIn('user_videos', response.context)
        user_videos = response.context['user_videos']

        self.assertEqual(len(user_videos), 2)

        self.assertContains(response, "Test Video 1")
        self.assertContains(response, "Test Video 2")

        video_titles = [video.title for video in user_videos]
        self.assertIn("Test Video 1", video_titles)
        self.assertIn("Test Video 2", video_titles)
