#!/usr/bin/python3
# -*- coding: utf-8 -*-

import difflib
import os
import os.path
import logging
import logging.config
import sys
import re
import hashlib
import datetime
import random
import yaml

from itertools import groupby

from urllib.parse import urlencode

from flask import (Flask, abort, flash, redirect, render_template,
                   request, url_for, jsonify, make_response, current_app)
from flask_assets import Environment, Bundle
from flask_login import (
    LoginManager, current_user,
    login_required, login_user, logout_user
)
from flask_babel import Babel, gettext
from flask_caching import Cache
from flask_compress import Compress

from jinja2 import pass_eval_context, Markup

from form import (LoginForm, RegisterForm, CommunityCreateForm)

import peewee

from playhouse.flask_utils import get_object_or_404, object_list

from models import (Comment, AnonymousUser, User, Community, CommunityUser,
                    Proposal, CommentVote, PostVote, Moderator, Tag,
                    PostHistory, PostInternalVote, db)

from slugify import slugify


_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')

#
# http://www.evanmiller.org/how-not-to-sort-by-average-rating.html
#


def create_app(config_file='config.yaml'):
    config = {}

    for f in ['config.yaml',
              os.path.join(os.getcwd(), 'config.yaml'),
              os.path.join(os.path.expanduser('~'), '.pnyx/config.yaml'),
              os.environ.get('PNYXCONF'), None]:
        try:
            with open(f) as cfg:
                config = yaml.safe_load(cfg.read())
                if config:
                    break

        except IOError as e:
            print(e)

        except Exception as e:
            print("No configuration", e)

    app = Flask(__name__, template_folder='../templates',
                static_folder='../static')
    app.config.from_mapping(config.get(config.get('instance')))

    logging.config.dictConfig(
        config.get(config.get('instance')).get('logging', {}))

    if 'BABEL_TRANSLATION_DIRECTORIES' not in app.config.keys():
        app.config['BABEL_TRANSLATION_DIRECTORIES'] = \
            'translations;../translations'

    return app


app = create_app("config.yaml")
babel = Babel(app)
cache = Cache(app)
Compress(app)
login_manager = LoginManager()
login_manager.login_view = "login"
assets = Environment(app)

css_easymde = Bundle('css/easymde.min.css',
                     output='gen/easymde.min.css')
js_easymde = Bundle('js/easymde.min.js',
                    output='gen/easymde.min.js')

css = Bundle('css/bootstrap_pnyx.min.css',
             'css/select2-bootstrap4.min.css',
             'css/pnyx.css',
             # filters='cssmin',
             output='gen/screen.css')
assets.register('css_all', css)
assets.register('css_easymde', css_easymde)
assets.register('js_easymde', js_easymde)

db.init_app(app)
database = db.database
app.database = database


@app.route('/submit_comment', methods=['POST'])
@login_required
def submit_comment():
    comment = Comment()

    content = request.form.get('content')
    slug = request.form.get('slug')
    user = User.get(User.id == current_user.id)
    root = request.form.get('parent') or None

    if not(content and slug and user):
        flash('Missing content or reference to Post')
        return redirect(url_for('feed', feed='new'))

    else:
        comment.post = Proposal.get(Proposal.slug == slug)

        if root is not None and not (
                Comment.get(Comment.id == root).post == comment.post):
            flash('Invalid comment reference')
            return redirect(
                url_for('post_details',
                        slug=slug,
                        community=comment.post.community.name))
        else:
            comment.content = content
            comment.user = user
            comment.root = root

            try:
                with database.atomic():
                    comment.save()

            except peewee.IntegrityError:
                flash('Unable to save comment', 'error')

            else:
                return redirect(
                    url_for('post_details',
                            slug=slug,
                            community=comment.post.community.name))

    return redirect(
        url_for('post_details', slug=slug, community=comment.post.community))


@app.route('/submit', methods=['GET', 'POST'])
@app.route('/c/<community>/submit', methods=['GET', 'POST'])
@app.route('/u/<user>/submit', methods=['GET', 'POST'])
@cache.cached(timeout=50)
@login_required
def post_submit(user=None, community=None):
    entry = Proposal(community='', title='', content='')

    if community is None:
        community = request.form.get('community') or None
        if community and community[0:2] == "c/":
            community = community[2:]

    if request.method == 'POST':
        try:
            entry.title = request.form.get('title') or ''
            entry.content = request.form.get('content') or ''
            entry.published = request.form.get('published') or True
            entry.vote_options = request.form.get('internalvote') or None
            entry.usepositions = (
                True if request.form.get('use-positions') == '' else False
            )
            entry.author = User.get(User.id == current_user.id)
            entry.community = Community.get(Community.name == community)

            if not (entry.title and entry.community and entry.author):
                flash('Community and Title are required.', 'error')

            else:
                entry.update_search_index()

                # Wrap the call to save in a transaction so we can roll it back
                # cleanly in the event of an integrity error.
                try:
                    with database.atomic():
                        entry.save()

                except peewee.IntegrityError:
                    flash('This title is already in use.', 'error')
                else:

                    if entry.published:
                        return redirect(
                            url_for('post_details',
                                    community=entry.community.name,
                                    slug=entry.slug))
                    else:
                        abort(404)

        except peewee.DoesNotExist:
            flash('Community and Title are required.', 'error')

    if community is not None:
        community = Community.get_or_none(Community.name == community)

    return render_template('submit.html', entry=entry, community=community)


@app.route('/p/<slug>/edit', methods=['GET', 'POST'])
@login_required
def post_edit(slug):
    entry = get_object_or_404(Proposal, Proposal.slug == slug)
    if entry.author_id != current_user.id:
        abort(404)

    if request.method == 'POST':
        with database.atomic():
            new_content = request.form.get('content') or ''
            new_vote_opt = request.form.get('internalvote', None)
            new_usepositions = (
                True if request.form.get('use-positions') == '' else False
            )

            if new_content != entry.content:
                ph = PostHistory()
                ph.post = entry
                ph.user_id = current_user.id
                ph.content = entry.content
                ph.save()

            if new_vote_opt is not None and new_vote_opt != entry.vote_options:
                PostInternalVote.delete().where(
                    PostInternalVote.post == entry
                ).execute()
                # Drop all existing votes
                entry.vote_options = new_vote_opt

            if new_usepositions != entry.usepositions:
                entry.usepositions = new_usepositions

            entry.modified = datetime.datetime.now()
            entry.content = new_content
            entry.update_search_index()
            entry.save()

        return redirect(
            url_for('post_details',
                    slug=entry.slug, community=entry.community.name))

    return render_template('submit.html',
                           entry=entry, community=entry.community)


@app.route('/u/<user>', methods=["GET", "POST"])
def user_page(user):
    u = get_object_or_404(User, User.username == user)
    query = u.posts.order_by(Proposal.timestamp.desc())

    return object_list(
        'user.html',
        query,
        user=u,
        check_bounds=False)


@app.route('/u/<user>', methods=["DELETE"])
def user_delete(user):
    u = get_object_or_404(User, User.username == user)
    u.delete_instance()
    return "", 204


@app.route('/u/<user>/karma', methods=['GET'])
def user_karma(user):
    u = get_object_or_404(User, User.username == user)
    return str(u.karma_count), 200


@app.route('/u/<user>/delete', methods=['GET'])
def user_delete_verify(user):
    u = get_object_or_404(User, User.username == user)

    if u.id != current_user.id:
        return render_template('403.html'), 403

    return render_template(
        'user_delete_verify.html', user=u)


@app.route('/u/subscribe/<community>', methods=['GET'])
@login_required
def community_subscribe(community):
    fu = CommunityUser(community=Community.get(Community.name == community),
                       user=User.get(User.id == current_user.id))

    try:
        with database.atomic():
            fu.save()
    except peewee.IntegrityError as e:
        print(e)

    else:
        return redirect(url_for("community", community=community))

    # flash error message

    return redirect(url_for("community", community=community))


#
# Community
#
@app.route('/c/<community>')
@cache.cached(timeout=50)
def community(community):
    community_ref = Community.get_or_none(Community.name == community)
    return object_list('community.html',
                       Proposal.from_community(community_ref).order_by(
                          Proposal.timestamp.desc()),
                       community=community_ref,
                       check_bounds=False)


@app.route('/c/<community>.rss', methods=["GET"])
@cache.cached(timeout=50)
def community_rss(community):
    community_ref = Community.get_or_none(Community.name == community)
    response = make_response(community_ref.rss_feed)
    response.headers['Content-Type'] = 'application/rss+xml; charset=utf-8'
    return response


@app.route('/c/<community>/<slug>')
@cache.cached(timeout=50)
def post_details(community, slug):
    query = Proposal.public()
    community_id = Community.get_or_none(Community.name == community)
    entry = get_object_or_404(query, Proposal.slug == slug,
                              Proposal.community == community_id)
    return render_template('post.html', entry=entry, community=community_id)


@app.route('/c/<community>/<slug>/revisions')
def post_revisions(community, slug):
    query = Proposal.public()
    community = Community.get_or_none(Community.name == community)
    entry = get_object_or_404(query, Proposal.slug == slug,
                              Proposal.community == community)
    return render_template('post_revisions.html',
                           entry=entry, community=community)


@app.route('/community/slug_gen', methods=['GET'])
@login_required
def community_slug_generate():
    return jsonify({"slug": slugify(request.args.get('t', ''))})


@app.route('/community/create', methods=['GET', 'POST'])
@login_required
@database.atomic()
def community_create():
    form = CommunityCreateForm()

    form.tags.choices = [
        (t.title, t.title) for t in Tag.select(Tag.title).order_by(
            Tag.title).distinct()
    ]

    if form.validate_on_submit() and current_user.karma >= 50:
        community = Community()

        community.name = slugify(form.name.data)
        community.description = form.description.data
        community.maintainer = User.get(User.id == current_user.id)

        community.update_search_index()

        user = User.get(User.id == current_user.id)
        user.karma -= 50
        user.save()

        success = True

        try:
            community.save()

        except peewee.IntegrityError:
            flash(gettext('This name is already in use.'), 'error')
            success = False

        else:
            try:
                for element in form.tags.data.split(','):
                    if not element:
                        continue

                    tag = Tag()
                    # FIXME: slugify?
                    tag.title = element
                    tag.community = community
                    tag.save()

            except peewee.IntegrityError:
                flash(gettext('Unable to add tags.'), 'error')
                success = False

        if success:
            return redirect(url_for('community', community=community.name))

    return render_template('community_create.html', form=form)


@app.route('/community/search', methods=['GET'])
def community_search():
    db_query = Community.select(
        Community.name,
        Community.description
    )

    search_query = request.args.get('q')
    if search_query:
        db_query = db_query.where(
            Community.prefix_name.contains(search_query)
        )

    db_query = db_query.order_by(Community.name).limit(30)

    # hits = [model_to_dict(hit, recurse=True) for hit in db_query]

    result = []
    for hit in db_query:
        result.append({
            "id": hit.name_with_prefix,
            "text": hit.name_with_prefix
        })

    feeds = [
        {"id": "", "text": "Frontpage"},
        {"id": "f/popular", "text": "Popular"},
        {"id": "f/new", "text": "New"},
        {"id": "f/upvote", "text": "Most upvoted"}
    ]

    # print(json.dumps({"suggestions": feeds + hits}, indent=4))

    if request.args.get('s'):
        return jsonify({"results": result})

    return jsonify({"results": [{
        "text": "Feeds",
        "children": feeds,
    }, {
        "text": "Other",
        "children": result,
    }]})


#
# Voting
#

@app.route('/p/intvote/<slug>', methods=['POST'])
@login_required
@database.atomic()
def proposal_intvote(slug):
    vote = request.form.get('vote') or None
    if not vote:
        return jsonify({"error": "invalid vote parameter"}), 400

    prop = Proposal.get(Proposal.slug == slug)

    if vote == '':  # Pull vote
        PostInternalVote.delete().where(
            PostInternalVote.user_id == current_user.id and
            PostInternalVote.post == prop.id
        ).execute()

    else:
        (PostInternalVote.insert(
            post=prop, user=current_user.id, vote=vote
        ).on_conflict(
            conflict_target=[PostInternalVote.user, PostInternalVote.post],
            preserve=[PostInternalVote.vote, PostInternalVote.timestamp]
        ).execute())

    return jsonify({"status": "ok"})


@app.route('/p/upvote/<slug>', methods=['GET'])
@login_required
@database.atomic()
def proposal_upvote(slug):
    prop = Proposal.get(Proposal.slug == slug)

    result = {"diff": '0', "votes": str(prop.votes)}

    if current_user.id == prop.author_id or current_user.karma <= 0:
        return jsonify(result)

    if current_user.has_upvoted(prop):
        prop.upvotes -= 1
        # current_user.karma += 1
        prop.author.karma -= 1  # Not so sure about this...
        PostVote.delete().where(
            (PostVote.post == prop) & (PostVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '-1'
    else:
        score_mod = 1
        if current_user.has_downvoted(prop):
            score_mod = 2

        result["diff"] = '+' + str(score_mod)
        prop.upvotes += score_mod
        # current_user.karma -= 1
        prop.author.karma += 1

        (PostVote.insert(
            post=prop, user=current_user.id, vote=1
        ).on_conflict(
            conflict_target=[PostVote.user, PostVote.post],
            preserve=[PostVote.vote, PostVote.timestamp]
        ).execute())

    Proposal.save(prop)
    
    # FIXME move karma to another table
    User.save(prop.author)
    User.save(current_user)

    result["votes"] = str(prop.votes)

    return jsonify(result)


@app.route('/p/downvote/<slug>', methods=['GET'])
@login_required
@database.atomic()
def proposal_downvote(slug):
    prop = Proposal.get(Proposal.slug == slug)

    result = {"diff": '0', "votes": str(prop.votes)}

    if current_user.id == prop.author_id or current_user.karma <= 0:
        return jsonify(result)

    if current_user.has_downvoted(prop):
        # current_user.karma += 1
        prop.author.karma += 1
        prop.downvotes -= 1
        PostVote.delete().where(
            (PostVote.post == prop) & (PostVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '+1'

    else:
        # current_user.karma -= 1
        prop.author.karma -= 1
        score_mod = 1
        if current_user.has_upvoted(prop):
            score_mod = 2
        result["diff"] = str(-score_mod)
        prop.downvotes += score_mod

        (PostVote.insert(
            post=prop, user=current_user.id, vote=-1
        ).on_conflict(
            conflict_target=[PostVote.user, PostVote.post],
            preserve=[PostVote.vote, PostVote.timestamp]
        ).execute())

    Proposal.save(prop)

    # FIXME move karma to another table
    User.save(current_user)
    User.save(prop.author)

    result["votes"] = str(prop.votes)

    return jsonify(result)


@app.route('/p/upvote/<slug>/<comment_id>', methods=['GET'])
@login_required
@database.atomic()
def comment_upvote(slug, comment_id):
    # Ensure comment belongs to slug
    # prop = Proposal.get(Proposal.slug == slug)
    comment = Comment.get(Comment.id == comment_id)

    result = {"diff": '0', "score": str(comment.score)}

    if current_user.id == comment.user_id or current_user.karma <= 0:
        return jsonify(result)

    if current_user.has_upvoted(comment):
        # current_user.karma += 1
        comment.score -= 1
        CommentVote.delete().where(
            (CommentVote.comment == comment) &
            (CommentVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '-1'
    else:
        # current_user.karma -= 1
        score_mod = 1
        if current_user.has_downvoted(comment):
            score_mod = 2

        comment.score += score_mod

        result["diff"] = '+' + str(score_mod)

        (CommentVote.insert(
            comment=comment, user=current_user.id, vote=1
        ).on_conflict(
            conflict_target=[CommentVote.user, CommentVote.comment],
            preserve=[CommentVote.vote, CommentVote.timestamp]
        ).execute())

    Comment.save(comment)
    # FIXME move karma to another table
    User.save(current_user)

    result["score"] = str(comment.score)

    return jsonify(result)


@app.route('/p/downvote/<slug>/<comment_id>', methods=['GET'])
@login_required
@database.atomic()
def comment_downvote(slug, comment_id):
    # Ensure comment belongs to slug
    # prop = Proposal.get(Proposal.slug == slug)
    comment = Comment.get(Comment.id == comment_id)

    result = {"diff": '0', "score": str(comment.score)}

    if current_user.id == comment.user_id or current_user.karma <= 0:
        return jsonify(result)

    if current_user.has_downvoted(comment):
        comment.score += 1
        # current_user.karma += 1
        CommentVote.delete().where(
            (CommentVote.comment == comment) &
            (CommentVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '+1'
    else:
        score_mod = 1
        if current_user.has_upvoted(comment):
            score_mod = 2
        result["diff"] = str(-score_mod)

        comment.score -= score_mod
        # current_user.karma -= 1

        (CommentVote.insert(
            comment=comment, user=current_user.id, vote=-1
        ).on_conflict(
            conflict_target=[CommentVote.user, CommentVote.comment],
            preserve=[CommentVote.vote, CommentVote.timestamp]
        ).execute())

    Comment.save(comment)
    # FIXME move karma to another table
    # User.save(current_user)

    result["score"] = str(comment.score)

    return jsonify(result)


@app.route('/p/blankvote/<slug>/<comment_id>', methods=['GET'])
@login_required
@database.atomic()
def comment_blankvote(slug, comment_id):
    # Ensure comment belongs to slug
    # prop = Proposal.get(Proposal.slug == slug)
    comment = Comment.get(Comment.id == comment_id)

    result = {"diff": '0', "score": str(comment.score)}

    if current_user.id == comment.user_id or current_user.karma <= 0:
        return jsonify(result)

    score_mod = 1

    if current_user.has_upvoted(comment):
        comment.score -= 1
        score_mod = 2
        result["diff"] = str(-score_mod)
    elif current_user.has_downvoted(comment):
        comment.score += 1
        score_mod = 2
        result["diff"] = str(score_mod)

    Comment.save(comment)

    (CommentVote.insert(
        comment=comment, user=current_user.id, vote=0
    ).on_conflict(
        conflict_target=[CommentVote.user, CommentVote.comment],
        preserve=[CommentVote.vote, CommentVote.timestamp]
    ).execute())

    # FIXME move karma to another table
    # User.save(current_user)

    result["score"] = str(comment.score)

    return jsonify(result)


#
# Proposal, load all comments
#
@app.route('/p/<slug>/comments', methods=['GET'])
@cache.cached(timeout=50)
def all_comments_for_post(slug):
    entry = get_object_or_404(Proposal, Proposal.slug == slug)
    return render_template(
        'includes/comments.html', entry=entry, load_all=True)


#
# Proposal, load random comment
#
@app.route('/p/<slug>/random_comment', methods=['GET'])
@cache.cached(timeout=50)
def random_comment_for_post(slug):
    entry = get_object_or_404(Proposal, Proposal.slug == slug)
    comments = entry.comments()
    return render_template('random_comment.html', entry=entry,
                           reply=random.choice(comments))


#
# Proposal, load random comment
#
@app.route('/p/<slug>/report', methods=['GET'])
@cache.cached(timeout=50)
def report_for_post(slug):
    entry = get_object_or_404(Proposal, Proposal.slug == slug)

    comments = Comment.select(
        Comment.id,
        Comment.content,
        CommentVote.vote,
        peewee.fn.COUNT(CommentVote.vote)).join(CommentVote).where(
        Comment.post == entry).group_by(Comment.id, CommentVote.vote).order_by(
            Comment.timestamp).dicts()

    result_list = []
    for key, grp in groupby(comments, key=lambda x: x['id']):
        item = {
            'content': None,
            'options': {
                'yes': 0,
                'no': 0,
                'undecided': 0
            },
            'percentages': {
                'yes': 0,
                'no': 0,
                'undecided': 0
            },
            'total_votes': 0
        }

        for v in grp:
            item['content'] = v['content']

            if v['vote'] == 0:
                item['options']['undecided'] = v['count']

            elif v['vote'] == 1:
                item['options']['yes'] = v['count']

            elif v['vote'] == -1:
                item['options']['no'] = v['count']

        total = float(sum(item['options'].values()))
        item['total_votes'] = total
        item['percentages']['yes'] = round(
            (item['options']['yes'] / total) * 100)
        item['percentages']['no'] = round(
            (item['options']['no'] / total) * 100)
        item['percentages']['undecided'] = round(
            (item['options']['undecided'] / total) * 100)
        result_list.append(item)

    return render_template('very_basic_report.html', entry=entry,
                           comments=result_list)


#
# Login/Logout/Register
#
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Here we use a class of some kind to represent and validate our
    # client-side form data. For example, WTForms is a library that will
    # handle this for us, and we use a custom LoginForm to validate.
    form = LoginForm()

    # next = get_redirect_target()
    # next = None

    if form.validate_on_submit():
        # Login and validate the user.
        # user should be an instance of your `User` class
        shasum = hashlib.sha384(form.password.data.encode()).hexdigest()

        try:
            user = User.get(User.username == form.username.data,
                            User.password == shasum)
        except peewee.DoesNotExist:
            flash("Invalid username or password", "error")
            return redirect(url_for('login'))

        login_user(user)

        return render_template('login.html')  # form.redirect('index')

    return render_template('login.html',
                           form=form,
                           next=request.args.get('next'))


@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('feed', feed='new'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.is_submitted():
        if not form.validate():
            for key, items in form.errors.items():
                for err in items:
                    flash(err, 'error')

        else:
            user = User()
            user.username = form.username.data
            user.password = hashlib.sha384(
                form.password.data.encode()).hexdigest()
            user.karma = 0

            try:
                with database.atomic():
                    user.save()

            except peewee.IntegrityError:
                flash('This username is already in use.', 'error')

            else:
                login_user(user)
                return redirect(url_for('user_page', user=user.username))

    return render_template('register.html', form=form)


#
# Misc
#

@app.route('/f/<feed>')
def feed(feed):
    query = Proposal.public()

    # FIXME: better sorting

    community = None

    if feed == "popular":
        query = query.order_by(-Proposal.ranking)
        community = Community(name="popular",
                              description="The most popular posts on Pnyx.")

    elif feed == "upvote":
        query = query.order_by(-(Proposal.upvotes - Proposal.downvotes))
        community = Community(name="upvote",
                              description="The most upvoted posts on Pnyx.")

    elif feed == "new":
        query = query.order_by(Proposal.timestamp.desc())
        community = Community(name="new",
                              description=gettext(
                                "The newest posts from all of Pnyx. Come here "
                                "to see posts rising and be a part of "
                                "the conversation."))

    else:
        query = query.order_by(-Proposal.ranking, Proposal.timestamp.desc())

    return object_list(
        'community.html',
        query,
        community=community,
        check_bounds=False)


@app.route('/')
def frontpage():
    posts = (
        Proposal.all()
        .where(Proposal.published == True)
        .order_by(Proposal.timestamp.desc())
        .limit(20)
    )

    return object_list(
        'frontpage.html',
        posts,
        check_bounds=False,
        paginate_by=50)


@app.route('/search')
def search():
    search_query = request.args.get('q').strip()

    if search_query:
        try:
            post_query = Proposal.search(search_query)
            community_query = Community.search(search_query)

            return object_list(
                'search.html',
                post_query,
                communitys=community_query,
                search=search_query,
                check_bounds=False)

        except (peewee.InternalError, peewee.IntegrityError,
                peewee.ProgrammingError):
            # flash("Invalid query '{0}'".format(search_query), 'error')
            pass

    return render_template('search.html', search=search_query, pagination=None)


@app.route('/licenses')
def licenses():
    return render_template('licenses.html')


@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
    querystring = dict((key, value) for key, value in request_args.items())
    for key in keys_to_remove:
        querystring.pop(key, None)
    querystring.update(new_values)
    return urlencode(querystring)


@login_manager.user_loader
def load_user(user_id):
    user = User.get_or_none(User.id == int(user_id))
    if user is None:
        return AnonymousUser()
    return user


def request_wants_json():
    best = request.accept_mimetypes \
        .best_match(['application/json', 'text/html'])

    return best == 'application/json' and \
        request.accept_mimetypes[best] > \
        request.accept_mimetypes['text/html']


@login_manager.unauthorized_handler
def unauthorized():
    if request_wants_json():
        return jsonify({"error": "unauthorized", "code": 401})
    # do stuff
    return redirect(url_for('login'))


@app.errorhandler(404)
def not_found(exc):
    return render_template('404.html'), 404


@app.template_filter()
@pass_eval_context
def nl2br(eval_ctx, value):
    result = "<br>\n".join(value.splitlines())
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


@app.template_filter()
@pass_eval_context
def htmldiff(eval_ctx, a, b):
    a = a.splitlines()
    b = b.splitlines()

    diff_html = ""
    theDiffs = difflib.ndiff(a, b)
    for eachDiff in theDiffs:
        if (eachDiff[0] == "-"):
            diff_html += "<del>%s</del>" % eachDiff[1:].strip()
        elif (eachDiff[0] == "+"):
            diff_html += "<ins>%s</ins>" % eachDiff[1:].strip()
        else:
            diff_html += eachDiff[1:].strip()

        diff_html += "\n"

    return diff_html


#
# Babel
#
@babel.localeselector
def get_locale():
    if current_user.is_authenticated:
        return current_user.locale
    return request.accept_languages.best_match(['sv', 'es', 'de', 'fr', 'en'])


def create_db_tables():
    database.create_tables([Comment, User, Community, CommunityUser, Proposal,
                            CommentVote, PostVote, Moderator, Tag, PostHistory,
                            PostInternalVote])


def site_map():
    def has_no_empty_params(rule):
        defaults = rule.defaults if rule.defaults is not None else ()
        arguments = rule.arguments if rule.arguments is not None else ()
        return len(defaults) >= len(arguments)

    links = []
    for rule in current_app.url_map.iter_rules():
        # Filter out rules we can't navigate to in a browser
        # and rules that require parameters
        if "GET" in rule.methods and has_no_empty_params(rule):
            url = url_for(rule.endpoint, **(rule.defaults or {}))
            links.append((url, rule.endpoint))

    return links


login_manager.init_app(app)

if __name__ == '__main__':
    if "--setup" in sys.argv:
        create_db_tables()
        print(gettext("Database tables created"))

    elif "--sitemap" in sys.argv:
        with app.app_context():
            for item in site_map():
                print(item)
    else:
        app.run(host='0.0.0.0', port=8780, debug=True, threaded=True)
