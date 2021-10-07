#!/bin/bash

RUN_INTERACTIVE="-d"
if [[ "$1" == "-i" ]]; then
     RUN_INTERACTIVE="-it"
fi

source vars.env

IMAGE_NAME="imarchenko/domino-export:beta"
#ECR_KEY=$(aws ecr get-login --region us-east-1 | awk '{print $6}')
#docker login -u AWS -p $ECR_KEY https://573040241134.dkr.ecr.us-east-1.amazonaws.com
#sed -E "s#^ECR_KEY=.*#ECR_KEY=$ECR_KEY#g" vars.env > vars.env.new
#mv vars.env.new vars.env

docker stop domino-export
docker rm domino-export
docker pull $IMAGE_NAME
docker run --name domino-export \
	--env-file vars.env \
	-v $LOCAL_INSTANCE_PATH:$APP_INSTANCE_PATH \
	-v $LOCAL_FLASK_LOGGING_FILE:$FLASK_LOGGING_FILE \
	-v $LOCAL_SQLALCHEMY_DATABASE_FILE:$SQLALCHEMY_DATABASE_FILE \
	-v /var/run/docker.sock:/var/run/docker.sock $ADDITIONAL_DOCKER_ARGS \
	-p $SERVICE_PORT:8888 \
	--privileged \
	$RUN_INTERACTIVE \
	$IMAGE_NAME
