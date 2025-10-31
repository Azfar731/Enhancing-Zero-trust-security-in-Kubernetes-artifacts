# Bash script for running Continuous watch version of the Controller
# Needs to be in the same directory as the files, or update the file paths 

set -euo pipefail

IMAGE_TAG="deny-auto:local"
KIND_CLUSTER="otterize-local"
NS_APP="otterize-auto"
NS_AUTOMATION="otterize-automation"
CLIENTINTENT_FILE="./clientintent.yaml"
DEPLOY_FILE="./controller_deployment.yaml"
DEPLOY_NAME="deny-automation-controller"

echo "[1/6] Build Docker image"
docker build -t "$IMAGE_TAG" .

echo "[2/6] Load image into kind cluster: $KIND_CLUSTER"
kind load docker-image "$IMAGE_TAG" --name "$KIND_CLUSTER"

echo "[2b/6] Verify image present locally"
docker images | grep -E "^deny-auto\s+local" || true

echo "[3/6] Reset ClientIntents in $NS_APP, then re-apply"
kubectl delete clientintents.k8s.otterize.com -n "$NS_APP" --all --ignore-not-found


echo "[4/6] Delete existing Deployment, then apply"
kubectl delete deployment "$DEPLOY_NAME" -n "$NS_AUTOMATION" --ignore-not-found
kubectl apply -f "$DEPLOY_FILE"

echo "[5/6] Wait for Deployment rollout"
kubectl rollout status deploy/"$DEPLOY_NAME" -n "$NS_AUTOMATION" --timeout=180s || {
  echo "Rollout did not complete within timeout. Showing current pods:"
  kubectl get pods -n "$NS_AUTOMATION" -l app=deny-automation -o wide || true
  exit 1
}

echo "[6/6] Stream Deployment logs"
kubectl logs -f deploy/"$DEPLOY_NAME" -n "$NS_AUTOMATION"
