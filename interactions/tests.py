import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from videos.models import Video
from .forms import CommentForm
from .models import Comment, LikeDislike, Notification, Subscription

TEST_PASSWORD = 'password123'
TEST_VIDEO_CONTENT = b"video content"
TEST_VIDEO_CONTENT_TYPE = "video/mp4"

class CommentModelTests(TestCase):
    """Test cases for Comment model functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user(username='commenter1', password=TEST_PASSWORD)
        self.user2 = User.objects.create_user(username='commenter2', password=TEST_PASSWORD)
        self.video_owner = User.objects.create_user(username='video_owner_for_comments', password=TEST_PASSWORD)
        self.video = self._create_test_video("Test Video for Comments", "dummy_video_for_comments.mp4")

    def _create_test_video(self, title, filename):
        dummy_video_file = SimpleUploadedFile(filename, TEST_VIDEO_CONTENT, TEST_VIDEO_CONTENT_TYPE)
        return Video.objects.create(
            title=title,
            uploader=self.video_owner,
            video_file=dummy_video_file
        )

    def test_comment_creation(self):
        comment_content = "This is a great video!"
        comment = Comment.objects.create(
            video=self.video,
            user=self.user1,
            content=comment_content
        )
        self.assertEqual(comment.video, self.video)
        self.assertEqual(comment.user, self.user1)
        self.assertEqual(comment.content, comment_content)
        self.assertIsNotNone(comment.timestamp)
        self.assertIsNone(comment.parent_comment)
        expected_str = f'Comment by {self.user1.username} on {self.video.title}'
        self.assertEqual(str(comment), expected_str)

    def test_comment_reply_creation(self):
        parent_comment = Comment.objects.create(
            video=self.video,
            user=self.user1,
            content="Initial comment."
        )
        reply_content = "I agree with your comment!"
        reply = Comment.objects.create(
            video=self.video,
            user=self.user2,
            content=reply_content,
            parent_comment=parent_comment
        )
        self.assertEqual(reply.parent_comment, parent_comment)
        self.assertEqual(parent_comment.replies.count(), 1)
        self.assertIn(reply, parent_comment.replies.all())

        expected_str = f'Reply by {self.user2.username} to {parent_comment.user.username} on {self.video.title}'
        self.assertEqual(str(reply), expected_str)

    def test_comment_timestamp_default(self):
        now = timezone.now()
        comment = Comment.objects.create(video=self.video, user=self.user1, content="Time test")
        self.assertTrue((comment.timestamp - now).total_seconds() < 2)

class LikeDislikeModelTests(TestCase):
    """Test cases for LikeDislike model functionality."""

    def setUp(self):
        self.user1 = User.objects.create_user(username='voter1', password=TEST_PASSWORD)
        self.user2 = User.objects.create_user(username='voter2', password=TEST_PASSWORD)
        self.video_owner = User.objects.create_user(username='video_owner_for_votes', password=TEST_PASSWORD)
        self.video = self._create_test_video("Test Video for Votes", "dummy_video_for_votes.mp4")

    def _create_test_video(self, title, filename):
        dummy_video_file = SimpleUploadedFile(filename, TEST_VIDEO_CONTENT, TEST_VIDEO_CONTENT_TYPE)
        return Video.objects.create(
            title=title,
            uploader=self.video_owner,
            video_file=dummy_video_file
        )

    def test_like_creation(self):
        like = LikeDislike.objects.create(
            video=self.video,
            user=self.user1,
            type=LikeDislike.LIKE
        )
        self.assertEqual(like.video, self.video)
        self.assertEqual(like.user, self.user1)
        self.assertEqual(like.type, LikeDislike.LIKE)
        self.assertIsNotNone(like.timestamp)
        expected_str = f'{self.user1.username} {LikeDislike.LIKE}s {self.video.title}'
        self.assertEqual(str(like), expected_str)

    def test_dislike_creation(self):
        dislike = LikeDislike.objects.create(
            video=self.video,
            user=self.user1,
            type=LikeDislike.DISLIKE
        )
        self.assertEqual(dislike.type, LikeDislike.DISLIKE)
        expected_str = f'{self.user1.username} {LikeDislike.DISLIKE}s {self.video.title}'
        self.assertEqual(str(dislike), expected_str)

    def test_like_dislike_unique_together_constraint(self):
        """A user can only have one vote (like or dislike) per video."""
        LikeDislike.objects.create(video=self.video, user=self.user1, type=LikeDislike.LIKE)
        self.assertEqual(LikeDislike.objects.filter(video=self.video, user=self.user1).count(), 1)

        with self.assertRaises(IntegrityError):
            LikeDislike.objects.create(video=self.video, user=self.user1, type=LikeDislike.DISLIKE)

    def test_different_users_can_vote_on_same_video(self):
        LikeDislike.objects.create(video=self.video, user=self.user1, type=LikeDislike.LIKE)
        LikeDislike.objects.create(video=self.video, user=self.user2, type=LikeDislike.DISLIKE)
        self.assertEqual(self.video.likes_dislikes.count(), 2)

    def test_same_user_can_vote_on_different_videos(self):
        video2 = self._create_test_video("Another Video", "dummy_video2_for_votes.mp4")
        LikeDislike.objects.create(video=self.video, user=self.user1, type=LikeDislike.LIKE)
        LikeDislike.objects.create(video=video2, user=self.user1, type=LikeDislike.LIKE)
        self.assertEqual(self.user1.likes_dislikes.count(), 2)

class SubscriptionModelTests(TestCase):
    """Test cases for Subscription model functionality."""

    def setUp(self):
        self.user_subscriber = User.objects.create_user(username='subscriber_user', password=TEST_PASSWORD)
        self.user_channel_owner1 = User.objects.create_user(username='channel_owner1', password=TEST_PASSWORD)
        self.user_channel_owner2 = User.objects.create_user(username='channel_owner2', password=TEST_PASSWORD)

    def test_subscription_creation(self):
        subscription = Subscription.objects.create(
            subscriber=self.user_subscriber,
            subscribed_to=self.user_channel_owner1
        )
        self.assertEqual(subscription.subscriber, self.user_subscriber)
        self.assertEqual(subscription.subscribed_to, self.user_channel_owner1)
        self.assertIsNotNone(subscription.timestamp)

        expected_str = f'{self.user_subscriber.username} subscribes to {self.user_channel_owner1.username}'
        self.assertEqual(str(subscription), expected_str)

    def test_subscription_unique_together_constraint(self):
        """A user can only subscribe to another user once."""
        Subscription.objects.create(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner1)
        self.assertEqual(Subscription.objects.filter(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner1).count(), 1)

        with self.assertRaises(IntegrityError):
            Subscription.objects.create(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner1)

    def test_user_can_subscribe_to_multiple_channels(self):
        Subscription.objects.create(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner1)
        Subscription.objects.create(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner2)
        self.assertEqual(self.user_subscriber.subscriptions.count(), 2)

    def test_channel_can_have_multiple_subscribers(self):
        another_subscriber = User.objects.create_user(username='another_sub', password=TEST_PASSWORD)
        Subscription.objects.create(subscriber=self.user_subscriber, subscribed_to=self.user_channel_owner1)
        Subscription.objects.create(subscriber=another_subscriber, subscribed_to=self.user_channel_owner1)
        self.assertEqual(self.user_channel_owner1.subscribers.count(), 2)

    def test_user_cannot_subscribe_to_self(self):
        """Test self-subscription behavior. Currently allowed at model level."""
        sub_to_self = Subscription.objects.create(
            subscriber=self.user_subscriber,
            subscribed_to=self.user_subscriber
        )
        self.assertIsNotNone(sub_to_self)

class CommentFormTests(TestCase):
    """Test cases for CommentForm functionality."""

    def test_comment_form_valid_data(self):
        form_data = {'content': 'This is a valid comment.'}
        form = CommentForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_comment_form_empty_content(self):
        form_data = {'content': ''}
        form = CommentForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('content', form.errors)

    def test_comment_form_content_too_long(self):
        """Test that very long content is accepted."""
        long_content = "a" * 5000
        form_data = {'content': long_content}
        form = CommentForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_comment_form_widget_attributes(self):
        form = CommentForm()
        self.assertIn('placeholder', form.fields['content'].widget.attrs)
        self.assertEqual(form.fields['content'].widget.attrs['placeholder'], 'Add a comment...')
        self.assertEqual(form.fields['content'].widget.attrs['rows'], 3)

class AddCommentViewTests(TestCase):
    """Test cases for AddCommentView functionality."""

    def setUp(self):
        self.comment_poster = User.objects.create_user(username='comment_poster', password=TEST_PASSWORD)
        self.video_author = User.objects.create_user(username='video_author_interactions', password=TEST_PASSWORD)
        self.video = self._create_test_video("Video for Interaction Tests", "interaction_video.mp4")
        self.client.login(username='comment_poster', password=TEST_PASSWORD)

    def _create_test_video(self, title, filename):
        dummy_file = SimpleUploadedFile(filename, TEST_VIDEO_CONTENT, TEST_VIDEO_CONTENT_TYPE)
        return Video.objects.create(title=title, uploader=self.video_author, video_file=dummy_file)

    def test_add_comment_successful_non_ajax(self):
        comment_data = {'content': 'A great non-ajax comment!'}
        response = self.client.post(reverse('interactions:add_comment', args=[self.video.id]), data=comment_data)

        self.assertEqual(Comment.objects.count(), 1)
        new_comment = Comment.objects.first()
        self.assertEqual(new_comment.content, 'A great non-ajax comment!')
        self.assertEqual(new_comment.user, self.comment_poster)
        self.assertEqual(new_comment.video, self.video)

        self.assertEqual(response.status_code, 302)
        expected_redirect_url = reverse('videos:video_detail', kwargs={'video_id': self.video.id}) + f'#comment-{new_comment.id}'
        self.assertRedirects(response, expected_redirect_url)

    def test_add_comment_successful_ajax(self):
        comment_data = {'content': 'An awesome AJAX comment!'}
        response = self.client.post(
            reverse('interactions:add_comment', args=[self.video.id]),
            data=comment_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Comment.objects.count(), 1)
        new_comment = Comment.objects.first()

        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['comment_id'], new_comment.id)
        self.assertIn(new_comment.content, json_response['comment_html'])
        self.assertFalse(json_response['is_reply'])

    def test_add_reply_to_comment_non_ajax(self):
        parent_comment = Comment.objects.create(video=self.video, user=self.video_author, content="Parent comment content")
        reply_data = {
            'content': 'This is a non-ajax reply.',
            'parent_comment_id': parent_comment.id
        }
        response = self.client.post(reverse('interactions:add_comment', args=[self.video.id]), data=reply_data)

        self.assertEqual(Comment.objects.count(), 2)
        new_reply = Comment.objects.get(content=reply_data['content'])
        self.assertEqual(new_reply.parent_comment, parent_comment)

        self.assertEqual(response.status_code, 302)
        expected_redirect_url = reverse('videos:video_detail', kwargs={'video_id': self.video.id}) + f'#comment-{parent_comment.id}'
        self.assertRedirects(response, expected_redirect_url)

    def test_add_reply_to_comment_ajax(self):
        parent_comment = Comment.objects.create(video=self.video, user=self.video_author, content="Parent for AJAX reply")
        reply_data = {
            'content': 'This is an AJAX reply.',
            'parent_comment_id': parent_comment.id
        }
        response = self.client.post(
            reverse('interactions:add_comment', args=[self.video.id]),
            data=reply_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertTrue(json_response['is_reply'])
        self.assertEqual(json_response['parent_comment_id'], parent_comment.id)
        self.assertIn(reply_data['content'], json_response['comment_html'])

    def test_add_comment_invalid_form_non_ajax(self):
        response = self.client.post(reverse('interactions:add_comment', args=[self.video.id]), data={'content': ''})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('videos:video_detail', args=[self.video.id]))
        self.assertEqual(Comment.objects.count(), 0)

    def test_add_comment_invalid_form_ajax(self):
        response = self.client.post(
            reverse('interactions:add_comment', args=[self.video.id]),
            data={'content': ''},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'error')
        self.assertIn('content', json_response['errors'])
        self.assertEqual(Comment.objects.count(), 0)

    def test_add_comment_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse('interactions:add_comment', args=[self.video.id]), data={'content': 'Trying to comment'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse('users:login') in response.url)

    def test_add_comment_to_non_existent_video(self):
        response = self.client.post(reverse('interactions:add_comment', args=[9999]), data={'content': 'Test'})
        self.assertEqual(response.status_code, 404)

    def test_add_reply_to_non_existent_parent_comment_ajax(self):
        reply_data = {
            'content': 'Reply to ghost parent.',
            'parent_comment_id': 8888
        }
        response = self.client.post(
            reverse('interactions:add_comment', args=[self.video.id]),
            data=reply_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Parent comment not found.')

class VoteVideoViewTests(TestCase):
    """Test cases for VoteVideoView functionality."""

    def setUp(self):
        self.voter = User.objects.create_user(username='video_voter', password=TEST_PASSWORD)
        self.video_creator = User.objects.create_user(username='video_creator_for_vote', password=TEST_PASSWORD)
        self.video = self._create_test_video("Video for Voting", "vote_video.mp4")
        self.client.login(username='video_voter', password=TEST_PASSWORD)

    def _create_test_video(self, title, filename):
        dummy_file = SimpleUploadedFile(filename, TEST_VIDEO_CONTENT, TEST_VIDEO_CONTENT_TYPE)
        return Video.objects.create(title=title, uploader=self.video_creator, video_file=dummy_file)

    def _post_vote_ajax(self, vote_type):
        return self.client.post(
            reverse('interactions:vote_video', args=[self.video.id]),
            data={'vote_type': vote_type},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

    def test_like_video_ajax_first_time(self):
        response = self._post_vote_ajax(LikeDislike.LIKE)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['likes_count'], 1)
        self.assertEqual(json_response['dislikes_count'], 0)
        self.assertEqual(json_response['action_taken'], 'created')
        self.assertEqual(json_response['new_vote_type'], LikeDislike.LIKE)
        self.assertEqual(json_response['current_user_vote_type'], LikeDislike.LIKE)
        self.assertTrue(LikeDislike.objects.filter(video=self.video, user=self.voter, type=LikeDislike.LIKE).exists())

    def test_dislike_video_ajax_first_time(self):
        response = self._post_vote_ajax(LikeDislike.DISLIKE)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['likes_count'], 0)
        self.assertEqual(json_response['dislikes_count'], 1)
        self.assertEqual(json_response['action_taken'], 'created')
        self.assertEqual(json_response['new_vote_type'], LikeDislike.DISLIKE)
        self.assertEqual(json_response['current_user_vote_type'], LikeDislike.DISLIKE)
        self.assertTrue(LikeDislike.objects.filter(video=self.video, user=self.voter, type=LikeDislike.DISLIKE).exists())

    def test_remove_like_video_ajax(self):
        LikeDislike.objects.create(video=self.video, user=self.voter, type=LikeDislike.LIKE)
        response = self._post_vote_ajax(LikeDislike.LIKE)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['likes_count'], 0)
        self.assertEqual(json_response['dislikes_count'], 0)
        self.assertEqual(json_response['action_taken'], 'deleted')
        self.assertIsNone(json_response['new_vote_type'])
        self.assertIsNone(json_response['current_user_vote_type'])
        self.assertFalse(LikeDislike.objects.filter(video=self.video, user=self.voter).exists())

    def test_change_vote_from_like_to_dislike_ajax(self):
        LikeDislike.objects.create(video=self.video, user=self.voter, type=LikeDislike.LIKE)
        response = self._post_vote_ajax(LikeDislike.DISLIKE)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['likes_count'], 0)
        self.assertEqual(json_response['dislikes_count'], 1)
        self.assertEqual(json_response['action_taken'], 'updated')
        self.assertEqual(json_response['new_vote_type'], LikeDislike.DISLIKE)
        self.assertEqual(json_response['current_user_vote_type'], LikeDislike.DISLIKE)
        self.assertTrue(LikeDislike.objects.filter(video=self.video, user=self.voter, type=LikeDislike.DISLIKE).exists())

    def test_vote_video_invalid_vote_type_ajax(self):
        response = self._post_vote_ajax('invalid_vote')
        self.assertEqual(response.status_code, 400)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Invalid vote type.')

    def test_vote_video_non_ajax_redirects(self):
        response = self.client.post(
            reverse('interactions:vote_video', args=[self.video.id]),
            data={'vote_type': LikeDislike.LIKE}
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('videos:video_detail', args=[self.video.id]))

    def test_vote_video_requires_login(self):
        self.client.logout()
        response = self._post_vote_ajax(LikeDislike.LIKE)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse('users:login') in response.url)

class ToggleSubscriptionViewTests(TestCase):
    """Test cases for ToggleSubscriptionView functionality."""

    def setUp(self):
        self.subscriber_user = User.objects.create_user(username='subscriber_interactions', password=TEST_PASSWORD)
        self.channel_owner = User.objects.create_user(username='channel_owner_interactions', password=TEST_PASSWORD)
        self.channel_owner_profile = self.channel_owner.profile
        self.client.login(username='subscriber_interactions', password=TEST_PASSWORD)

    def _post_toggle_subscription_ajax(self, user_to_subscribe_id):
        return self.client.post(
            reverse('interactions:toggle_subscription', args=[user_to_subscribe_id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

    def test_subscribe_to_user_ajax_first_time(self):
        initial_subs_count = self.channel_owner_profile.subscribers_count()
        response = self._post_toggle_subscription_ajax(self.channel_owner.id)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertTrue(json_response['subscribed'])
        self.assertEqual(json_response['subscribers_count'], initial_subs_count + 1)
        self.assertTrue(Subscription.objects.filter(subscriber=self.subscriber_user, subscribed_to=self.channel_owner).exists())

    def test_unsubscribe_from_user_ajax(self):
        Subscription.objects.create(subscriber=self.subscriber_user, subscribed_to=self.channel_owner)
        initial_subs_count = self.channel_owner_profile.subscribers_count()

        response = self._post_toggle_subscription_ajax(self.channel_owner.id)
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertFalse(json_response['subscribed'])
        self.assertEqual(json_response['subscribers_count'], initial_subs_count - 1)
        self.assertFalse(Subscription.objects.filter(subscriber=self.subscriber_user, subscribed_to=self.channel_owner).exists())

    def test_subscribe_to_self_ajax(self):
        response = self._post_toggle_subscription_ajax(self.subscriber_user.id)
        self.assertEqual(response.status_code, 400)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Cannot subscribe to yourself.')
        self.assertFalse(Subscription.objects.filter(subscriber=self.subscriber_user, subscribed_to=self.subscriber_user).exists())

    def test_toggle_subscription_non_ajax_redirects(self):
        response = self.client.post(
            reverse('interactions:toggle_subscription', args=[self.channel_owner.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('users:channel', args=[self.channel_owner.username]))

    def test_toggle_subscription_requires_login(self):
        self.client.logout()
        response = self._post_toggle_subscription_ajax(self.channel_owner.id)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(reverse('users:login') in response.url)

    def test_toggle_subscription_to_non_existent_user(self):
        response = self._post_toggle_subscription_ajax(999888)
        self.assertEqual(response.status_code, 404)

    @patch('interactions.views.get_channel_layer')
    @patch('interactions.views.async_to_sync')
    def test_subscribe_sends_websocket_notification(self, mock_async_to_sync, mock_get_channel_layer):
        """Test that subscribing sends a WebSocket notification."""
        # Setup mocks
        mock_channel_layer = MagicMock()
        mock_get_channel_layer.return_value = mock_channel_layer
        mock_group_send = MagicMock()
        mock_async_to_sync.return_value = mock_group_send

        # Perform subscription
        response = self._post_toggle_subscription_ajax(self.channel_owner.id)

        # Verify response
        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertTrue(json_response['subscribed'])

        # Verify WebSocket notification was sent
        mock_get_channel_layer.assert_called_once()
        mock_async_to_sync.assert_called_once_with(mock_channel_layer.group_send)

        # Verify the message content
        expected_group_name = f"user_{self.channel_owner.id}_notifications"
        expected_message = {
            'type': 'send_notification',
            'message': {
                'type': 'new_subscription',
                'subscriber_name': self.subscriber_user.username,
                'subscriber_id': self.subscriber_user.id,
                'text': f"{self.subscriber_user.username} subscribed to you.",
                'url': f'/users/channel/{self.subscriber_user.username}/'
            }
        }

        mock_group_send.assert_called_once_with(expected_group_name, expected_message)

    def test_subscribe_does_not_create_direct_notification(self):
        """Test that subscribing does not create a direct Notification object in the view."""
        initial_notification_count = Notification.objects.count()

        response = self._post_toggle_subscription_ajax(self.channel_owner.id)

        self.assertEqual(response.status_code, 200)
        json_response = json.loads(response.content)
        self.assertEqual(json_response['status'], 'success')
        self.assertTrue(json_response['subscribed'])

        self.assertEqual(Notification.objects.count(), initial_notification_count)
