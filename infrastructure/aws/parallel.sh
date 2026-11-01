# Sourced by RUNBOOK.md (`. ./parallel.sh` from infrastructure/aws).
#
# each '<command using $SVC>' <service> ...
#   Runs the command once per service, all at the same time, with $SVC set to
#   that service. Single-quote the command so $SVC is expanded per service.
#   Each one's output goes to logs/<service>.log (replaced on every run) and
#   stdin is closed, so a command that would prompt fails instead of hanging.
#   Waits for all of them, then names the ones that failed.
each() {
  local cmd=$1 jobs="" failed="" svc job
  shift
  mkdir -p logs
  for svc in "$@"; do
    (SVC=$svc; export TF_CLI_ARGS=-no-color; eval "$cmd") > "logs/$svc.log" 2>&1 < /dev/null &
    jobs="$jobs $!:$svc"
  done
  for job in $jobs; do
    wait "${job%%:*}" || failed="$failed ${job#*:}"
  done
  if [ -n "$failed" ]; then
    echo "Failed:$failed (see logs/<service>.log)"
    return 1
  fi
  echo "All $# succeeded"
}
