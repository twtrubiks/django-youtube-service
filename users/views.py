from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from .forms import UserRegistrationForm, UserLoginForm, UserProfileForm, UserEditForm
from .models import UserProfile
from videos.models import Video
from interactions.models import Subscription

def register_view(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            new_user = form.save(commit=False)
            new_user.set_password(form.cleaned_data['password'])
            new_user.save()
            # UserProfile is created by signal
            messages.success(request, 'Registration successful. Please log in.')
            return redirect('users:login')
    else:
        form = UserRegistrationForm()
    return render(request, 'users/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = authenticate(request, username=cd['username'], password=cd['password'])
            if user is not None:
                # authenticate 成功時，user.is_active 必定為 True (除非自訂 backend)
                # Django 的 ModelBackend 會處理 is_active
                login(request, user)
                messages.success(request, 'Authenticated successfully')
                return redirect('users:channel', username=user.username)
            else:
                # Authenticate failed
                try:
                    # 檢查用戶是否存在但未啟用
                    user_exists = User.objects.get(username=cd['username'])
                    if not user_exists.is_active:
                        messages.error(request, 'Disabled account')
                    else:
                        # 這種情況理論上不應該發生，因為如果 user_exists.is_active 為 True
                        # 且密碼正確，authenticate 應該成功。
                        # 如果密碼錯誤，則 authenticate 返回 None 是正常的。
                        messages.error(request, 'Invalid login')
                except User.DoesNotExist:
                    # 用戶名不存在
                    messages.error(request, 'Invalid login')
    else:
        form = UserLoginForm()
    return render(request, 'users/login.html', {'form': form})

@login_required
def logout_view(request):
    logout(request)
    messages.info(request, 'You have been successfully logged out.')
    return redirect('users:login') # Or to homepage

@login_required
def edit_profile_view(request):
    if request.method == 'POST':
        user_form = UserEditForm(instance=request.user, data=request.POST)
        profile_form = UserProfileForm(instance=request.user.profile, data=request.POST, files=request.FILES)

        if 'delete_banner' in request.POST:
            profile = request.user.profile
            if profile.banner_image:
                profile.banner_image.delete(save=False) # Delete the file from storage
                profile.banner_image = None
                profile.save()
                messages.success(request, 'Banner image removed successfully.')
            # We might want to redirect here or let the rest of the form processing continue
            # For now, let's assume if they delete, they might also be updating other fields.

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated successfully')
            return redirect('users:channel', username=request.user.username)
        else:
            messages.error(request, 'Error updating your profile')
    else:
        user_form = UserEditForm(instance=request.user)
        profile_form = UserProfileForm(instance=request.user.profile)
    return render(request, 'users/edit_profile.html', {'user_form': user_form, 'profile_form': profile_form})

def user_channel_view(request, username):
    try:
        # Corrected to use UserProfile to find the user, then get videos
        profile_owner_profile = UserProfile.objects.get(user__username=username)
        profile_owner = profile_owner_profile.user
        user_videos = Video.objects.filter(uploader=profile_owner).order_by('-upload_date') # Commenting out for now
    except UserProfile.DoesNotExist:
        messages.error(request, 'User channel not found.')
        # Assuming you will create a home view later. For now, redirect to login or register.
        return redirect('users:login')

    is_subscribed = False
    if request.user.is_authenticated and request.user != profile_owner:
        is_subscribed = Subscription.objects.filter(subscriber=request.user, subscribed_to=profile_owner).exists()

    return render(request, 'users/channel.html', {
        'profile_owner': profile_owner,
        'user_videos': user_videos, # Pass empty list for now
        'profile': profile_owner_profile,
        'is_subscribed': is_subscribed,
    })
