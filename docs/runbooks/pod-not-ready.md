# LND namespace Pod is not Ready

1. Identify the namespace and Pod from the alert labels. Check `kubectl -n <namespace> describe pod <pod>` and recent namespace events.
2. Read current container logs with `kubectl -n <namespace> logs <pod> --all-containers --tail=200` and check PVC binding and node conditions.
3. A locked LND wallet can be an expected manual gate. Unlock it using the documented operator procedure; do not put wallet passwords, seeds, or macaroons in alerts or agent prompts.
4. If the problem is image pull, storage, or K3s readiness, repair that cause and observe the Pod and alert return to normal. Obtain operator approval before restarting a funded LND Pod.
