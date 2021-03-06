import functools
import os

import flask
from flask import render_template, request, redirect, url_for

from post_service import PostTable
from notification_service import Notifier

from authlib.client import OAuth2Session
import google.oauth2.credentials
import googleapiclient.discovery

ACCESS_TOKEN_URI = 'https://www.googleapis.com/oauth2/v4/token'
AUTHORIZATION_URL = 'https://accounts.google.com/o/oauth2/v2/auth?access_type=offline&prompt=consent'

AUTHORIZATION_SCOPE ='openid email profile'

AUTH_REDIRECT_URI = os.environ.get("FN_AUTH_REDIRECT_URI", default=False)
BASE_URI = os.environ.get("FN_BASE_URI", default=False)
CLIENT_ID = os.environ.get("FN_CLIENT_ID", default=False)
CLIENT_SECRET = os.environ.get("FN_CLIENT_SECRET", default=False)

AUTH_TOKEN_KEY = 'auth_token'
AUTH_STATE_KEY = 'auth_state'
USER_INFO_KEY = 'user_info'

app = flask.Flask(__name__, template_folder="views")
app.secret_key = os.environ.get("FN_FLASK_SECRET_KEY", default=False)

@app.route('/')
def index():
    if is_logged_in():
        user_info = get_user_info()
        return redirect(url_for('posts'))
    else:
        return render_template('./login.html')

@app.route('/posts', methods=['GET', 'POST'])
def posts():
    if not is_logged_in():
        return redirect(url_for('index'))
    user_info = get_user_info()
    if request.method == 'POST':
        request_info = request.form.to_dict()
        PostTable.create_post(request_info, user_info)
        return redirect(url_for('posts'))

    elif request.method == 'GET':
        post_id = request.args.get('post_id')
        if post_id is not None:
            post = PostTable.get_post(post_id, user_info)
            return render_template('./post.html', post=post, user_info=user_info)
        else:
            posts = PostTable.list_posts()
            return render_template('./posts.html', posts=posts, user_info=user_info)

@app.route('/comments', methods=['GET', 'POST'])
def comments():
    if not is_logged_in():
        return redirect(url_for('index'))
    user_info = get_user_info()
    if request.method == 'POST':
        post_id = request.args.get('post_id')
        request_info = request.form.to_dict()
        PostTable.create_comment(request_info, user_info, post_id)
        return redirect('posts?post_id=' + str(post_id))

@app.route('/posts/create')
def create_post():
    if not is_logged_in():
        return redirect(url_for('index'))
    user_info = get_user_info()
    if request.method == 'GET':
        return render_template('./post_form.html', user_info=user_info)

@app.route('/comments/create')
def create_comment():
    if not is_logged_in():
        return redirect(url_for('index'))
    user_info = get_user_info()
    if request.method == 'GET':
        post_id = request.args.get('post_id')
        return render_template('./comment_form.html' , user_info=user_info, post_id=post_id)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    if not is_logged_in():
        return redirect(url_for('index'))
    user_info = get_user_info()
    if request.method == 'POST':
        post_id = request.args.get('post_id')
        target_user_id = request.args.get('user_id')
        print(target_user_id)
        Notifier.subscribe(target_user_id, user_info)
        return redirect('posts?post_id=' + str(post_id))

def no_cache(view):
    @functools.wraps(view)
    def no_cache_impl(*args, **kwargs):
        response = flask.make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        return response

    return functools.update_wrapper(no_cache_impl, view)

@app.route('/google/login')
@no_cache
def login():
    session = OAuth2Session(CLIENT_ID, CLIENT_SECRET, scope=AUTHORIZATION_SCOPE, redirect_uri=AUTH_REDIRECT_URI)
    uri, state = session.authorization_url(AUTHORIZATION_URL)
    flask.session[AUTH_STATE_KEY] = state
    flask.session.permanent = True
    return flask.redirect(uri, code=302)


@app.route('/google/auth')
@no_cache
def google_auth_redirect():
    state = flask.request.args.get('state', default=None, type=None)

    session = OAuth2Session(CLIENT_ID, CLIENT_SECRET, scope=AUTHORIZATION_SCOPE, state=state, redirect_uri=AUTH_REDIRECT_URI)
    oauth2_tokens = session.fetch_access_token(ACCESS_TOKEN_URI, authorization_response=flask.request.url)
    flask.session[AUTH_TOKEN_KEY] = oauth2_tokens

    user_info = get_user_info()
    Notifier.add_user_sns(user_info)

    return flask.redirect(BASE_URI, code=302)

@app.route('/google/logout')
@no_cache
def logout():
    flask.session.pop(AUTH_TOKEN_KEY, None)
    flask.session.pop(AUTH_STATE_KEY, None)
    flask.session.pop(USER_INFO_KEY, None)

    return flask.redirect(BASE_URI, code=302)

def is_logged_in():
    return True if AUTH_TOKEN_KEY in flask.session else False

def build_credentials():
    if not is_logged_in():
        raise Exception('User must be logged in')

    oauth2_tokens = flask.session[AUTH_TOKEN_KEY]
    return google.oauth2.credentials.Credentials(
        oauth2_tokens['access_token'],
        refresh_token=oauth2_tokens['refresh_token'],
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri=ACCESS_TOKEN_URI)

def get_user_info():
    credentials = build_credentials()
    oauth2_client = googleapiclient.discovery.build('oauth2', 'v2', credentials=credentials)
    user_info = oauth2_client.userinfo().get().execute()
    user_info['id'] = int(user_info['id'])
    return user_info
