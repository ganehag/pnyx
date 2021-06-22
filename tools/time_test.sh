#!/bin/bash

TIME="/usr/bin/time -f %e"

$TIME curl -s "http://10.0.0.229/?page=50000" -o /dev/null
$TIME curl -s "http://10.0.0.229/?page=1" -o /dev/null
$TIME curl -s "http://10.0.0.229/search?q=fugit" -o /dev/null

$TIME curl -s "http://10.0.0.229/c/lokalt_v%C3%A4st" -o /dev/null

$TIME curl -s "http:/10.0.0.229/c/lokalt_v%C3%A4xj%C3%B6/accusantium-quam-eveniet-ut-eos" -o /dev/null

