#!/bin/bash

update-ca-certificates

if [[ -z $1 ]]; then
    APPDIR=/domino-export
else
    APPDIR=$1
fi

cd $APPDIR
python3 -m flask run --host=0.0.0.0 --port=8888
