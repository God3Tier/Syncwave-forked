#!/usr/bin/env bash
# Resumes the AWS environment after pause.sh (RUNBOOK.md §9): starts RDS,
# then RabbitMQ, then every other ECS service at its saved task count.
#
#   infrastructure/aws/resume.sh       (Git Bash, from any directory)
#
# The workers must start after RabbitMQ has declared its queues; otherwise
# they connect to a broker with no queues and sit at `consumers 0`.
# Safe to run again if it stops halfway.
set -eu

CLUSTER=${CLUSTER:-syncwave}
DB=${DB:-syncwave}
RABBITMQ_TIMEOUT=${RABBITMQ_TIMEOUT:-600}        # seconds to wait for "definitions loaded"
cd "$(dirname "$0")"                             # infrastructure/aws, for terraform below

db_status() {
  aws rds describe-db-instances --db-instance-identifier "$DB" \
    --query 'DBInstances[0].DBInstanceStatus' --output text
}

# Scales the ECS service with ARN $1 back to its saved count and removes the
# tag. Returns 1 if the service has no saved count (it wasn't paused).
restore() {
  local COUNT
  COUNT=$(aws ecs list-tags-for-resource --resource-arn "$1" \
    --query "tags[?key=='PausedDesiredCount'].value | [0]" --output text)
  [ "$COUNT" != None ] || return 1
  aws ecs update-service --cluster "$CLUSTER" --service "${1##*/}" --desired-count "$COUNT" \
    --query 'service.[serviceName,desiredCount]' --output text
  aws ecs untag-resource --resource-arn "$1" --tag-keys PausedDesiredCount
}

# 1. Start the database and wait until it accepts connections
STATUS=$(db_status)
if [ "$STATUS" = stopping ]; then
  echo "RDS is still stopping; waiting until it has stopped..."
  until [ "$(db_status)" = stopped ]; do sleep 30; done
  STATUS=stopped
fi
if [ "$STATUS" = stopped ]; then
  aws rds start-db-instance --db-instance-identifier "$DB" \
    --query 'DBInstance.DBInstanceStatus' --output text
fi
echo "Waiting for RDS to be available (about 5 to 10 minutes)..."
aws rds wait db-instance-available --db-instance-identifier "$DB"
echo "RDS available"

ARNS=$(aws ecs list-services --cluster "$CLUSTER" --query 'serviceArns' --output text | tr '\t' '\n')
RABBITMQ=$(echo "$ARNS" | grep '/rabbitmq$' || true)

# 2. RabbitMQ, and wait until its queues are declared
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ -n "$RABBITMQ" ] && restore "$RABBITMQ"; then
  echo "Waiting for RabbitMQ to declare its queues..."
  WAITED=0
  until MSYS_NO_PATHCONV=1 aws logs tail /ecs/syncwave/rabbitmq --since "$START" | grep -q "definitions loaded"; do
    if [ "$WAITED" -ge "$RABBITMQ_TIMEOUT" ]; then
      echo "RabbitMQ did not load its definitions within ${RABBITMQ_TIMEOUT}s. See RUNBOOK.md §7, then run resume.sh again." >&2
      exit 1
    fi
    sleep 15
    WAITED=$((WAITED + 15))
  done
  echo "RabbitMQ ready"
fi

# 3. Everything else
for ARN in $(echo "$ARNS" | grep -v '/rabbitmq$' || true); do
  restore "$ARN" || true                         # not paused: leave it as it is
done
echo "Waiting for the services to be stable..."
for ARN in $ARNS; do
  aws ecs wait services-stable --cluster "$CLUSTER" --services "${ARN##*/}"
done
echo "Resumed: $(terraform -chdir=platform output -raw base_url)"
