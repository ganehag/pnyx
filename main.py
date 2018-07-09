#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import os.path
import json
import logging
import logging.config
import sys
import hashlib
import math

import yaml

from urllib.parse import urlparse, urljoin, urlencode


from flask import (Flask, abort, flash, Markup, redirect, render_template,
                   request, Response, session, url_for, jsonify)
from flask_assets import Environment, Bundle

from flask_login import (
    LoginManager, current_user,
    login_required, login_user, logout_user
)

from form import LoginForm, RegisterForm, CommunityCreateForm

import peewee

from playhouse.flask_utils import FlaskDB, get_object_or_404, object_list
from playhouse.shortcuts import model_to_dict, dict_to_model

from models import (Comment, AnonymousUser, User, Community, CommunityUser, 
    Proposal, CommentVote, PostVote, db)

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
                config = yaml.load(cfg.read())
                if config:
                    break

        except IOError as e:
            print(e)

        except Exception as e:
            print("No configuration", e)

    app = Flask(__name__)
    app.config.from_mapping(config.get(config.get('instance')))
    logging.config.dictConfig(config.get(config.get('instance')).get('logging', {}))
    return app


app = create_app("config.yaml")

login_manager = LoginManager()
login_manager.login_view = "login"

assets = Environment(app)
# assets.auto_build = False
css = Bundle('css/bootstrap_pnyx.min.css', 'css/select2-bootstrap4.min.css', 'css/pnyx.css',
            # filters='cssmin',
            output='gen/screen.css')
assets.register('css_all', css)

db.init_app(app)
database = db.database

@app.route('/submit_comment', methods=['POST'])
def submit_comment():
    comment = Comment()

    content = request.form.get('content')
    slug = request.form.get('slug')
    user = User.get(User.id == current_user.id)
    root = request.form.get('parent') or None

    if not(content and slug and user):
        flash('Missing content or reference to Post')
        return redirect(url_for('index'))

    else:
        comment.post = Proposal.get(Proposal.slug == slug)

        if root is not None and not (Comment.get(Comment.id == root).post == comment.post):
            flash('Invalid comment reference')
            return redirect(url_for('detail', slug=slug, community=comment.post.community.name))
        else:
            comment.content = content
            comment.user = user
            comment.root = root

            try:
                with database.atomic():
                    comment.save()

            except peewee.IntegrityError as e:
                flash('Unable to save comment', 'error')

            else:
                return redirect(url_for('detail', slug=slug, community=comment.post.community.name))
                

    return redirect(url_for('detail', slug=slug, community=comment.post.community))


@app.route('/submit', methods=['GET', 'POST'])
@app.route('/c/<community>/submit', methods=['GET', 'POST'])
@app.route('/u/<user>/submit', methods=['GET', 'POST'])
@login_required
def submit(user=None, community=None):
    entry = Proposal(community='', title='', content='')

    if community is None:
        community = request.form.get('community') or None
        if community and community[0:2] == "c/":
            community = community[2:]

    if request.method == 'POST':
        try:
            entry.title = request.form.get('title') or ''
            entry.content = request.form.get('content') or ''
            entry.published = request.form.get('published') or True  # default to published
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

                except peewee.IntegrityError as e:
                    print(e)
                    flash('This title is already in use.', 'error')
                else:

                    if entry.published:
                        return redirect(url_for('detail', community=entry.community.name, slug=entry.slug))
                    else:
                        return 404

        except peewee.DoesNotExist:
            flash('Community and Title are required.', 'error')
        
    if community is not None:
        community = Community.get_or_none(Community.name == community)

    return render_template('submit.html', entry=entry, community=community)

@app.route('/u/<user>', methods=["GET", "POST"])
def user_page(user):
    u = get_object_or_404(User, User.username == user)
    query = u.posts.order_by(Proposal.timestamp.desc())

    return object_list(
        'user.html',
        query,
        user=u,
        check_bounds=False)

@app.route('/u/<user>/karma', methods=['GET'])
def user_karma(user):
    u = get_object_or_404(User, User.username == user)
    return str(u.karma_count), 200

@app.route('/u/subscribe/<community>', methods=['GET'])
@login_required
def community_subscribe(community):
    fu = CommunityUser(community=Community.get(Community.name == community), user=User.get(User.id == current_user.id))

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
def community(community):
    community_ref = Community.get_or_none(Community.name == community)
    return object_list('index.html',
        Proposal.from_community(community_ref).order_by(Proposal.timestamp.desc()),
        community=community_ref,
        check_bounds=False)

@app.route('/c/<community>/<slug>')
def detail(community, slug):
    query = Proposal.public()
    community_id = Community.get_or_none(Community.name == community)
    entry = get_object_or_404(query, Proposal.slug == slug, Proposal.community == community_id)
    return render_template('detail.html', entry=entry, community=community_id)

@app.route('/community/create', methods=['GET', 'POST'])
@login_required
@database.atomic()
def community_create():
    form = CommunityCreateForm()

    if form.validate_on_submit() and current_user.karma >= 50:
        community = Community()
        community.name = form.name.data
        community.description = form.description.data
        community.maintainer = User.get(User.id == current_user.id)

        community.update_search_index()

        user = User.get(User.id == current_user.id)
        user.karma -= 50
        user.save()

        try:
            community.save()

        except peewee.IntegrityError as e:
            print(e)
            flash('This name is already in use.', 'error')

        else:
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
        {"id": "", "text": "Home"},
        {"id": "c/popular", "text": "Popular"},
        {"id": "c/new", "text": "New"},
        {"id": "c/upvote", "text": "Most upvoted"}
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
        rowcount = PostVote.delete().where((PostVote.post == prop) & (PostVote.user_id == current_user.id)).execute()
        result["diff"] = '-1'
    else:
        score_mod = 1
        if current_user.has_downvoted(prop):
            score_mod = 2

        result["diff"] = '+' + str(score_mod)
        prop.upvotes += score_mod
        # current_user.karma -= 1
        prop.author.karma += 1

        rowid = (PostVote
         .insert(post=prop, user=current_user.id, vote=1)
         .on_conflict(
             conflict_target=[PostVote.user,PostVote.post],
             preserve=[PostVote.vote,PostVote.timestamp])
         .execute())
    
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
        rowcount = PostVote.delete().where((PostVote.post == prop) & (PostVote.user_id == current_user.id)).execute()
        result["diff"] = '+1'

    else:
        # current_user.karma -= 1
        prop.author.karma -= 1
        score_mod = 1
        if current_user.has_upvoted(prop):
            score_mod = 2
        result["diff"] = str(-score_mod)
        prop.downvotes += score_mod
        

        rowid = (PostVote
         .insert(post=prop, user=current_user.id, vote=-1)
         .on_conflict(
             conflict_target=[PostVote.user,PostVote.post],
             preserve=[PostVote.vote,PostVote.timestamp])
         .execute())

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
        rowcount = CommentVote.delete().where(
            (CommentVote.comment == comment) & (CommentVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '-1'
    else:
        # current_user.karma -= 1
        score_mod = 1
        if current_user.has_downvoted(comment):
            score_mod = 2

        comment.score += score_mod
        
        result["diff"] = '+' + str(score_mod)

        rowid = (CommentVote
         .insert(comment=comment, user=current_user.id, vote=1)
         .on_conflict(
             conflict_target=[CommentVote.user,CommentVote.comment],
             preserve=[CommentVote.vote,CommentVote.timestamp])
         .execute())

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
        rowcount = CommentVote.delete().where(
            (CommentVote.comment == comment) & (CommentVote.user_id == current_user.id)
        ).execute()
        result["diff"] = '+1'
    else:
        score_mod = 1
        if current_user.has_upvoted(comment):
            score_mod = 2
        result["diff"] = str(-score_mod)

        comment.score -= score_mod
        # current_user.karma -= 1

        rowid = (CommentVote
         .insert(comment=comment, user=current_user.id, vote=-1)
         .on_conflict(
             conflict_target=[CommentVote.user,CommentVote.comment],
             preserve=[CommentVote.vote,CommentVote.timestamp])
         .execute())

    Comment.save(comment)
    # FIXME move karma to another table
    User.save(current_user)

    result["score"] = str(comment.score)

    return jsonify(result)


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
            user = User.get(User.username == form.username.data, User.password == shasum)
        except peewee.DoesNotExist:
            flash("Invalid username or password", "error")
            return redirect(url_for('login'))

        login_user(user)

        flash('Logged in successfully.')

        return form.redirect('index')

    return render_template('login.html', form=form, next=request.args.get('next'))


@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()

    if form.validate_on_submit():
        user = User()
        user.email = form.email.data
        user.username = form.username.data
        user.password = hashlib.sha384(form.password.data.encode()).hexdigest()

        try:
            with database.atomic():
                user.save()

        except peewee.IntegrityError as e:
            flash('This username/email is already in use.', 'error')

        else:
            login_user(user)
            return form.redirect('index')

    return render_template('register.html', form=form)


#
# Misc
#

@app.route('/c/upvote')
@app.route('/c/popular')
@app.route('/c/new')
@app.route('/')
def index():
    query = Proposal.public()

    # FIXME: better sorting

    community = None

    if request.path == "/c/popular":
        query = query.order_by(-Proposal.ranking)
        community = Community(name="popular", description="The most popular posts on Pnyx.")

    elif request.path == "/c/upvote":
        query = query.order_by(-(Proposal.upvotes - Proposal.downvotes))
        community = Community(name="upvote", description="The most upvoted posts on Pnyx.")

    elif request.path == "/c/new":
        query = query.order_by(Proposal.timestamp.desc())
        community = Community(name="new", description="The newest posts from all of Pnyx. Come here to see posts rising and be a part of the conversation..")

    else:
        query = query.order_by(-Proposal.ranking, Proposal.timestamp.desc())

    return object_list(
        'index.html',
        query,
        community=community,
        check_bounds=False)

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

        except (peewee.InternalError, peewee.IntegrityError, peewee.ProgrammingError):
            # flash("Invalid query '{0}'".format(search_query), 'error')
            pass

    return render_template('search.html', search=search_query, pagination=None)

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

@app.errorhandler(404)
def not_found(exc):
    return render_template('404.html'), 404


login_manager.init_app(app)

if __name__ == '__main__':
    if "--setup" in sys.argv:
        # with app.app_context():
        #     db.create_all()
        #     db.session.commit()
        # with database:
        database.create_tables([Comment, User, Community, CommunityUser, Proposal, CommentVote, PostVote])
        print("Database tables created")
    else:
        app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)
