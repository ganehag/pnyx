#!/usr/bin/python3

from bs4 import BeautifulSoup
import sys
import os

with open(sys.argv[1]) as f:
  soup = BeautifulSoup(f.read(), 'html.parser')
  print(soup.get_text())
