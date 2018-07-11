# -*- coding: utf-8 -*-

import collections
import datetime
import re
import os.path


from flask import Markup
from flask_login import current_user

from markdown import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.extra import ExtraExtension

from playhouse.flask_utils import FlaskDB
from playhouse.hybrid import hybrid_property
from playhouse.postgres_ext import *

from peewee import *
import peewee

db = FlaskDB()


# forward declaration
class Comment(db.Model):
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
        ).join(CommunityUser).where(CommunityUser.user_id == self.id).order_by(Community.name)
    
    @property
    def newest_posts(self):
        return self.posts.order_by(Proposal.timestamp.desc()).limit(10)
    

    def has_upvoted(self, item):
        if isinstance(item, Proposal):
            return PostVote.select().where(
                (PostVote.post == item) & (PostVote.user == self) & (PostVote.vote > 0)
            ).count() > 0

        elif isinstance(item, Comment):
            return CommentVote.select(CommentVote.id).where(
                (CommentVote.comment == item) & (CommentVote.user == self) & (CommentVote.vote > 0)
            ).count() > 0
        
        return None

    def has_downvoted(self, item):
        if isinstance(item, Proposal):
            return PostVote.select().where(
                (PostVote.post == item) & (PostVote.user == self) & (PostVote.vote < 0)
            ).count() > 0

        elif isinstance(item, Comment):
            return CommentVote.select().where(
                (CommentVote.comment == item) & (CommentVote.user == self) & (CommentVote.vote < 0)
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
        ret = super(Community, self).save(*args, **kwargs)
        self.update_search_index()
        return ret

    def update_search_index(self):
        search_content = '\n'.join((self.name, self.description))
        self.search_content = fn.to_tsvector(search_content)

    @hybrid_property
    def prefix_name(self):
        return fn.CONCAT("c/", self.name)

    @property
    def user_count(self):
        num = CommunityUser.select().where(CommunityUser.community == self).count()
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
            CommunityUser.user_id == current_user.id, CommunityUser.community_id == self.id
        ) is not None

    @classmethod
    def search(cls, query):
        return Community.select(
            Community,
            fn.COUNT(CommunityUser.community_id).alias('sub_count')
        ).join(CommunityUser).where(Community.search_content.match(query.replace(' ', '|'))).group_by(Community).order_by(SQL('sub_count'))

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


    def save(self, *args, **kwargs):
        # Generate a URL-friendly representation of the entry's title.
        if not self.slug:
            self.slug = re.sub('[^\w]+', '-', self.title.lower()).strip('-')
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
                   1.96 * math.sqrt((self.upvotes * self.downvotes) / (self.upvotes + self.downvotes) + 0.9604) / 
                          (self.upvotes + self.downvotes)) / (1 + 3.8416 / (self.upvotes + self.downvotes))
        except ZeroDivisionError:
            return 0

    @hybrid_property
    def ranking(self):
        upvotes = self.upvotes
        downvotes = self.downvotes

        if self.upvotes + self.downvotes == 0:
            return self.upvotes

        return ((upvotes + 1.9208) / (upvotes + downvotes) - 
               1.96 * fn.SQRT((upvotes * downvotes) / (upvotes + downvotes) + 0.9604) / 
                      (upvotes + downvotes)) / (1 + 3.8416 / (upvotes + downvotes))

    @classmethod
    def search(cls, query):
        match_filter = Expression(Proposal.search_content, TS_MATCH, fn.plainto_tsquery(query))
        return Proposal.select().where((Proposal.published == True) & match_filter)

    @classmethod
    def from_community(cls, community):
        return Proposal.select().where(Proposal.published == True, Proposal.community == community)

    @classmethod
    def public(cls):
        return Proposal.select().where(Proposal.published == True)

    @classmethod
    def drafts(cls):
        return Proposal.select().where(Proposal.published == False)

    @property
    def comment_count(self):
        return Comment.select().where(Comment.post_id == self.id).count()

    @property
    def comments(self):
        Base = Comment.alias()
        level = Value(1).alias('level')

        path = Base.id.cast('text').alias('path')

        base_case = (Base
             .select(Base.id, Base.post, Base.user, Base.root, Base.timestamp, Base.score, Base.content, level, path)
             .where(Base.root.is_null())
             .cte('base', recursive=True))

        RTerm = Comment.alias()
        rlevel = (base_case.c.level + 1).alias('level')
        rpath = base_case.c.path.concat('/').concat(RTerm.id).alias('path')

        recursive = (RTerm
             .select(RTerm.id, RTerm.post, RTerm.user, RTerm.root, RTerm.timestamp, RTerm.score, RTerm.content, rlevel, rpath)
             # .where(RTerm.post_id == self.id)
             .join(base_case, on=(RTerm.root == base_case.c.id)))

        cte = base_case.union_all(recursive)

        query = (cte
         .select_from(cte.c.id, cte.c.user_id, User.username, cte.c.timestamp, cte.c.score, cte.c.content, cte.c.level, cte.c.path)
         .join(User, on=(User.id == cte.c.user_id))
         .where(cte.c.post_id == self.id)
         .order_by(cte.c.path, cte.c.timestamp))

        def resolve_comment(path, comment, base):
            if os.path.dirname(path) == '':
                base[comment.id] = {
                    'id': comment.id,
                    'username': comment.username,
                    'user_id': comment.user_id,
                    'timestamp': comment.timestamp,
                    'score': comment.score,
                    'content': comment.content,
                    'comments': collections.OrderedDict()
                }
            else:
                resolve_comment(os.path.dirname(path), comment, base[int(os.path.basename(path))]['comments'])

        comment_dict = collections.OrderedDict()
        for com in query:
            rpath = "/".join(com.path.split('/')[::-1])
            resolve_comment(rpath, com, comment_dict)

        def recursive_sort_dict(items):
            items = collections.OrderedDict(sorted(items.items(), reverse=True, key=lambda x: (x[1]['score'], x[1]['timestamp'])))
            for key, item in items.items():
                if item['comments']:
                    item['comments'] = recursive_sort_dict(item['comments'])
            return items

        sorted_dict = recursive_sort_dict(comment_dict)

        return sorted_dict


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