/* video_interactions.js - Comments and Votes for video detail page */

function toggleReplyForm(commentId) {
    var formContainer = document.getElementById('reply-form-container-' + commentId);
    if (formContainer) {
        formContainer.style.display = formContainer.style.display === 'none' ? 'block' : 'none';
        if (formContainer.style.display === 'block') {
            formContainer.querySelector('textarea[name="content"]').focus();
        }
    }
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
                    var parentReplies = document.getElementById('replies-to-' + data.parent_comment_id);
                    if (parentReplies) {
                        parentReplies.insertAdjacentHTML('beforeend', data.comment_html);
                        parentReplies.querySelectorAll('.reply-form-actual').forEach(function(f) {
                            if (!f.dataset.listenerAttached) {
                                handleCommentSubmission(f, true);
                                f.dataset.listenerAttached = 'true';
                            }
                        });
                    }
                } else {
                    commentsList.insertAdjacentHTML('beforeend', data.comment_html);
                    if (noCommentsMessage) noCommentsMessage.style.display = 'none';
                    var newComment = document.getElementById('comment-' + data.comment_id);
                    if (newComment) {
                        newComment.querySelectorAll('.reply-form-actual').forEach(function(f) {
                            if (!f.dataset.listenerAttached) {
                                handleCommentSubmission(f, true);
                                f.dataset.listenerAttached = 'true';
                            }
                        });
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
                document.getElementById('likes-count-display').textContent = 'Likes: ' + data.likes_count;
                document.getElementById('dislikes-count-display').textContent = 'Dislikes: ' + data.dislikes_count;
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

document.addEventListener('DOMContentLoaded', function() {
    var mainForm = document.getElementById('main-comment-form');
    if (mainForm) handleCommentSubmission(mainForm, false);

    document.querySelectorAll('.reply-form-actual').forEach(function(form) {
        if (!form.dataset.listenerAttached) {
            handleCommentSubmission(form, true);
            form.dataset.listenerAttached = 'true';
        }
    });

    initVoteForm();
});
