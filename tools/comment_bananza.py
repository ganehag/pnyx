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

def get_random_user():
    return User.select(User.id).order_by(fn.Random()).get()

def get_random_text():
  return fake.text() + '\n' + fake.text()

def get_random_sentence():
  return fake.sentence()

prop = Proposal.get(Proposal.slug == "quasi-veritatis-beatae-alias-porro")

for i in range(len(prop.comments), 1000 + 1):
  c = Comment()
  c.user_id = get_random_user()
  c.content = get_random_sentence()
  c.post = prop

  if i % 10 != 0:
    c.root = get_random_comment(prop)

  c.save()
