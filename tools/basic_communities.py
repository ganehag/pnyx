#!/usr/bin/python3
import sys
import os

import peewee

from slugify import slugify

sys.path.insert(1, os.path.join(sys.path[0], '../src'))

from faker import Faker
from main import database, db, Proposal, Community, User, Tag

import random

from peewee import fn

fake = Faker('sv_SE')

def get_random_user():
    return User.select(User.id).order_by(fn.Random()).get()

def get_random_text():
  return fake.text() + '\n' + fake.text()

def get_random_sentence():
  return fake.sentence()


items = [
  ("Natur, Miljö och Resurser", "politik"),
  ("Konst och Kultur", "politik"),
  ("Socialpolitik och Mönsterbrytning", "politik"),
  ("Integration och Arbetsmarknaden", "politik"),
  ("Freds- och Försvarspolitik", "politik"),
  ("Bostad, Städer och Landsbygd", "politik"),
  ("IT och Digitala Rättigheter", "politik"),
  ("Skola, Utbildning och Forskning", "politik"),
  ("Finans-, Ekonomi- och Skattepolitik", "politik"),
  ("Asylpolitik", "politik"),
  ("Ny Politisk Kultur", "politik"),
  ("Transport", "politik"),
  ("Entreprenör, Näringsliv och Handel", "politik"),
  ("Religion och Kyrka", "politik"),
  ("Sundhet, Livskvalité och Familjeliv", "politik"),
  ("Rättspolitik", "politik"),
  ("EU- och Utrikespolitik", "politik"),
  ("Mat, Jordbruk och Fiske", "politik"),
  ("Inrikespolitik och Offentliga Sektorn", "politik"),
  ("Principer och Värderingar", "politik"),
  ("Mångfald och Jämställdhet", "politik"),
  ("Förslag under utveckling", "politiska-förslag"),
  ("Förslag i samråd", "politiska-förslag"),
  ("Förslag som söker medlemmars stöd", "politiska-förslag"),
  ("Förslag under utveckling", "politiska-förslag"),
  ("Politisk katalog (snälla betygsätt)", "politiska-förslag"),
  ("Annullerade förslag", "politiska-förslag"),
  ("Söker medarbetare", "politiska-förslag"),
  ("Visioner i samråd", "politisk-vision"),
  ("Visioner som väntar på behandling i Politiska Forum", "politisk-vision"),
  ("Visioner under utveckling", "politisk-vision"),
  ("Antagna visioner", "politisk-vision"),
  ("Hemsidan", "hemsidan"),
  ("Funktioner och önskemål", "meta"),
  ("Support", "meta"),
  ("Felanmälan", "meta"),
  ("Lokal Karlshamn", "lokalförening")
]

me = User.get(User.username == 'ganehag')

for title, tag in items:
  c = Community()
  c.name = slugify(title)
  c.description = title
  c.maintainer = me

  with database.atomic():
    try:
      c.save()
    except peewee.IntegrityError as e:
      pass

  c = Community.get(Community.name == slugify(title))

  t = Tag()
  t.title = tag
  t.community = c

  with database.atomic():
    try:
      t.save()
    except peewee.IntegrityError as e:
      pass

  continue

  for z in range(0, 5):
    p = Proposal()
    p.title = fake.sentence(nb_words=5, variable_nb_words=False)
    p.author = get_random_user()
    p.community = c
    p.content = get_random_text()
    p.update_search_index()
    p.published = True
    p.upvotes = random.randint(0, 10000)
    p.downvotes = random.randint(0, 10000)
    try:
      with database.atomic():
        p.save()
    except peewee.IntegrityError as e:
      print(e)
      print("Duplicate title", p.title)

