#!/bin/sh

waitress-serve --list '0.0.0.0:80' --call 'application:create_app'
