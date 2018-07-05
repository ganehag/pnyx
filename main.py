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
                   request, Response, session, url_for)
from werkzeug.contrib.fixers import ProxyFix

from flask_login import (
    LoginManager, current_user,
    login_required, login_user, logout_user
)

from form import LoginForm, RegisterForm

import peewee


from playhouse.flask_utils import FlaskDB, get_object_or_404, object_list
from playhouse.shortcuts import model_to_dict, dict_to_model



from models import (Comment, AnonymousUser, User, Forum, ForumUser, 
    Proposal, db)

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
app.wsgi_app = ProxyFix(app.wsgi_app)

login_manager = LoginManager()
login_manager.login_view = "login"


db.init_app(app)
database = db.database

@login_manager.user_loader
def load_user(user_id):
    user = User.get_or_none(User.id == int(user_id))
    if user is None:
        return AnonymousUser()
    return user

@app.route('/')
def index():
    query = Proposal.public().order_by(-Proposal.ranking, Proposal.timestamp.desc())

    # The `object_list` helper will take a base query and then handle
    # paginating the results if there are more than 20. For more info see
    # the docs:
    # http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#object_list
    return object_list(
        'index.html',
        query,
        forum=None,
        check_bounds=False)

@app.route('/search')
def search():
    search_query = request.args.get('q').strip()

    if search_query:
        try:
            post_query = Proposal.search(search_query)
            forum_query = Forum.search(search_query)

            return object_list(
                'search.html',
                post_query,
                forums=forum_query,
                search=search_query,
                check_bounds=False)

        except (peewee.InternalError, peewee.IntegrityError, peewee.ProgrammingError):
            # flash("Invalid query '{0}'".format(search_query), 'error')
            pass

    return render_template('search.html', search=search_query, pagination=None)

@app.route('/c/<forum>')
def forum(forum):
    # search_query = request.args.get('q')
    forum_ref = Forum.get_or_none(Forum.name == forum)
    return object_list('index.html',
        Proposal.from_forum(forum_ref).order_by(Proposal.timestamp.desc()),
        forum=forum_ref,
        # search=search_query,
        check_bounds=False
    )


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
            return redirect(url_for('detail', slug=slug, forum=comment.post.forum.name))
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
                return redirect(url_for('detail', slug=slug, forum=comment.post.forum.name))
                

    return redirect(url_for('detail', slug=slug, forum=comment.post.forum))


@app.route('/submit', methods=['GET', 'POST'])
@app.route('/c/<forum>/submit', methods=['GET', 'POST'])
@app.route('/u/<user>/submit', methods=['GET', 'POST'])
@login_required
def submit(user=None, forum=None):
    entry = Proposal(forum='', title='', content='')

    if forum is None:
        forum = request.form.get('forum') or None
        if forum and forum[0:2] == "c/":
            forum = forum[2:]

    if request.method == 'POST':
        try:
            entry.title = request.form.get('title') or ''
            entry.content = request.form.get('content') or ''
            entry.published = request.form.get('published') or True  # default to published
            entry.author = User.get(User.id == current_user.id)
            entry.forum = Forum.get(Forum.name == forum)

            if not (entry.title and entry.forum and entry.author):
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
                        return redirect(url_for('detail', forum=entry.forum.name, slug=entry.slug))
                    else:
                        return 404

        except peewee.DoesNotExist:
            flash('Community and Title are required.', 'error')
        
    if forum is not None:
        forum = Forum.get_or_none(Forum.name == forum)

    return render_template('submit.html', entry=entry, forum=forum)

@app.route('/u/<user>/gold', methods=['GET'])
def user_gold(user):
    u = get_object_or_404(User, User.username == user)
    return str(u.gold_count), 200

# @app.route('/drafts/')
# def drafts():
#    query = Proposal.drafts().order_by(Proposal.timestamp.desc())
#    return object_list('index.html', query, check_bounds=False)

@app.route('/c/<forum>/<slug>')
def detail(forum, slug):
    query = Proposal.public()
    forum_id = Forum.get_or_none(Forum.name == forum)
    entry = get_object_or_404(query, Proposal.slug == slug, Proposal.forum == forum_id)
    return render_template('detail.html', entry=entry, forum=forum_id)


@app.route('/p/upvote/<slug>', methods=['GET'])
@login_required
def proposal_upvote(slug):
    prop = Proposal.get(Proposal.slug == slug)

    if current_user.id == prop.user_id or current_user.gold <= 0:
        return str(prop.votes), 200

    prop.upvotes += 1
    Proposal.save(prop)
    prop.author.gold += 5
    User.save(prop.author)

    current_user.gold -= 1
    User.save(current_user)

    return str(prop.votes), 200

@app.route('/p/downvote/<slug>', methods=['GET'])
@login_required
def proposal_downvote(slug):
    prop = Proposal.get(Proposal.slug == slug)

    if current_user.id == prop.author_id or current_user.gold <= 0:
        return str(prop.votes), 200

    prop.downvotes += 1
    Proposal.save(prop)

    current_user.gold -= 1
    User.save(current_user)

    return str(prop.votes), 200

@app.route('/p/upvote/<slug>/<comment_id>', methods=['GET'])
@login_required
def comment_upvote(slug, comment_id):
    # Ensure comment belongs to slug
    # prop = Proposal.get(Proposal.slug == slug)
    comment = Comment.get(Comment.id == comment_id)

    if current_user.gold <= 0:
        return str(comment.score), 200

    comment.score += 1
    Comment.save(comment)

    current_user.gold -= 1
    User.save(current_user)

    return str(comment.score), 200

@app.route('/p/downvote/<slug>/<comment_id>', methods=['GET'])
@login_required
def comment_downvote(slug, comment_id):
    # Ensure comment belongs to slug
    # prop = Proposal.get(Proposal.slug == slug)
    # prop.downvotes += 1
    comment = Comment.get(Comment.id == comment_id)

    if current_user.gold <= 0:
        return str(comment.score), 200

    comment.score -= 1
    Comment.save(comment)

    current_user.gold -= 1
    User.save(current_user)

    return str(comment.score), 200

@app.route('/u/subscribe/<forum>', methods=['GET'])
@login_required
def forum_subscribe(forum):
    fu = ForumUser(forum=Forum.get(Forum.name == forum), user=User.get(User.id == current_user.id))

    try:
        with database.atomic():
            fu.save()
    except peewee.IntegrityError as e:
        print(e)

    else:
        return redirect(url_for("forum", forum=forum))

    # flash error message

    return redirect(url_for("forum", forum=forum))

@app.route('/community/search', methods=['GET'])
def community_search():
    search_query = request.args.get('query')

    hits = [model_to_dict(hit, recurse=True) for hit in Forum.select().where(Forum.prefix_name.contains(search_query)).order_by(Forum.name)]
    for hit in hits:
        hit['name'] = "c/" + hit['name']
        hit['id'] = str(hit['id'])

    return json.dumps({"suggestions": hits})

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

@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
    querystring = dict((key, value) for key, value in request_args.items())
    for key in keys_to_remove:
        querystring.pop(key, None)
    querystring.update(new_values)
    return urlencode(querystring)

@app.errorhandler(404)
def not_found(exc):
    return Response('<h3>Not found</h3>'), 404


login_manager.init_app(app)

if __name__ == '__main__':
    if "--setup" in sys.argv:
        # with app.app_context():
        #     db.create_all()
        #     db.session.commit()
        # with database:
        database.create_tables([Comment, User, Forum, ForumUser, Proposal])
        print("Database tables created")
    else:
        app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)
