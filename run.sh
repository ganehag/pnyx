#!/bin/sh

if [ "$WORKERS" == "" ]; then
  WORKERS=4
fi

gunicorn --bind=0.0.0.0:80 --workers=$WORKERS --access-logfile=- --error-logfile=- main:app
