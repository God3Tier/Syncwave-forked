#!/usr/bin/env bash
# Pauses the AWS environment (RUNBOOK.md §9): scales every ECS service in the
# cluster to 0 tasks, then stops the RDS instance. resume.sh undoes it.
#
#   infrastructure/aws/pause.sh        (Git Bash, from any directory)
#
# Each service's task count is saved as a PausedDesiredCount tag on the ECS
# service, so anyone on the team can resume. A service already at 0 gets no
# tag and stays at 0. Safe to run again if it stops halfway.
set -eu

CLUSTER=${CLUSTER:-syncwave}
DB=${DB:-syncwave}

db_status() {
  aws rds describe-db-instances --db-instance-identifier "$DB" \
    --query 'DBInstances[0].DBInstanceStatus' --output text
}

# 1. Save each service's task count in a tag, then scale it to 0
ARNS=$(aws ecs list-services --cluster "$CLUSTER" --query 'serviceArns' --output text | tr '\t' '\n')
for ARN in $ARNS; do
  S=${ARN##*/}                                   # the service name, e.g. lyrics-worker
  COUNT=$(aws ecs describe-services --cluster "$CLUSTER" --services "$S" \
    --query 'services[0].desiredCount' --output text)
  [ "$COUNT" -gt 0 ] || continue                 # already paused, or at 0 on purpose
  aws ecs tag-resource --resource-arn "$ARN" --tags key=PausedDesiredCount,value="$COUNT"
  aws ecs update-service --cluster "$CLUSTER" --service "$S" --desired-count 0 \
    --query 'service.[serviceName,desiredCount]' --output text
done

echo "Waiting for the tasks to stop..."
for ARN in $ARNS; do
  aws ecs wait services-stable --cluster "$CLUSTER" --services "${ARN##*/}"
done
echo "Running tasks: $(aws ecs describe-clusters --clusters "$CLUSTER" \
  --query 'clusters[0].runningTasksCount' --output text)"

# 2. Stop the database
STATUS=$(db_status)
case $STATUS in
  available)
    aws rds stop-db-instance --db-instance-identifier "$DB" \
      --query 'DBInstance.DBInstanceStatus' --output text ;;
  stopping|stopped) ;;
  *)
    echo "RDS is '$STATUS', not 'available'. Run pause.sh again once it is available." >&2
    exit 1 ;;
esac
until [ "$(db_status)" = stopped ]; do sleep 30; done
echo "RDS stopped. Paused; run resume.sh to bring it back."
