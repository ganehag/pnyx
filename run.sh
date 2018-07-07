#!/bin/sh

if [ "$WORKERS" == "" ]; then
  WORKERS=4
fi

waitress-serve --list '0.0.0.0:80' --call 'application:create_app'
# gunicorn --bind=0.0.0.0:80 --workers=$WORKERS --access-logfile=- --error-logfile=- main:app
