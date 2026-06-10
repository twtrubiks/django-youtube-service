import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from videos.models import Video

from .forms import CommentForm
from .models import Comment, LikeDislike, Notification, Subscription
from .services import notify

logger = logging.getLogger(__name__)


@ratelimit(key="user", rate="30/m", method="POST", block=True)
@require_POST
@login_required
def add_comment(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    form = CommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.video = video
        comment.user = request.user

        parent_comment_id = request.POST.get("parent_comment_id")
        parent_comment = None
        if parent_comment_id:
            try:
                parent_comment = Comment.objects.get(id=parent_comment_id, video=video)
                comment.parent_comment = parent_comment
            except Comment.DoesNotExist:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"status": "error", "message": "Parent comment not found."}, status=400)
                pass

        comment.save()

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "status": "success",
                    "comment_id": comment.id,
                    "comment_html": render_to_string(
                        "interactions/_comment_detail.html", {"comment": comment, "request": request, "video": video}
                    ),
                    "parent_comment_id": parent_comment.id if parent_comment else None,
                    "is_reply": bool(parent_comment),
                }
            )
        else:
            redirect_url = reverse("videos:video_detail", kwargs={"video_id": video.id})
            if comment.parent_comment:
                redirect_url += f"#comment-{comment.parent_comment.id}"
            else:
                redirect_url += f"#comment-{comment.id}"
            return redirect(redirect_url)
    else:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "errors": form.errors}, status=400)
        else:
            return redirect("videos:video_detail", video_id=video.id)


@ratelimit(key="user", rate="60/m", method="POST", block=True)
@login_required
@require_POST
def vote_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    vote_type = request.POST.get("vote_type")

    if vote_type not in [LikeDislike.LIKE, LikeDislike.DISLIKE]:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": "Invalid vote type."}, status=400)
        return redirect("videos:video_detail", video_id=video.id)

    like_dislike, created = LikeDislike.objects.get_or_create(
        video=video, user=request.user, defaults={"type": vote_type}
    )

    action_taken = "created"
    if not created:
        if like_dislike.type == vote_type:
            like_dislike.delete()
            action_taken = "deleted"
        else:
            like_dislike.type = vote_type
            like_dislike.save()
            action_taken = "updated"

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        likes_count = video.likes_count()
        dislikes_count = video.dislikes_count()
        user_vote = LikeDislike.objects.filter(video=video, user=request.user).first()
        current_user_vote_type = user_vote.type if user_vote else None

        return JsonResponse(
            {
                "status": "success",
                "likes_count": likes_count,
                "dislikes_count": dislikes_count,
                "action_taken": action_taken,
                "new_vote_type": vote_type if action_taken != "deleted" else None,
                "current_user_vote_type": current_user_vote_type,
            }
        )
    return redirect("videos:video_detail", video_id=video.id)


@ratelimit(key="user", rate="30/m", method="POST", block=True)
@login_required
@require_POST
def toggle_subscription(request, user_id_to_subscribe):
    subscribing_user = request.user
    user_to_subscribe_to = get_object_or_404(User, id=user_id_to_subscribe)

    if subscribing_user == user_to_subscribe_to:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "message": "Cannot subscribe to yourself."}, status=400)
        return redirect("users:channel", username=user_to_subscribe_to.username)

    subscription, created = Subscription.objects.get_or_create(
        subscriber=subscribing_user, subscribed_to=user_to_subscribe_to
    )

    action = ""
    subscribed_status = False
    if created:
        action = "subscribed"
        subscribed_status = True

        notify(
            user_to_subscribe_to,
            {
                "type": "new_subscription",
                "subscriber_name": subscribing_user.username,
                "subscriber_id": subscribing_user.id,
                "text": f"{subscribing_user.username} subscribed to you.",
                "url": reverse("users:channel", kwargs={"username": subscribing_user.username}),
            },
            sender=subscribing_user,
        )
    else:
        subscription.delete()
        action = "unsubscribed"
        subscribed_status = False

    subscriber_count_val = 0
    try:
        if hasattr(user_to_subscribe_to, "profile") and user_to_subscribe_to.profile is not None:
            user_to_subscribe_to.profile.refresh_subscriber_count()
            subscriber_count_val = user_to_subscribe_to.profile.subscribers_count()
    except Exception:
        logger.warning("Failed to get subscribers_count for user %s", user_id_to_subscribe, exc_info=True)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": "success",
                "action": action,
                "subscribed": subscribed_status,
                "subscribers_count": subscriber_count_val,
            }
        )
    else:
        return redirect("users:channel", username=user_to_subscribe_to.username)


@login_required
def get_notifications(request):
    notifications = Notification.objects.filter(recipient=request.user).order_by("-timestamp")[:50]

    data = [
        {
            "id": notification.id,
            "message": notification.message,
            "link": notification.link,
            "is_read": notification.is_read,
            # USE_TZ=True 下 timestamp 必為 aware UTC，isoformat 直接得到 +00:00 結尾
            "timestamp": notification.timestamp.isoformat(),
        }
        for notification in notifications
    ]

    return JsonResponse({"status": "success", "data": {"notifications": data}})


@login_required
@require_POST
def mark_notification_as_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return JsonResponse({"status": "success", "message": "Notification marked as read."})
    return JsonResponse({"status": "noop", "message": "Notification was already read."})


@login_required
@require_POST
def mark_all_notifications_as_read(request):
    updated_count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)

    if updated_count > 0:
        return JsonResponse({"status": "success", "message": f"{updated_count} notifications marked as read."})
    return JsonResponse({"status": "noop", "message": "No unread notifications to mark."})
