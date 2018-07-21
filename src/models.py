# -*- coding: utf-8 -*-

import collections
import datetime
import re
import os.path
import time

import hashlib

from slugify import slugify

from flask import Markup, current_app
from flask_login import current_user

from itertools import islice

from markdown import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.extra import ExtraExtension

from playhouse.flask_utils import FlaskDB
from playhouse.hybrid import hybrid_property
from playhouse.postgres_ext import *

from peewee import *
import peewee

db = FlaskDB()


#
# Forward declarations
#
class Comment(db.Model):
    pass


class Proposal(db.Model):
    pass


class AnonymousUser():
    username = "Anonymous"
    password = ""
    karma = 0

    @property
    def id(self):
        return None

    @property
    def is_authenticated(self):
        return False

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return True

    @property
    def karma_count(self):
        return 0

    @property
    def locale(self):
        return None

    def get_id(self):
        return 0


class User(db.Model):
    email = CharField(unique=True)
    username = CharField(unique=True)
    password = CharField()
    karma = IntegerField(default=100)
    cake_day = DateTimeField(default=datetime.datetime.now)

    _is_active = True
    _is_anonymous = False
    _is_authenticated = True

    @property
    def locale(self):
        return None

    @property
    def is_authenticated(self):
        return self._is_authenticated

    @property
    def is_active(self):
        return self._is_active

    @property
    def is_anonymous(self):
        return self._is_anonymous

    @property
    def username_with_prefix(self):
        return "u/" + self.username

    @property
    def karma_count(self):
        num = self.karma
        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0
        if magnitude == 0:
            return '%i' % num
        return '%.1f%s' % (num, ['', 'K', 'M', 'G', 'T', 'P'][magnitude])

    @property
    def subscriptions(self):
        return Community.select(
            Community.id,
            Community.name,
            Community.description
        ).join(CommunityUser).where(CommunityUser.user_id == self.id).order_by(
            Community.name)

    @property
    def newest_posts(self):
        return self.posts.order_by(Proposal.timestamp.desc()).limit(10)

    def has_upvoted(self, item):
        if isinstance(item, Proposal):
            return PostVote.select().where(
                (PostVote.post == item) &
                (PostVote.user == self) &
                (PostVote.vote > 0)
            ).count() > 0

        elif isinstance(item, Comment):
            return CommentVote.select(CommentVote.id).where(
                (CommentVote.comment == item) &
                (CommentVote.user == self) &
                (CommentVote.vote > 0)
            ).count() > 0

        return None

    def has_downvoted(self, item):
        if isinstance(item, Proposal):
            return PostVote.select().where(
                (PostVote.post == item) &
                (PostVote.user == self) &
                (PostVote.vote < 0)
            ).count() > 0

        elif isinstance(item, Comment):
            return CommentVote.select().where(
                (CommentVote.comment == item) &
                (CommentVote.user == self) &
                (CommentVote.vote < 0)
            ).count() > 0

        return None

    def get_id(self):
        return self.id


class Community(db.Model):
    name = CharField(unique=True)
    description = CharField()
    maintainer = ForeignKeyField(User, backref='community_maintainer')

    search_content = TSVectorField()

    def save(self, *args, **kwargs):
        # FIXME:
        # Ensure "name" has a correct format.
        self.update_search_index()
        ret = super(Community, self).save(*args, **kwargs)
        return ret

    def update_search_index(self):
        search_content = '\n'.join((self.name, self.description))
        self.search_content = fn.to_tsvector(search_content)

    @hybrid_property
    def prefix_name(self):
        return fn.CONCAT("c/", self.name)

    @property
    def user_count(self):
        num = CommunityUser.select().where(
            CommunityUser.community == self).count()
        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0

        if magnitude == 0:
            return '%i' % num

        return '%.1f%s' % (num, ['', 'K', 'M', 'G', 'T', 'P'][magnitude])

    @property
    def name_with_prefix(self):
        return "c/" + self.name

    @property
    def current_user_subscribed(self):
        return CommunityUser.get_or_none(
            CommunityUser.user_id == current_user.id,
            CommunityUser.community_id == self.id
        ) is not None

    @classmethod
    def search(cls, query):
        return Community.select(
            Community,
            fn.COUNT(CommunityUser.community_id).alias('sub_count')
        ).join(CommunityUser, JOIN.LEFT_OUTER).where(
            Community.search_content.match(query.replace(' ', '|'))
        ).group_by(Community).order_by(SQL('sub_count'))

    @classmethod
    def rgbcolor(cls, name):
        d = [int(x) for x in hashlib.md5(name).digest()]
        return "rgb({0}, {1}, {2})".format(
                sum(d[0:5]) % 256,
                sum(d[5:10]) % 256,
                sum(d[10:16]) % 256
            )

    def __str__(self):
        r = {}
        for k in self._data.keys():
            try:
                r[k] = str(getattr(self, k))
            except:
                r[k] = json.dumps(getattr(self, k))
        return str(r)


class CommunityUser(db.Model):
    community = ForeignKeyField(Community, backref='subscribers')
    user = ForeignKeyField(User)

    class Meta:
        indexes = (
            (("community_id", "user_id"), True),
        )


class PostHistory(db.Model):
    post = ForeignKeyField(Proposal)
    timestamp = DateTimeField(default=datetime.datetime.now)
    content = TextField()

    @hybrid_property
    def rev(self):
        return fn.row_number().over(
            order_by=[PostHistory.timestamp]).alias('revision')


class Proposal(db.Model):
    community = ForeignKeyField(Community, backref='posts')
    title = CharField()
    slug = CharField(unique=True)
    author = ForeignKeyField(User, backref='posts')
    content = TextField()
    search_content = TSVectorField()

    published = BooleanField(index=True)

    upvotes = IntegerField(default=0)
    downvotes = IntegerField(default=0)
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    modified = DateTimeField(default=None, null=True)

    @classmethod
    def all(cls):  # Except search content
        return Proposal.select(Proposal.id,
                               Proposal.community,
                               Proposal.title,
                               Proposal.slug,
                               Proposal.author,
                               Proposal.content,
                               Proposal.published,
                               Proposal.upvotes,
                               Proposal.downvotes,
                               Proposal.timestamp,
                               Proposal.modified)

    def save(self, *args, **kwargs):
        # Generate a URL-friendly representation of the entry's title.
        if not self.slug:
            self.slug = slugify(self.title)
        ret = super(Proposal, self).save(*args, **kwargs)

        # Store search content.
        self.update_search_index()
        return ret

    def update_search_index(self):
        search_content = '\n'.join((self.title, self.content))
        self.search_content = fn.to_tsvector(search_content)

    @property
    def community_name(self):
        if self.community is None:
            return ''
        return Community.get_or_none(Community.id == self.community)

    @property
    def html_content(self):
        hilite = CodeHiliteExtension(linenums=False, css_class='highlight')
        extras = ExtraExtension()
        markdown_content = markdown(self.content, extensions=[hilite, extras])
        # oembed_content = parse_html(
        #     markdown_content,
        #     oembed_providers,
        #     urlize_all=True,
        #     maxwidth=app.config['SITE_WIDTH'])
        return Markup(markdown_content)

    @property
    def votes(self):
        num = self.upvotes - self.downvotes

        magnitude = 0
        while abs(num) >= 1000:
            magnitude += 1
            num /= 1000.0

        if magnitude == 0:
            return '%i' % num

        return '%.1f%s' % (num, ['', 'K', 'M', 'G', 'T', 'P'][magnitude])

    @property
    def vote_percent(self):
        total = self.upvotes + self.downvotes
        if total == 0:
            return "0% Upvoted"

        up_perc = self.upvotes / float(total)
        down_perc = self.downvotes / float(total)

        if up_perc >= down_perc:
            return "{0:.0f}% Upvoted".format(up_perc * 100)

        return "{0:.0f}% Downvoted".format(down_perc * 100)

    @property
    def rank(self):
        try:
            return ((self.upvotes + 1.9208) / (self.upvotes + self.downvotes) -
                    1.96 * math.sqrt(
                        (self.upvotes * self.downvotes)
                        / (self.upvotes + self.downvotes)
                        + 0.9604) / (self.upvotes + self.downvotes)
                    ) / (1 + 3.8416 / (self.upvotes + self.downvotes))
        except ZeroDivisionError:
            return 0

    @hybrid_property
    def ranking(self):
        upvotes = self.upvotes
        downvotes = self.downvotes

        if self.upvotes + self.downvotes == 0:
            return self.upvotes

        return ((upvotes + 1.9208) / (upvotes + downvotes) -
                1.96 * fn.SQRT((upvotes * downvotes)
                / (upvotes + downvotes) + 0.9604) /
                (upvotes + downvotes)) / (1 + 3.8416 / (upvotes + downvotes))

    @classmethod
    def search(cls, query):
        match_filter = Expression(
            Proposal.search_content, TS_MATCH, fn.plainto_tsquery(query))
        return Proposal.select().where(
            (Proposal.published == True) & match_filter)

    @classmethod
    def from_community(cls, community):
        return Proposal.select().where(
            Proposal.published == True, Proposal.community == community)

    @classmethod
    def public(cls):
        return Proposal.all().where(Proposal.published == True)

    @classmethod
    def drafts(cls):
        return Proposal.all().where(Proposal.published == False)

    @property
    def comment_count(self):
        return Comment.select().where(Comment.post_id == self.id).count()

    def comments(self, show_all=False):
        def resolve_comment(path, base):
            if os.path.dirname(path) == '':
                comment = comment_dict[int(os.path.basename(path))]
                base[comment['id']] = {
                    'id': comment['id'],
                    'username': comment['username'],
                    'user_id': comment['user_id'],
                    'timestamp': comment['timestamp'],
                    'score': comment['score'],
                    'content': comment['content'],
                    'comments': collections.OrderedDict()
                }
            else:
                resolve_comment(os.path.dirname(path),
                                base[int(os.path.basename(path))]['comments'])

        def recursive_sort_dict(items, limit=None):
            items = collections.OrderedDict(
                sorted(items.items(),
                       reverse=True,
                       key=lambda x: (x[1]['score'], x[1]['timestamp'])))

            for key, item in items.items():
                if item['comments'] and (limit is None or limit > 0):
                    # if limit is None or limit > 0:
                    limit, item['comments'] = recursive_sort_dict(
                        item['comments'], limit)

            if limit is not None:
                if limit - len(items) <= 0:
                    return -1, collections.OrderedDict(
                        islice(items.items(), self.LOAD_LIMIT))
                limit -= len(items)
            return limit, items

        Base = Comment.alias()
        level = Value(1).alias('level')
        path = Base.id.cast('text').alias('path')

        base_case = (Base.select(
                Base.id, Base.post, Base.root, level, path
            ).where(
                (Base.root.is_null()) & (Base.post == self)
            ).cte('base', recursive=True))

        RTerm = Comment.alias()
        rlevel = (base_case.c.level + 1).alias('level')
        rpath = base_case.c.path.concat('/').concat(RTerm.id).alias('path')

        recursive = (RTerm.select(
                RTerm.id, RTerm.post, RTerm.root, rlevel, rpath
            ).where(RTerm.post_id == self.id)
             .join(base_case, on=(RTerm.root == base_case.c.id)))

        cte = base_case.union_all(recursive)

        query = (cte.select_from(
                cte.c.id, cte.c.level, cte.c.path
            ).where(cte.c.post_id == self.id)
             .order_by(cte.c.path))

        c_query = Comment.select(
                Comment.id, Comment.user_id, Comment.score,
                Comment.timestamp, Comment.content, User.username
            ).join(User).where(Comment.post == self).order_by(Comment.id)
        cursor = db.database.execute(c_query)
        comment_dict = {id: {
            'id': id,
            'username': username,
            'user_id': user_id,
            'timestamp': ts,
            'score': score,
            'content': content
        } for id, user_id, score, ts, content, username in cursor}

        comment_dict_res = collections.OrderedDict()
        for item in query:
            rpath = "/".join(item.path.split('/')[::-1])
            resolve_comment(rpath, comment_dict_res)

        if not show_all:
            _, sorted_dict = recursive_sort_dict(
                comment_dict_res, self.LOAD_LIMIT)
        else:
            _, sorted_dict = recursive_sort_dict(comment_dict_res)

        return sorted_dict

    @property
    def num_remaining_comments(self):
        return self.comment_count - self.LOAD_LIMIT

    @property
    def LOAD_LIMIT(self):
        return 50

    @property
    def history(self):
        return PostHistory.select(PostHistory.timestamp,
                                  PostHistory.content,
                                  PostHistory.rev
                                  ).where(
                                    PostHistory.post == self
                                  ).order_by(SQL('revision').desc())

    @property
    def history_skip_latest(self):
        return self.history.offset(1)


class Comment(db.Model):
    post = ForeignKeyField(Proposal)
    user = ForeignKeyField(User)
    root = ForeignKeyField('self', backref='children', null=True, default=None)
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    score = IntegerField(default=0)
    content = TextField()


class CommentVote(db.Model):
    comment = ForeignKeyField(Comment)
    user = ForeignKeyField(User)
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    vote = IntegerField(default=0)

    class Meta:
        indexes = (
            (('comment', 'user'), True),
        )


class PostVote(db.Model):
    post = ForeignKeyField(Proposal)
    user = ForeignKeyField(User)
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    vote = IntegerField(default=0)

    class Meta:
        indexes = (
            (('post', 'user'), True),
        )


class Moderator(db.Model):
    user = ForeignKeyField(User)
    community = ForeignKeyField(Community)

    class Meta:
        indexes = (
            (('user', 'community'), True),
        )


class Tag(db.Model):
    title = CharField()
    community = ForeignKeyField(Community)

    class Meta:
        indexes = (
            (('title', 'community'), True),
        )

    @classmethod
    def unique(cls):
        return (Tag.select(
                    Tag.title,
                    fn.COUNT(Tag.id))
                .group_by(Tag.title)
                .order_by(-fn.COUNT(Tag.id)))

    @classmethod
    def communities(cls):
        return (Tag.select(
                        Tag.title.alias('tag_title'),
                        Community.name.alias('community_name'),
                        fn.COUNT(Proposal.id).alias('post_count')
                )
                .join(Community)
                .join(Proposal)

                .group_by(Tag.title, Community.name)
                .order_by(Tag.title, Community.name)
                .objects())

