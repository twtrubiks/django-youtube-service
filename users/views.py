from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django_ratelimit.decorators import ratelimit

from interactions.models import Subscription
from videos.models import Video

from .forms import UserEditForm, UserLoginForm, UserProfileForm, UserRegistrationForm
from .models import UserProfile


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
def register_view(request):
    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            new_user = form.save(commit=False)
            new_user.set_password(form.cleaned_data["password"])
            try:
                with transaction.atomic():
                    new_user.save()
            except IntegrityError:
                # clean_email 通過後、寫入前的併發註冊：被 DB 唯一索引擋下，
                # 回填表單錯誤而非 500
                form.add_error("email", "A user with that email already exists.")
            else:
                # UserProfile is created by signal
                messages.success(request, "Registration successful. Please log in.")
                return redirect("users:login")
    else:
        form = UserRegistrationForm()
    return render(request, "users/register.html", {"form": form})


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def login_view(request):
    if request.method == "POST":
        form = UserLoginForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = authenticate(request, username=cd["username"], password=cd["password"])
            if user is not None:
                # authenticate 成功時，user.is_active 必定為 True (除非自訂 backend)
                # Django 的 ModelBackend 會處理 is_active
                login(request, user)
                messages.success(request, "Authenticated successfully")
                return redirect("users:channel", username=user.username)
            else:
                # 帳號不存在、密碼錯誤、帳號停用一律回同一訊息，避免帳號枚舉
                messages.error(request, "Invalid login")
    else:
        form = UserLoginForm()
    return render(request, "users/login.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "You have been successfully logged out.")
    return redirect("users:login")  # Or to homepage


@login_required
def edit_profile_view(request):
    if request.method == "POST":
        user_form = UserEditForm(instance=request.user, data=request.POST)
        profile_form = UserProfileForm(instance=request.user.profile, data=request.POST, files=request.FILES)

        if "delete_banner" in request.POST:
            profile = request.user.profile
            if profile.banner_image:
                profile.banner_image.delete(save=False)  # Delete the file from storage
                profile.banner_image = None
                profile.save()
                messages.success(request, "Banner image removed successfully.")
            # We might want to redirect here or let the rest of the form processing continue
            # For now, let's assume if they delete, they might also be updating other fields.

        if user_form.is_valid() and profile_form.is_valid():
            try:
                with transaction.atomic():
                    user_form.save()
                    profile_form.save()
            except IntegrityError:
                # clean_email 通過後、寫入前把 email 改成別人剛用掉的：被 DB 唯一索引擋下
                user_form.add_error("email", "A user with that email already exists.")
                messages.error(request, "Error updating your profile")
            else:
                messages.success(request, "Profile updated successfully")
                return redirect("users:channel", username=request.user.username)
        else:
            messages.error(request, "Error updating your profile")
    else:
        user_form = UserEditForm(instance=request.user)
        profile_form = UserProfileForm(instance=request.user.profile)
    return render(request, "users/edit_profile.html", {"user_form": user_form, "profile_form": profile_form})


def user_channel_view(request, username):
    try:
        # Corrected to use UserProfile to find the user, then get videos
        profile_owner_profile = UserProfile.objects.get(user__username=username)
        profile_owner = profile_owner_profile.user
        user_videos = Video.objects.filter(uploader=profile_owner).select_related("uploader").order_by("-upload_date")
        # 訪客只能看到 public 影片；private/unlisted 只在本人查看自己頻道時列出
        if request.user != profile_owner:
            user_videos = user_videos.listable()
    except UserProfile.DoesNotExist:
        messages.error(request, "User channel not found.")
        # Assuming you will create a home view later. For now, redirect to login or register.
        return redirect("users:login")

    is_subscribed = False
    if request.user.is_authenticated and request.user != profile_owner:
        is_subscribed = Subscription.objects.filter(subscriber=request.user, subscribed_to=profile_owner).exists()

    # 與其他列表頁一致的分頁（首頁/搜尋/分類/標籤皆為每頁 12 部）
    page_obj = Paginator(user_videos, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "users/channel.html",
        {
            "profile_owner": profile_owner,
            "user_videos": page_obj,
            "page_obj": page_obj,
            "profile": profile_owner_profile,
            "is_subscribed": is_subscribed,
        },
    )
