#!/usr/bin/python3

from __future__ import print_function

import urllib
import time
import sys

times = []

start = time.time()

for i in range(0, 100):
  nf = urllib.urlopen(sys.argv[1])
  page = nf.read()
  end = time.time()
  nf.close()

times.append(end - start)

print("AVG:", (sum(times) / 100) * 1000)

# print("MIN:", (min(times) * 1000))
# print("MAX:", (max(times) * 1000))
