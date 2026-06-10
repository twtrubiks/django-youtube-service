/* video_interactions.js - Comments and Votes for video detail page */

function toggleReplyForm(commentId) {
    var formContainer = document.getElementById('reply-form-container-' + commentId);
    if (!formContainer) return;
    var isHidden = getComputedStyle(formContainer).display === 'none';
    formContainer.style.display = isHidden ? 'block' : 'none';
    if (isHidden) {
        var textarea = formContainer.querySelector('textarea[name="content"]');
        var commentEl = document.getElementById('comment-' + commentId);
        // 回覆「回覆」時預填 @作者 提供對話脈絡（後端會把它掛回頂層留言串）
        if (commentEl && commentEl.closest('.replies-container') && !textarea.value) {
            textarea.value = '@' + commentEl.dataset.author + ' ';
        }
        textarea.focus();
    }
}

function bindReplyForms(scope) {
    (scope || document).querySelectorAll('.reply-form-actual').forEach(function(form) {
        if (!form.dataset.listenerAttached) {
            handleCommentSubmission(form, true);
            form.dataset.listenerAttached = 'true';
        }
    });
}

function updateRepliesToggleText(btn, expanded) {
    if (expanded) {
        btn.textContent = 'Hide replies';
    } else {
        var count = btn.dataset.count;
        btn.textContent = 'View ' + count + (count === '1' ? ' reply' : ' replies');
    }
}

function loadReplies(commentId, page, replace) {
    var container = document.getElementById('replies-to-' + commentId);
    var base = document.getElementById('comments-list').dataset.repliesUrlBase;
    var url = base.replace('/0/', '/' + commentId + '/') + '?page=' + page;

    fetch(url)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.status !== 'success') return;
            var moreBtn = container.querySelector('.show-more-replies');
            if (moreBtn) moreBtn.remove();
            if (replace) {
                container.innerHTML = data.html;
            } else {
                container.insertAdjacentHTML('beforeend', data.html);
            }
            if (data.has_next) {
                container.insertAdjacentHTML('beforeend',
                    '<button type="button" class="button button-secondary button-small show-more-replies">Show more replies</button>');
                container.querySelector('.show-more-replies').addEventListener('click', function() {
                    loadReplies(commentId, data.next_page, false);
                });
            }
            bindReplyForms(container);
            container.style.display = 'block';
        })
        .catch(function(error) {
            console.error('Error loading replies:', error);
            showToast('Failed to load replies.');
        });
}

function bindRepliesToggles(scope) {
    (scope || document).querySelectorAll('.replies-toggle-btn').forEach(function(btn) {
        if (btn.dataset.listenerAttached) return;
        btn.dataset.listenerAttached = 'true';
        btn.addEventListener('click', function() {
            var commentId = btn.dataset.commentId;
            var container = document.getElementById('replies-to-' + commentId);
            var visible = getComputedStyle(container).display !== 'none';
            if (visible) {
                container.style.display = 'none';
                updateRepliesToggleText(btn, false);
            } else if (btn.dataset.loaded === 'true') {
                container.style.display = 'block';
                updateRepliesToggleText(btn, true);
            } else {
                btn.dataset.loaded = 'true';
                loadReplies(commentId, 1, true);
                updateRepliesToggleText(btn, true);
            }
        });
    });
}

function initLoadMoreComments() {
    var btn = document.getElementById('load-more-comments');
    if (!btn) return;
    btn.addEventListener('click', function() {
        var url = btn.dataset.url + '?page=' + btn.dataset.nextPage;
        if (btn.dataset.exclude) url += '&exclude=' + btn.dataset.exclude;
        btn.disabled = true;
        fetch(url)
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.status !== 'success') {
                    btn.disabled = false;
                    return;
                }
                var commentsList = document.getElementById('comments-list');
                commentsList.insertAdjacentHTML('beforeend', data.html);
                bindReplyForms(commentsList);
                bindRepliesToggles(commentsList);
                if (data.has_next) {
                    btn.dataset.nextPage = data.next_page;
                    btn.disabled = false;
                } else {
                    btn.remove();
                }
            })
            .catch(function(error) {
                console.error('Error loading comments:', error);
                btn.disabled = false;
                showToast('Failed to load comments.');
            });
    });
}

function handleCommentSubmission(form, isReply) {
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        var formData = new FormData(form);
        var commentContent = formData.get('content').trim();
        var commentFormErrors = document.getElementById('comment-form-errors');
        var csrftoken = window.csrftoken;

        if (commentFormErrors && !isReply) commentFormErrors.innerHTML = '';

        if (!commentContent) {
            if (commentFormErrors && !isReply) commentFormErrors.innerHTML = '<p>Comment cannot be empty.</p>';
            if (isReply) showToast('Reply cannot be empty.');
            return;
        }

        fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': csrftoken, 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                var commentsList = document.getElementById('comments-list');
                var noCommentsMessage = document.getElementById('no-comments-message');
                var commentsCountSpan = document.getElementById('comments-count');

                if (data.is_reply) {
                    // parent_comment_id 一律是頂層留言（後端 re-root），容器必定存在
                    var parentReplies = document.getElementById('replies-to-' + data.parent_comment_id);
                    if (parentReplies) {
                        parentReplies.insertAdjacentHTML('beforeend', data.comment_html);
                        parentReplies.style.display = 'block';
                        bindReplyForms(parentReplies);
                        var toggleBtn = document.querySelector('.replies-toggle-btn[data-comment-id="' + data.parent_comment_id + '"]');
                        if (toggleBtn) {
                            toggleBtn.dataset.count = parseInt(toggleBtn.dataset.count || '0', 10) + 1;
                            toggleBtn.style.display = '';
                            updateRepliesToggleText(toggleBtn, true);
                        }
                    }
                } else {
                    commentsList.insertAdjacentHTML('afterbegin', data.comment_html);
                    if (noCommentsMessage) noCommentsMessage.style.display = 'none';
                    var newComment = document.getElementById('comment-' + data.comment_id);
                    if (newComment) {
                        bindReplyForms(newComment);
                        bindRepliesToggles(newComment);
                    }
                }
                form.reset();
                if (isReply) {
                    var container = form.closest('.reply-form-container');
                    if (container) container.style.display = 'none';
                }
                commentsCountSpan.textContent = parseInt(commentsCountSpan.textContent) + 1;
            } else if (data.status === 'error') {
                if (commentFormErrors && !isReply) {
                    var msgs = '';
                    for (var field in data.errors) {
                        msgs += '<p>' + field + ': ' + data.errors[field].join(', ') + '</p>';
                    }
                    if (!msgs && data.message) msgs = '<p>' + data.message + '</p>';
                    commentFormErrors.innerHTML = msgs;
                } else if (isReply) {
                    showToast('Error posting reply: ' + (data.message || JSON.stringify(data.errors)));
                }
            }
        })
        .catch(function(error) {
            console.error('Error:', error);
            if (commentFormErrors && !isReply) commentFormErrors.innerHTML = '<p>An unexpected error occurred.</p>';
            if (isReply) showToast('An unexpected error occurred with your reply.');
        });
    });
}

function initVoteForm() {
    var voteForm = document.getElementById('vote-form');
    if (!voteForm) return;
    var csrftoken = window.csrftoken;

    voteForm.addEventListener('submit', function(e) {
        e.preventDefault();
        var formData = new FormData(voteForm);
        var voteType = e.submitter && e.submitter.name === 'vote_type' ? e.submitter.value : null;
        if (voteType) formData.append('vote_type', voteType);

        fetch(voteForm.action, {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': csrftoken, 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                document.getElementById('likes-count-display').textContent = data.likes_count;
                document.getElementById('dislikes-count-display').textContent = data.dislikes_count;
                var likeBtn = document.getElementById('like-button');
                var dislikeBtn = document.getElementById('dislike-button');
                likeBtn.classList.remove('active');
                dislikeBtn.classList.remove('active-danger');
                if (data.current_user_vote_type === 'like') likeBtn.classList.add('active');
                else if (data.current_user_vote_type === 'dislike') dislikeBtn.classList.add('active-danger');
            } else {
                showToast('Error: ' + data.message);
            }
        })
        .catch(function(error) {
            console.error('Error:', error);
            showToast('An unexpected error occurred.');
        });
    });
}

function initSubscribeForm() {
    var form = document.getElementById('subscribe-form');
    if (!form) return;

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-CSRFToken': window.csrftoken, 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.status === 'success') {
                var btn = document.getElementById('subscribe-button');
                var count = document.getElementById('subscriber-count');
                if (count) count.textContent = data.subscribers_count;
                if (data.subscribed) {
                    btn.textContent = 'Subscribed';
                    btn.classList.add('button-secondary');
                } else {
                    btn.textContent = 'Subscribe';
                    btn.classList.remove('button-secondary');
                }
            } else {
                showToast('Error: ' + data.message);
            }
        })
        .catch(function(error) {
            console.error('Error:', error);
            showToast('An unexpected error occurred.');
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {
    var mainForm = document.getElementById('main-comment-form');
    if (mainForm) handleCommentSubmission(mainForm, false);

    bindReplyForms(document);
    bindRepliesToggles(document);
    initLoadMoreComments();
    initVoteForm();
    initSubscribeForm();
});
