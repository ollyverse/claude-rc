# claude-rc

Helm chart for Claude Code Remote Control sessions: a controller Deployment (one unprivileged session,
a ServiceAccount that may scale the workers) and a worker StatefulSet (sessions with a privileged
Docker-in-Docker sidecar, `replicas: 0` at rest). Chart version = app version = image tag.

```sh
helm upgrade --install claude-rc oci://ghcr.io/ollyverse/charts/claude-rc --version <X.Y.Z> \
  -n claude-rc --create-namespace -f values.yaml --wait
```

Every option is documented in `values.yaml`. After the install, each pod needs a one-time
`claude auth login` and two `y` answers on its TTY; the pod's log prints the command.
If Argo CD syncs this chart, make it ignore `/spec/replicas` of the StatefulSet, or it heals
every `kubectl scale` back to the value in git.
