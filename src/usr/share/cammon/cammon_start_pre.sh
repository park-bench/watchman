#!/bin/sh

set -e

mkdir --mode=0750 --parent /var/log/cammon/images
chown --recursive cammon:cammon /var/log/cammon
