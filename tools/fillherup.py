#!/usr/bin/python3
import sys
import os

import peewee

sys.path.insert(1, os.path.join(sys.path[0], '../src'))

from faker import Faker
from main import database, db, Proposal, User, Community, Comment

import random

from peewee import fn

fake = Faker('sv_SE')

def get_random_comment(proposal=None):
    query = Comment.select(Comment.id, Comment.post)
    if proposal is not None:
        query = query.where(Comment.post == proposal)
    query = query.order_by(fn.Random())
    return query.get()

def get_random_post():
    return Proposal.select(Proposal.id).order_by(fn.Random()).get()

def get_random_user():
    return User.select(User.id).order_by(fn.Random()).get()

def get_random_community():
    return Community.select().order_by(fn.Random()).get()

def get_random_text():
  return fake.text() + '\n' + fake.text()

def get_random_sentence():
  return fake.sentence()

def add_proposals():
  for i in range(Proposal.select(Proposal.id).count(), 50 + 1):
    p = Proposal()
    p.title = fake.sentence(nb_words=5, variable_nb_words=False)
    p.author = get_random_user()
    p.community = get_random_community()
    p.content = get_random_text()
    p.update_search_index()
    p.published = True
    p.upvotes = random.randint(0, 10000)
    p.downvotes = random.randint(0, 10000)
    try:
      with database.atomic():
        p.save()
    except peewee.IntegrityError:
      print("Duplicate title", p.title)

add_proposals()

# prop = Proposal.get(Proposal.slug == "voluptates-minus-deleniti-molestiae-harum")

# for i in range(len(prop.comments), 1000 + 1):
#   c = Comment()
#   c.user_id = get_random_user()
#   c.content = get_random_sentence()
#   c.post = prop

#   if i % 10 != 0:
#     c.root = get_random_comment(prop)

#   c.save()


for i in range(Comment.select(Comment.id).count(), 1000):
  c = Comment()

  c.user_id = get_random_user()
  c.content = get_random_sentence()

  if i % 10 != 0:
    c.root = get_random_comment()
#    print("hellow")

#     print(c.root.post.id)
    c.post_id = c.root.post_id

  else:
    c.post_id = get_random_post()

  c.save()

