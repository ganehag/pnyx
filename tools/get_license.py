#!/usr/bin/python

import pkg_resources

def get_pkg_license(pkgname):
    """
    Given a package reference (as from requirements.txt),
    return license listed in package metadata.
    NOTE: This function does no error checking and is for
    demonstration purposes only.
    """
    pkgs = pkg_resources.require(pkgname)
    pkg = pkgs[0]
    for line in pkg.get_metadata_lines('PKG-INFO'):
        (k, v) = line.split(': ', 1)
        if k == "License":
            return v
    return None


with open('requirements.txt') as f:
  lines = f.read().splitlines()
  for line in lines:
    module = line.split('==')[0]
    try:
      print(get_pkg_license(module))
    except FileNotFoundError:
      pass
