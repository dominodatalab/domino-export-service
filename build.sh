#!/bin/bash

IMAGE_NAME="imarchenko/domino-export:beta"

aws ecr get-login --region us-east-1 | sed "s#-e none##g" | bash -s --

docker build $PWD -t $IMAGE_NAME

docker push $IMAGE_NAME

