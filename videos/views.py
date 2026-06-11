# 標準庫 imports
import logging

# Django imports
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import TrigramWordSimilarity
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_safe

# 第三方庫 imports
from django_ratelimit.decorators import ratelimit
from taggit.models import Tag

from interactions.forms import CommentForm
from interactions.models import Comment, LikeDislike, Subscription
from interactions.views import COMMENTS_PER_PAGE

# 本地應用 imports
from .forms import CategoryForm, VideoEditForm, VideoUploadForm
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

    # private 影片只有上傳者本人能看；unlisted 拿到連結即可觀看（與 HLS 端點的權限一致）
    if not video.is_accessible_by(request.user):
        raise Http404("影片不存在或無權限訪問")

    top_level_comments = (
        Comment.objects.filter(video=video, parent_comment__isnull=True)
        .select_related("user")
        .annotate(num_replies=Count("replies"))
        .order_by("-timestamp")
    )

    # 通知深連結：?comment=<id> 將該留言串釘選在列表最上方並預先展開回覆，
    # 確保留言分頁後 #comment-<id> anchor 仍然有效
    pinned_comment = None
    pinned_id = request.GET.get("comment")
    if pinned_id and pinned_id.isdigit():
        pinned = (
            Comment.objects.filter(video=video, pk=pinned_id).select_related("user", "parent_comment__user").first()
        )
        if pinned:
            pinned_comment = pinned.parent_comment or pinned
            pinned_comment.preloaded_replies = list(pinned_comment.replies.select_related("user").order_by("timestamp"))
            pinned_comment.num_replies = len(pinned_comment.preloaded_replies)
            top_level_comments = top_level_comments.exclude(pk=pinned_comment.pk)

    comments_page = Paginator(top_level_comments, COMMENTS_PER_PAGE).get_page(1)
    comments_count = video.comments.count()
    comment_form = CommentForm()

    viewed_video_session_key = f"viewed_video_{video.id}"
    if not request.session.get(viewed_video_session_key, False):
        Video.objects.filter(pk=video.pk).update(views_count=F("views_count") + 1)
        video.refresh_from_db(fields=["views_count"])
        request.session[viewed_video_session_key] = True

    vote_counts = video.vote_counts()

    # Get current user's vote
    user_vote = None
    if request.user.is_authenticated:
        try:
            user_vote_obj = LikeDislike.objects.get(video=video, user=request.user)
            user_vote = user_vote_obj.type
        except LikeDislike.DoesNotExist:
            pass  # User hasn't voted

    is_subscribed = False
    if request.user.is_authenticated and request.user != video.uploader:
        is_subscribed = Subscription.objects.filter(subscriber=request.user, subscribed_to=video.uploader).exists()

    related_videos = (
        Video.objects.listable().exclude(pk=video.pk).select_related("uploader").order_by("-upload_date")[:8]
    )

    context = {
        "video": video,
        "comments_page": comments_page,
        "comments_count": comments_count,
        "pinned_comment": pinned_comment,
        "comment_form": comment_form,
        "likes_count": vote_counts["likes"],
        "dislikes_count": vote_counts["dislikes"],
        "user_vote": user_vote,  # 'like', 'dislike', or None
        "category": video.category,
        "tags": video.tags.all(),
        "is_subscribed": is_subscribed,
        "related_videos": related_videos,
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
    videos = Video.objects.listable().select_related("uploader").order_by("-upload_date")
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
    query = request.GET.get("query", "")
    videos = Video.objects.none()
    # 子字串匹配（icontains + trigram 索引）而非 tsvector 全文搜尋：
    # 內建 text search config 不斷中文詞，tsvector 對中文內容幾乎無法命中。
    # 空白分隔的關鍵字各自匹配再 AND，沿用原 SearchQuery(plain) 的多關鍵字語意。
    terms = query.split()
    if terms:
        condition = Q()
        for term in terms:
            condition &= Q(title__icontains=term) | Q(description__icontains=term)
        videos = (
            Video.objects.listable()
            .filter(condition)
            # 排序用 word similarity：以「查詢與標題中最相似片段」計分，
            # 避免短查詢對長標題被整串長度稀釋；title 命中者自然排在僅 description 命中者之前
            .annotate(similarity=TrigramWordSimilarity(query, "title"))
            .select_related("uploader")
            .order_by("-similarity", "-upload_date")
        )

    paginator = Paginator(videos, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "videos/search_results.html", {"videos": page_obj, "page_obj": page_obj, "query": query})


@ratelimit(key="ip", rate="30/m", method="GET", block=True)
def search_suggest(request):
    """回傳搜尋建議（最多 5 筆影片標題）。使用 icontains 而非全文搜尋，因為自動完成需要匹配部分輸入。"""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"suggestions": []})
    titles = list(
        Video.objects.listable()
        .filter(title__icontains=query)
        .values_list("title", flat=True)
        .order_by("-upload_date")[:5]
    )
    return JsonResponse({"suggestions": titles})


@login_required
def edit_video(request, video_id):
    video = get_object_or_404(Video, pk=video_id)

    if video.uploader != request.user:
        messages.error(request, "You are not authorized to edit this video.")
        return redirect(reverse("videos:video_detail", args=[video.id]))

    if request.method == "POST":
        form = VideoEditForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            form.save()
            messages.success(request, "Video updated successfully.")
            return redirect(reverse("videos:video_detail", args=[video.id]))
        else:
            messages.error(request, "Error updating video. Please check the form.")
    else:
        form = VideoEditForm(instance=video)

    return render(request, "videos/edit_video.html", {"form": form, "video": video})


def videos_by_category(request, category_slug):
    category = get_object_or_404(Category, slug=category_slug)
    videos = Video.objects.listable().filter(category=category).select_related("uploader").order_by("-upload_date")
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
    videos = Video.objects.listable().filter(tags__slug=tag_slug).select_related("uploader").order_by("-upload_date")
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
        video_title = video.title
        video.delete()  # post_delete signal 會一併清理影片檔、縮圖、HLS 目錄與轉檔暫存副本

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
    # 與 video_detail 一致：private 影片的存在與處理狀態只有上傳者可見
    if not video.is_accessible_by(request.user):
        raise Http404("影片不存在或無權限訪問")
    return JsonResponse({"status": video.processing_status or "pending", "hls_status": video.hls_status})


def _decode_uri_header(raw):
    """還原 header 中的 UTF-8 路徑。

    nginx 將 $uri 以原始 bytes 傳遞，ASGI/WSGI 層以 latin-1 解碼成 str，
    路徑含中文（上傳檔名）時需先還原 bytes 再以 UTF-8 解碼。
    """
    try:
        return raw.encode("iso-8859-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


@require_safe
def media_auth(request):
    """nginx auth_request 子請求端點：判斷受保護媒體檔（HLS、mp4）的存取權限。

    nginx 以 X-Original-URI header 帶入正規化後的請求路徑（見 nginx/nginx.conf），
    本 view 只回授權結果（204 允許 / 403 拒絕），檔案傳輸由 nginx 處理；
    授權結果由 nginx 以（session, 影片）為鍵快取，避免每個 HLS 片段都打進 Django。
    """
    uri = _decode_uri_header(request.headers.get("X-Original-URI", ""))

    video = None
    if uri.startswith("/media/hls/"):
        # HLS 目錄名以 <video_id>_ 開頭（見 tasks.generate_hls_files）
        video_id = uri[len("/media/hls/") :].split("/", 1)[0].split("_", 1)[0]
        if video_id.isdigit():
            video = Video.objects.filter(pk=video_id).only("visibility", "uploader_id").first()
    elif uri.startswith("/media/videos/"):
        # mp4 的 URL 不含影片 id，以 video_file 欄位值反查；
        # 磁碟上未被任何 Video 引用的檔案（如轉檔前的原始上傳檔）一律拒絕
        video = Video.objects.filter(video_file=uri[len("/media/") :]).only("visibility", "uploader_id").first()

    if video is None:
        return HttpResponseForbidden()
    if not video.is_accessible_by(request.user):
        return HttpResponseForbidden()
    return HttpResponse(status=204)
