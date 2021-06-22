#!/usr/bin/python

import os, sys
import hashlib

sys.path.insert(1, os.path.join(sys.path[0], '../src'))

from main import db, User

items = ['NumerousDiamond', 'AcceptableVillage', 'InformalEditor', 'ImportantRoad', 'HistoricalPainting', 'SexualClimate', 'ConsistentConcept', 'DesperateCoffee', 'ScaredFood', 'OddCurrency', 'AsleepImportance', 'GuiltyManager', 'ScaredGrandmother', 'PoliticalChapter', 'UnusualEmphasis', 'DramaticArt', 'InnerHealth', 'SevereAssociation', 'NiceInternet', 'ElectronicAffair', 'MedicalFeedback', 'ElectricalArrival', 'LatterExplanation', 'SufficientApartment', 'CulturalPeople', 'DistinctGirl', 'DangerousIdea', 'SeriousMeaning', 'SuitableCity', 'HotApplication', 'EasternActivity', 'SeveralGrandmother', 'KnownInsurance', 'EducationalOven', 'IntelligentBeer', 'PoorMoment', 'AdministrativeManagement', 'StrictContext', 'EfficientCandidate', 'MentalTale']

for item in items:
  u = User()
  u.username = item
  u.email = item.lower()+'@pnyx.app'
  u.password = hashlib.sha384(os.urandom(24)).hexdigest()
  u.save()
