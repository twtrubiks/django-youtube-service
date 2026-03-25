# 標準庫 imports
import logging
import os

# Django imports
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

# 第三方庫 imports
from taggit.models import Tag

from interactions.forms import CommentForm
from interactions.models import Comment, LikeDislike

# 本地應用 imports
from .forms import CategoryForm, VideoUploadForm
from .models import Category, Video
from .tasks import process_video

logger = logging.getLogger(__name__)


@login_required
def upload_video(request):
    """
    處理影片上傳功能。

    Args:
        request: HTTP 請求物件

    Returns:
        HttpResponse: 渲染的模板回應或重定向
    """
    if request.method == "POST":
        form = VideoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            video = form.save(commit=False)
            video.uploader = request.user
            video.save()
            form.save_m2m()  # Save ManyToMany data
            # 觸發 Celery 任務來處理影片
            process_video.delay(video.id)
            # Redirect to the video detail page or a success page
            return redirect(reverse("videos:video_detail", args=[video.id]))
    else:
        form = VideoUploadForm()
    return render(request, "videos/upload_video.html", {"form": form})


def video_detail(request, video_id):
    """
    顯示影片詳細資訊頁面。

    Args:
        request: HTTP 請求物件
        video_id: 影片 ID

    Returns:
        HttpResponse: 渲染的影片詳細頁面
    """
    video = get_object_or_404(Video, pk=video_id)
    comments = Comment.objects.filter(video=video).select_related("user", "parent_comment__user").order_by("-timestamp")
    comment_form = CommentForm()

    viewed_video_session_key = f"viewed_video_{video.id}"
    if not request.session.get(viewed_video_session_key, False):
        Video.objects.filter(pk=video.pk).update(views_count=F("views_count") + 1)
        video.refresh_from_db(fields=["views_count"])
        request.session[viewed_video_session_key] = True

    # Get like/dislike counts
    likes_count = LikeDislike.objects.filter(video=video, type=LikeDislike.LIKE).count()
    dislikes_count = LikeDislike.objects.filter(video=video, type=LikeDislike.DISLIKE).count()

    # Get current user's vote
    user_vote = None
    if request.user.is_authenticated:
        try:
            user_vote_obj = LikeDislike.objects.get(video=video, user=request.user)
            user_vote = user_vote_obj.type
        except LikeDislike.DoesNotExist:
            pass  # User hasn't voted

    context = {
        "video": video,
        "comments": comments,
        "comment_form": comment_form,
        "likes_count": likes_count,
        "dislikes_count": dislikes_count,
        "user_vote": user_vote,  # 'like', 'dislike', or None
        "category": video.category,
        "tags": video.tags.all(),
    }
    return render(request, "videos/video_detail.html", context)


def home(request):
    """
    顯示首頁，列出所有公開影片。

    Args:
        request: HTTP 請求物件

    Returns:
        HttpResponse: 渲染的首頁
    """
    videos = Video.objects.filter(visibility="public").select_related("uploader").order_by("-upload_date")
    paginator = Paginator(videos, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "videos/home.html", {"videos": page_obj, "page_obj": page_obj})


def search_videos(request):
    """
    搜尋影片功能。

    Args:
        request: HTTP 請求物件

    Returns:
        HttpResponse: 渲染的搜尋結果頁面
    """
    query = request.GET.get("query")
    videos = Video.objects.none()
    if query:
        videos = (
            Video.objects.filter(Q(title__icontains=query) | Q(description__icontains=query), visibility="public")
            .select_related("uploader")
            .order_by("-upload_date")
        )

    paginator = Paginator(videos, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "videos/search_results.html", {"videos": page_obj, "page_obj": page_obj, "query": query})


@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, pk=video_id)

    if video.uploader != request.user:
        messages.error(request, "You are not authorized to edit this video.")
        return redirect(reverse("videos:video_detail", args=[video.id]))

    if request.method == "POST":
        form = VideoUploadForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            form.save()
            messages.success(request, "Video updated successfully.")
            return redirect(reverse("videos:video_detail", args=[video.id]))
        else:
            messages.error(request, "Error updating video. Please check the form.")
    else:
        form = VideoUploadForm(instance=video)

    return render(request, "videos/edit_video.html", {"form": form, "video": video})


def videos_by_category(request, category_slug):
    category = get_object_or_404(Category, slug=category_slug)
    videos = (
        Video.objects.filter(category=category, visibility="public").select_related("uploader").order_by("-upload_date")
    )
    paginator = Paginator(videos, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "category": category,
        "videos": page_obj,
        "page_obj": page_obj,
    }
    return render(request, "videos/videos_by_category.html", context)


def videos_by_tag(request, tag_slug):
    tag = get_object_or_404(Tag, slug=tag_slug)
    videos = (
        Video.objects.filter(tags__slug=tag_slug, visibility="public")
        .select_related("uploader")
        .order_by("-upload_date")
    )
    paginator = Paginator(videos, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "tag": tag,
        "videos": page_obj,
        "page_obj": page_obj,
    }
    return render(request, "videos/videos_by_tag.html", context)


@login_required
def add_category(request):
    allowed_hosts = {request.get_host()}
    raw_next = (request.POST.get("next") or request.GET.get("next") or "").strip()
    safe_next = raw_next if url_has_allowed_host_and_scheme(raw_next, allowed_hosts=allowed_hosts) else ""

    if request.method == "POST":
        form = CategoryForm(request.POST)

        if form.is_valid():
            form.save()
            messages.success(request, "Category added successfully!")
            return redirect(safe_next or reverse("videos:upload_video"))
        else:
            messages.error(request, "Error adding category. Please check the form.")
            context = {"form": form, "next_target_url_for_template": safe_next}
            return render(request, "videos/add_category.html", context)
    else:
        form = CategoryForm()
        categories = Category.objects.all().order_by("name")
        context = {
            "form": form,
            "next_target_url_for_template": safe_next,
            "categories": categories,
        }
        return render(request, "videos/add_category.html", context)


@login_required
def delete_category(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    # 權限檢查：只有具備 staff 權限的使用者才能刪除分類
    if not request.user.is_staff:
        messages.error(request, "您沒有權限刪除此分類。")
        return redirect(reverse("videos:add_category"))  # 重定向到添加分類頁面

    if request.method == "POST":
        category_name = category.name
        # 檢查是否有影片關聯到此分類
        if category.videos.exists():
            messages.error(request, f'無法刪除分類 "{category_name}"，因為它有關聯的影片。請先重新分配或刪除這些影片。')
            # 重定向回來源頁面或分類列表頁
            # 為了簡單起見，我們先重定向到 add_category，理想情況下應該有更好的處理
            return redirect(reverse("videos:add_category"))

        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully.')
        # 重定向到一個合適的頁面，例如分類列表頁或首頁
        return redirect(reverse("videos:home"))  # 成功刪除後重定向到首頁

    # 如果不是 POST 請求，則顯示確認刪除頁面
    return render(request, "videos/confirm_delete_category.html", {"category": category})


@login_required
def delete_video(request, video_id):
    video = get_object_or_404(Video, pk=video_id)

    if video.uploader != request.user:
        messages.error(request, "您沒有權限刪除此影片。")
        return redirect(reverse("videos:video_detail", args=[video.id]))

    if request.method == "POST":
        video_path = os.path.join(settings.MEDIA_ROOT, str(video.video_file))
        thumbnail_path = None
        if video.thumbnail:
            thumbnail_path = os.path.join(settings.MEDIA_ROOT, str(video.thumbnail))

        video_title = video.title
        video.delete()  # Delete the video record from the database

        # Attempt to delete the video file
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
        except OSError:
            logger.exception("刪除影片檔案失敗: %s", video_path)
            messages.warning(request, f"成功從資料庫刪除影片 '{video_title}' 的記錄，但刪除影片檔案時發生錯誤。")

        if thumbnail_path:
            try:
                if os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
            except OSError:
                logger.exception("刪除縮圖檔案失敗: %s", thumbnail_path)
                messages.warning(request, "刪除縮圖檔案時發生錯誤。")

        messages.success(request, f"影片 '{video_title}' 已成功刪除。")
        # Redirect to user's channel or home page
        # Assuming you have a 'channel' view in your 'users' app
        # If not, redirect to 'videos:home'
        try:
            return redirect(reverse("users:channel", args=[request.user.username]))
        except Exception:
            return redirect(reverse("videos:home"))

    # If GET request, show confirmation page
    return render(request, "videos/confirm_delete_video.html", {"video": video})


def video_status(request, video_id):
    """回傳影片處理狀態 JSON。"""
    video = get_object_or_404(Video, pk=video_id)
    return JsonResponse({"status": video.processing_status or "pending"})


def _get_hls_video(request, video_id):
    """取得影片並驗證 HLS 存取權限，回傳 video 物件。"""
    video = get_object_or_404(Video, pk=video_id)
    if video.visibility == "private" and (not request.user.is_authenticated or video.uploader != request.user):
        raise Http404("影片不存在或無權限訪問")
    if not video.hls_path:
        raise Http404("HLS 文件不存在")
    return video


def serve_hls_playlist(request, video_id):
    """服務 HLS 播放清單文件"""
    video = _get_hls_video(request, video_id)
    playlist_path = os.path.join(settings.MEDIA_ROOT, video.hls_path)

    try:
        with open(playlist_path, encoding="utf-8") as f:
            content = f.read()
        response = HttpResponse(content, content_type="application/vnd.apple.mpegurl")
        response["Cache-Control"] = "no-cache"
        return response
    except OSError as e:
        raise Http404(f"讀取 HLS 播放清單失敗: {str(e)}") from e


def serve_hls_segment(request, video_id, segment_name):
    """服務 HLS 片段文件"""
    video = _get_hls_video(request, video_id)

    # 構建片段文件路徑
    hls_dir = os.path.realpath(os.path.dirname(os.path.join(settings.MEDIA_ROOT, video.hls_path)))
    segment_path = os.path.realpath(os.path.join(hls_dir, segment_name))

    # 安全檢查：確保請求的文件在正確的目錄中（防止路徑穿越）
    if not segment_path.startswith(hls_dir + os.sep):
        raise Http404("無效的片段請求")

    try:
        with open(segment_path, "rb") as f:
            content = f.read()

        response = HttpResponse(content, content_type="video/mp2t")
        response["Cache-Control"] = "public, max-age=3600"
        return response
    except OSError as e:
        raise Http404(f"讀取 HLS 片段失敗: {str(e)}") from e
