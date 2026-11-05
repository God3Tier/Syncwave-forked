#!/bin/sh
# Deploys one service's already-tested image to Amazon ECS (production).
#
#   1. Copy the image from the GitLab registry to ECR. No rebuild: it is the
#      same image that passed the MR, dev and staging pipelines.
#   2. For each ECS service that runs this image, register a new task
#      definition revision that differs only in the image.
#   3. Point the ECS service at it and wait until the rollout is stable.
#
# The task definitions themselves (CPU, memory, env, secrets, ports) are
# created with the infrastructure (infrastructure/aws/); the pipeline
# only swaps the image.
#
# Required: SERVICE, IMAGE_TAG (from the build job), AWS_REGION, ECR_REGISTRY,
#           ECS_CLUSTER, AWS credentials (OIDC, set up by the deploy job)
# Optional: ECS_SERVICES - ECS service names running this image (default: $SERVICE),
#           e.g. "lyrics lyrics-worker". Task definition family = syncwave-<name>.
set -eu

SRC="$CI_REGISTRY_IMAGE/$SERVICE:$IMAGE_TAG"
DST="$ECR_REGISTRY/syncwave/$SERVICE:$IMAGE_TAG"

echo "$CI_REGISTRY_PASSWORD" | docker login --username "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker buildx imagetools create --tag "$DST" "$SRC"
echo "Copied $SRC -> $DST"

for ecs_service in ${ECS_SERVICES:-$SERVICE}; do
  family="syncwave-$ecs_service"
  aws ecs describe-task-definition --region "$AWS_REGION" --task-definition "$family" \
    --query taskDefinition > task-def.json
  jq --arg image "$DST" '
      .containerDefinitions[0].image = $image
      | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
            .compatibilities, .registeredAt, .registeredBy)' \
    task-def.json > task-def-new.json
  arn=$(aws ecs register-task-definition --region "$AWS_REGION" \
    --cli-input-json file://task-def-new.json \
    --query taskDefinition.taskDefinitionArn --output text)
  aws ecs update-service --region "$AWS_REGION" --cluster "$ECS_CLUSTER" \
    --service "$ecs_service" --task-definition "$arn" >/dev/null
  echo "$ecs_service -> $arn"
done

for ecs_service in ${ECS_SERVICES:-$SERVICE}; do
  echo "Waiting for $ecs_service to become stable..."
  aws ecs wait services-stable --region "$AWS_REGION" --cluster "$ECS_CLUSTER" --services "$ecs_service"
done
echo "Deployed $SERVICE:$IMAGE_TAG"
