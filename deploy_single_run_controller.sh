# Bash script for running Single Run version of the Controller
# Needs to be in the same directory as the files, or update the file paths 

#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="deny-auto:local"
KIND_CLUSTER="otterize-local"
NS_APP="otterize-auto"
NS_AUTOMATION="otterize-automation"
CLIENTINTENT_FILE="./clientintent.yaml"
JOB_FILE="./job-once.yaml"
JOB_NAME="deny-automation-once"

echo "[1/6] Build Docker image"
docker build -t "$IMAGE_TAG" .

echo "[2/6] Load image into kind cluster: $KIND_CLUSTER"
kind load docker-image "$IMAGE_TAG" --name "$KIND_CLUSTER"

echo "[2b/6] Verify image present locally"
docker images | grep -E "^deny-auto\s+local" || true

echo "[3/6] Reset ClientIntents in $NS_APP, then re-apply"
kubectl delete clientintents.k8s.otterize.com -n "$NS_APP" --all --ignore-not-found
kubectl apply -f "$CLIENTINTENT_FILE"
kubectl get clientintents -n "$NS_APP"

echo "[4/6] Ensure any old Job is removed, then create the Job"
kubectl delete job "$JOB_NAME" -n "$NS_AUTOMATION" --ignore-not-found
kubectl apply -f "$JOB_FILE"

echo "[5/6] Wait for Job completion"
kubectl wait --for=condition=complete "job/$JOB_NAME" -n "$NS_AUTOMATION" --timeout=180s || {
  echo "Job did not complete within timeout. Showing current pods:"
  kubectl get pods -n "$NS_AUTOMATION" -l job-name="$JOB_NAME" -o wide || true
  exit 1
}

echo "[6/6] Stream Job logs"
kubectl logs -f "job/$JOB_NAME" -n "$NS_AUTOMATION"
