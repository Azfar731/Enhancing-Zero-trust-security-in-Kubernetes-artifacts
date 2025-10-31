# Python script for running the Continuous watch version of the Custom Controller. This is the complete/finsihed version of Custom Controller
import sys, time, os
from kubernetes import client, config, watch
from kubernetes.client import ApiException



NAMESPACE_TO_WATCH = os.getenv("NAMESPACE_TO_WATCH", "otterize-auto")
DENY_PORT_ANNOTATION = "otterize-automation/deny-port"

def _init_kube_clients():
    # Try in-cluster first, fall back to local kubeconfig
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi(), client.AppsV1Api()


# initialize kube clients
custom_objects_api, apps_v1 = _init_kube_clients()

def get_denied_port_from_annotation(obj: dict):
    """
    Return the denied port from ClientIntents annotations, or None if missing/invalid.
    Expects DENY_PORT_ANNOTATION to be defined.
    """
    annotations = (obj.get("metadata") or {}).get("annotations") or {}
    raw = annotations.get(DENY_PORT_ANNOTATION)
    if raw is None:
        return None

    try:
        port = int(str(raw).strip())
    except (ValueError, TypeError):
        print(f"Warning: '{DENY_PORT_ANNOTATION}' value is not an integer: {raw}")
        sys.stdout.flush()
        return None

    if not (1 <= port <= 65535):
        print(f"Warning: '{DENY_PORT_ANNOTATION}' out of range 1-65535: {port}")
        sys.stdout.flush()
        return None

    return port

def remove_port_from_deployment(namespace, deployment_name, denied_port):
    try:
        dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
    except ApiException as e:
        if e.status in (403, 404):
            print("Hint: verify RBAC and that the Deployment exists.")
        print(f"Error: read_namespaced_deployment failed: {e}"); sys.stdout.flush()
        return False

    d = dep.to_dict()
    containers = (d.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or [])
    if not containers:
        print("DEBUG: Deployment has no containers."); sys.stdout.flush()
        return False

    ops = []
    # build JSON Patch ops: wipe ports [] for any container that exposes denied_port
    for idx, c in enumerate(containers):
        ports = c.get("ports") or []
        # find indices of entries whose container_port/containerPort == denied_port
        rm_idxs = []
        for j, p in enumerate(ports):
            raw = p.get("container_port", p.get("containerPort"))
            try:
                cp = int(raw) if raw is not None else None
            except Exception:
                cp = None
            if cp == int(denied_port):
                rm_idxs.append(j)

        # JSON Patch: remove matching items from the list
        # reverse is necessary because if we remove index 0 first from port array, then later indexes will shift down and not match our rm_idxs array
        for j in sorted(rm_idxs, reverse=True):
            ops.append({
                "op": "remove",
                "path": f"/spec/template/spec/containers/{idx}/ports/{j}"
            })

    if not ops:
        print(f"DEBUG: No container exposed port {denied_port}. No patch built."); sys.stdout.flush()
        return False

    # ensure annotations map exists, then add/replace a timestamp to force new RS
    ops.append({
        "op": "add",
        "path": "/spec/template/metadata/annotations",
        "value": d.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {}) or {}
    })
    # escape "/" in JSON Patch paths with "~1"
    ops.append({
        "op": "add",  # add acts like upsert for a missing key
        "path": "/spec/template/metadata/annotations/deny-auto~1ts",
        "value": str(int(time.time()))
    })

    # apply with JSON Patch content-type; retry lightly on conflicts
    for delay in (0, 0.2, 0.5):
        try:
            apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=ops,
                
            )
            print(f"DEBUG: JSON patched deployment '{deployment_name}' to clear ports for containers exposing {denied_port}.")
            sys.stdout.flush()
            return True
        except ApiException as e:
            if e.status == 409:
                time.sleep(delay); continue
            print(f"Error: JSON patch failed: {e}"); sys.stdout.flush()
            return False

    return False



def run_automation():
    print(f"Starting Otterize Denial Automation (continuous watch) for namespace: {NAMESPACE_TO_WATCH}")
    sys.stdout.flush()

    reconnect_attempts = 0
    MAX_RECONNECT_ATTEMPTS = 5  # Limit rapid reconnects if persistent issue
    RECONNECT_DELAY_SECONDS = 5  # Delay between reconnect attempts

    while True:  # Keep trying to establish and maintain the watch
        w = watch.Watch()
        try:
            print(f"DEBUG: Attempting to establish watch on ClientIntents in namespace {NAMESPACE_TO_WATCH} (Attempt {reconnect_attempts + 1})...")
            sys.stdout.flush()
            # Stream events for ClientIntents
            for event in w.stream(
                custom_objects_api.list_namespaced_custom_object,
                group="k8s.otterize.com",
                version="v2beta1",
                namespace=NAMESPACE_TO_WATCH,
                plural="clientintents"
            ):
                event_type = event['type']
                obj = event['object']
                intent_name = obj['metadata']['name']
                intent_namespace = obj['metadata']['namespace']

                reconnect_attempts = 0  # Reset attempts on successful event processing

                print(f"\nProcessing event '{event_type}' for ClientIntent '{intent_name}' in namespace '{intent_namespace}'")
                sys.stdout.flush()

                if event_type == "ADDED" or event_type == "MODIFIED":
                    denied_port = get_denied_port_from_annotation(obj)
                    if denied_port:
                        print(f"ClientIntent '{intent_name}' has '{DENY_PORT_ANNOTATION}' annotation. Denied port: {denied_port}")
                        sys.stdout.flush()

                        workload_name = None
                        if 'spec' in obj and 'workload' in obj['spec'] and 'name' in obj['spec']['workload']:
                            workload_name = obj['spec']['workload']['name']

                        if not workload_name:
                            print(f"Warning: ClientIntent '{intent_name}' does not specify a workload name. Skipping.")
                            sys.stdout.flush()
                            continue

                        try:
                            # Before attempting patch, ensure deployment exists
                            apps_v1.read_namespaced_deployment(workload_name, intent_namespace)
                        except client.ApiException as e:
                            if e.status == 404:
                                print(f"Warning: Deployment '{workload_name}' not found for ClientIntent '{intent_name}'. Skipping patch.")
                                sys.stdout.flush()
                                continue
                            else:
                                print(f"Error reading deployment '{workload_name}': {e}")
                                sys.stdout.flush()
                                continue

                        success = remove_port_from_deployment(intent_namespace, workload_name, denied_port)
                        if success:
                            print(f"Automation for ClientIntent '{intent_name}' completed for {workload_name}.")
                            sys.stdout.flush()
                        else:
                            print(f"Automation for ClientIntent '{intent_name}' failed to remove port {denied_port}.")
                            sys.stdout.flush()
                    else:
                        print(f"ClientIntent '{intent_name}' does not have the '{DENY_PORT_ANNOTATION}' annotation or it's malformed.")
                        sys.stdout.flush()

                elif event_type == "DELETED":
                    print(f"ClientIntent '{intent_name}' was deleted. No action taken for port re-addition based on current script logic.")
                    sys.stdout.flush()

        except client.ApiException as e:
            print(f"ERROR: Kubernetes API error during watch: {e}. Attempting to reconnect in {RECONNECT_DELAY_SECONDS} seconds...")
            sys.stdout.flush()
            reconnect_attempts += 1
            if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                print(f"ERROR: Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Exiting due to persistent API errors.")
                sys.stdout.flush()
                sys.exit(1)  # Exit if persistent API errors
            time.sleep(RECONNECT_DELAY_SECONDS)  # Wait before retrying

        except Exception as e:
            print(f"ERROR: An unexpected error occurred during watch: {e}. Attempting to reconnect in {RECONNECT_DELAY_SECONDS} seconds...")
            sys.stdout.flush()
            reconnect_attempts += 1
            if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                print(f"ERROR: Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Exiting due to persistent unexpected errors.")
                sys.stdout.flush()
                sys.exit(1)  # Exit if persistent unexpected errors
            time.sleep(RECONNECT_DELAY_SECONDS)  # Wait before retrying

        finally:
            w.stop()
            print("DEBUG: Watch connection stopped, attempting to restart.")
            sys.stdout.flush()


def main():
    run_automation()
    

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e); sys.exit(1)