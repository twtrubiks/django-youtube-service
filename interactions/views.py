import pytz
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from videos.models import Video
from .forms import CommentForm
from .models import Comment, LikeDislike, Notification, Subscription

@require_POST
@login_required
def add_comment(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    form = CommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.video = video
        comment.user = request.user

        parent_comment_id = request.POST.get('parent_comment_id')
        parent_comment = None
        if parent_comment_id:
            try:
                parent_comment = Comment.objects.get(id=parent_comment_id, video=video)
                comment.parent_comment = parent_comment
            except Comment.DoesNotExist:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Parent comment not found.'
                    }, status=400)
                pass

        comment.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'comment_id': comment.id,
                'comment_html': render_to_string(
                    'interactions/_comment_detail.html',
                    {'comment': comment, 'request': request, 'video': video}
                ),
                'parent_comment_id': parent_comment.id if parent_comment else None,
                'is_reply': bool(parent_comment)
            })
        else:
            redirect_url = reverse('videos:video_detail', kwargs={'video_id': video.id})
            if comment.parent_comment:
                redirect_url += f'#comment-{comment.parent_comment.id}'
            else:
                redirect_url += f'#comment-{comment.id}'
            return redirect(redirect_url)
    else:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'errors': form.errors
            }, status=400)
        else:
            return redirect('videos:video_detail', video_id=video.id)

@login_required
@require_POST
def vote_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    vote_type = request.POST.get('vote_type')

    if vote_type not in [LikeDislike.LIKE, LikeDislike.DISLIKE]:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid vote type.'
            }, status=400)
        return redirect('videos:video_detail', video_id=video.id)

    like_dislike, created = LikeDislike.objects.get_or_create(
        video=video,
        user=request.user,
        defaults={'type': vote_type}
    )

    action_taken = 'created'
    if not created:
        if like_dislike.type == vote_type:
            like_dislike.delete()
            action_taken = 'deleted'
        else:
            like_dislike.type = vote_type
            like_dislike.save()
            action_taken = 'updated'

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        likes_count = video.likes_count()
        dislikes_count = video.dislikes_count()
        user_vote = LikeDislike.objects.filter(video=video, user=request.user).first()
        current_user_vote_type = user_vote.type if user_vote else None

        return JsonResponse({
            'status': 'success',
            'likes_count': likes_count,
            'dislikes_count': dislikes_count,
            'action_taken': action_taken,
            'new_vote_type': vote_type if action_taken != 'deleted' else None,
            'current_user_vote_type': current_user_vote_type
        })
    return redirect('videos:video_detail', video_id=video.id)

@login_required
@require_POST
def toggle_subscription(request, user_id_to_subscribe):
    subscribing_user = request.user
    user_to_subscribe_to = get_object_or_404(User, id=user_id_to_subscribe)

    if subscribing_user == user_to_subscribe_to:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': 'Cannot subscribe to yourself.'
            }, status=400)
        return redirect('users:channel', username=user_to_subscribe_to.username)

    subscription, created = Subscription.objects.get_or_create(
        subscriber=subscribing_user,
        subscribed_to=user_to_subscribe_to
    )

    action = ''
    subscribed_status = False
    if created:
        action = 'subscribed'
        subscribed_status = True

        if user_to_subscribe_to.is_active:
            channel_layer = get_channel_layer()
            group_name = f"user_{user_to_subscribe_to.id}_notifications"
            message_content = {
                'type': 'send_notification',
                'message': {
                    'type': 'new_subscription',
                    'subscriber_name': subscribing_user.username,
                    'subscriber_id': subscribing_user.id,
                    'text': f"{subscribing_user.username} subscribed to you.",
                    'url': reverse('users:channel', kwargs={'username': subscribing_user.username})
                }
            }
            async_to_sync(channel_layer.group_send)(group_name, message_content)
            print(f"Sent new subscription notification to group: {group_name} for subscriber: {subscribing_user.username}")
    else:
        subscription.delete()
        action = 'unsubscribed'
        subscribed_status = False

    subscriber_count_val = 0
    try:
        if hasattr(user_to_subscribe_to, 'profile') and user_to_subscribe_to.profile is not None:
            subscriber_count_val = user_to_subscribe_to.profile.subscribers_count()
    except Exception:
        pass

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success',
            'action': action,
            'subscribed': subscribed_status,
            'subscribers_count': subscriber_count_val
        })
    else:
        return redirect('users:channel', username=user_to_subscribe_to.username)


@login_required
def get_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user).order_by('-timestamp')

    data = []
    for notification in notifications:
        ts = notification.timestamp
        timestamp_str = ""

        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            try:
                server_local_tz = pytz.timezone(settings.TIME_ZONE)
                aware_local_ts = server_local_tz.localize(ts, is_dst=None)
                aware_utc_ts = aware_local_ts.astimezone(pytz.utc)
                timestamp_str = aware_utc_ts.isoformat()
            except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                aware_utc_ts = ts.replace(tzinfo=pytz.utc)
                timestamp_str = aware_utc_ts.isoformat()
            except Exception:
                aware_utc_ts = ts.replace(tzinfo=pytz.utc)
                timestamp_str = aware_utc_ts.isoformat()
        else:
            aware_utc_ts = ts.astimezone(pytz.utc)
            timestamp_str = aware_utc_ts.isoformat()

        data.append({
            'id': notification.id,
            'message': notification.message,
            'link': notification.link,
            'is_read': notification.is_read,
            'timestamp': timestamp_str,
        })

    return JsonResponse({'notifications': data})

@login_required
@require_POST
def mark_notification_as_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return JsonResponse({
            'status': 'success',
            'message': 'Notification marked as read.'
        })
    return JsonResponse({
        'status': 'noop',
        'message': 'Notification was already read.'
    })


@login_required
@require_POST
def mark_all_notifications_as_read(request):
    updated_count = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True)

    if updated_count > 0:
        return JsonResponse({
            'status': 'success',
            'message': f'{updated_count} notifications marked as read.'
        })
    return JsonResponse({
        'status': 'noop',
        'message': 'No unread notifications to mark.'
    })
