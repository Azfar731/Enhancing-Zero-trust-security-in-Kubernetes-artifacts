# Bash script for resetting kubernetes cluster to the initial state

#!/usr/bin/env bash
set -euo pipefail

# Path to your original manifest
ALL_YAML="./all.yaml"
# Namespace used in your all.yaml
NS="otterize-auto"
NS_AUTOMATION="otterize-automation"
JOB_NAME="deny-automation-once"
DEPLOY_NAME="deny-automation-controller"


echo "[1/5] Remove any ClientIntents in test namespace (clears deny rules)"
kubectl delete clientintents.k8s.otterize.com -n "$NS" --all --ignore-not-found

echo "[2/5] Remove any Jobs from the namespace"
kubectl delete job "$JOB_NAME" -n "$NS_AUTOMATION" --ignore-not-found

echo "[3/5] Delete existing Deployment"
kubectl delete deployment "$DEPLOY_NAME" -n "$NS_AUTOMATION" --ignore-not-found

echo "[4/5] Re-apply original resources"
kubectl apply -f "$ALL_YAML"

echo "[5/5] Restart server Deployment to pick up baseline spec"
kubectl rollout restart deployment/server -n "$NS"
kubectl rollout status deployment/server -n "$NS" --timeout=120s


echo "Baseline restored: server listening on port 80 and reachable from client."
