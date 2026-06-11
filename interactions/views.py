import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, JsonResponse
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

COMMENTS_PER_PAGE = 20
REPLIES_PER_PAGE = 10


@ratelimit(key="user", rate="30/m", method="POST", block=True)
@require_POST
@login_required
def add_comment(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    # 與 video_detail 一致回 404，避免確認 private 影片的存在性
    if not video.is_accessible_by(request.user):
        raise Http404("影片不存在或無權限訪問")
    form = CommentForm(request.POST)

    if form.is_valid():
        comment = form.save(commit=False)
        comment.video = video
        comment.user = request.user

        parent_comment_id = request.POST.get("parent_comment_id")
        parent_comment = None
        if parent_comment_id:
            try:
                parent_comment = Comment.objects.select_related("parent_comment").get(id=parent_comment_id, video=video)
            except Comment.DoesNotExist:
                parent_comment = None
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"status": "error", "message": "Parent comment not found."}, status=400)
            else:
                if parent_comment.parent_comment_id:
                    # 留言串只有兩層：回覆「回覆」時掛回頂層留言（同 YouTube），
                    # 通知仍須送給實際被回覆的人，先記在 instance 上供 signal 使用
                    comment._reply_to_user = parent_comment.user
                    parent_comment = parent_comment.parent_comment
                comment.parent_comment = parent_comment

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


def get_comments(request, video_id):
    """回傳影片頂層留言的分頁 HTML（前端 Load more 用）。"""
    video = get_object_or_404(Video, id=video_id)
    if not video.is_accessible_by(request.user):
        raise Http404("影片不存在或無權限訪問")
    comments = (
        Comment.objects.filter(video=video, parent_comment__isnull=True)
        .select_related("user")
        .annotate(num_replies=Count("replies"))
        .order_by("-timestamp")
    )

    # 釘選留言（通知深連結）已在頁面最上方渲染，載入更多時跳過避免重複
    exclude_id = request.GET.get("exclude")
    if exclude_id and exclude_id.isdigit():
        comments = comments.exclude(pk=exclude_id)

    paginator = Paginator(comments, COMMENTS_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))
    html = render_to_string(
        "interactions/_comment_list.html", {"comments": page.object_list, "video": video, "request": request}
    )
    return JsonResponse(
        {
            "status": "success",
            "html": html,
            "has_next": page.has_next(),
            "next_page": page.next_page_number() if page.has_next() else None,
        }
    )


def get_replies(request, comment_id):
    """回傳頂層留言底下回覆的分頁 HTML（前端展開回覆用），由舊到新排序。"""
    comment = get_object_or_404(Comment.objects.select_related("video"), id=comment_id, parent_comment__isnull=True)
    if not comment.video.is_accessible_by(request.user):
        raise Http404("留言不存在或無權限訪問")
    replies = comment.replies.select_related("user").order_by("timestamp")
    paginator = Paginator(replies, REPLIES_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))
    html = render_to_string(
        "interactions/_comment_list.html",
        {"comments": page.object_list, "video": comment.video, "request": request},
    )
    return JsonResponse(
        {
            "status": "success",
            "html": html,
            "has_next": page.has_next(),
            "next_page": page.next_page_number() if page.has_next() else None,
        }
    )


@ratelimit(key="user", rate="60/m", method="POST", block=True)
@login_required
@require_POST
def vote_video(request, video_id):
    video = get_object_or_404(Video, id=video_id)
    if not video.is_accessible_by(request.user):
        raise Http404("影片不存在或無權限訪問")
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
        vote_counts = video.vote_counts()
        user_vote = LikeDislike.objects.filter(video=video, user=request.user).first()
        current_user_vote_type = user_vote.type if user_vote else None

        return JsonResponse(
            {
                "status": "success",
                "likes_count": vote_counts["likes"],
                "dislikes_count": vote_counts["dislikes"],
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
