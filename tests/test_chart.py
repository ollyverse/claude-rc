"""Renders charts/claude-rc with its defaults and with a cluster-like values
file, and checks the invariants of the design: what is privileged, what is
mounted, who may scale what."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "claude-rc"
CLUSTER_VALUES = {
    "git": {"repos": {"ollyplatform": "https://github.com/ollyverse/ollyplatform.git",
                      "ollyweb": "https://github.com/ollyverse/ollyweb.git"},
            "user": {"name": "Matej Feder", "email": "feder.mato@gmail.com"}},
    "github": {"existingSecret": "claude-rc-github"},
    "session": {"name": "ollyverse"},
    "controller": {"nodeSelector": {"node-role.kubernetes.io/control-plane": ""}},
    "workers": {"nodeSelector": {"olly.io/pool": "s"}},
}
FORBIDDEN_ENV = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK", "ANTHROPIC_API_KEY",
                 "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "GH_TOKEN"}


def render(values=None, release="claude-rc", namespace="claude-rc"):
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "values.yaml"
        f.write_text(yaml.safe_dump(values or {}))
        out = subprocess.run(["helm", "template", release, str(CHART), "-n", namespace, "-f", str(f)],
                             check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def one(docs, kind, name=None):
    [d] = [d for d in docs if d["kind"] == kind and (name is None or d["metadata"]["name"] == name)]
    return d


def containers(pod):
    return {c["name"]: c for c in pod["spec"]["containers"]}


def env_names(container):
    return {e["name"] for e in container.get("env", [])}


@unittest.skipUnless(shutil.which("helm"), "helm not installed")
class Chart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.default = render()
        cls.cluster = render(CLUSTER_VALUES)

    def test_renders_exactly_these_kinds(self):
        for docs in (self.default, self.cluster):
            kinds = sorted(d["kind"] for d in docs)
            self.assertEqual(kinds, ["Deployment", "PersistentVolumeClaim", "Role", "RoleBinding", "ServiceAccount", "StatefulSet"])

    # --- controller -------------------------------------------------------------

    def test_controller_is_one_replica_recreate(self):
        dep = one(self.cluster, "Deployment", "claude-rc")
        self.assertEqual(dep["spec"]["replicas"], 1)
        self.assertEqual(dep["spec"]["strategy"], {"type": "Recreate"})

    def test_controller_pod(self):
        pod = one(self.cluster, "Deployment", "claude-rc")["spec"]["template"]
        spec = pod["spec"]
        self.assertEqual(spec["serviceAccountName"], "claude-rc")
        self.assertTrue(spec["automountServiceAccountToken"])
        self.assertEqual(spec["nodeSelector"], {"node-role.kubernetes.io/control-plane": ""})
        for key in ("hostPID", "hostNetwork", "hostIPC"):
            self.assertNotIn(key, spec)
        self.assertFalse([v for v in spec["volumes"] if "hostPath" in v])
        self.assertEqual(spec["securityContext"], {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                                   "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}})
        [claude] = spec["containers"]
        self.assertEqual(claude["name"], "claude")
        self.assertTrue(claude["tty"] and claude["stdin"])
        self.assertEqual(claude["securityContext"], {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                                      "capabilities": {"drop": ["ALL"]}})
        self.assertEqual(claude["resources"], {"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"memory": "1.5Gi"}})
        self.assertTrue(claude["image"].startswith("ghcr.io/ollyverse/claude-rc:"))

    def test_controller_env(self):
        claude = containers(one(self.cluster, "Deployment", "claude-rc")["spec"]["template"])["claude"]
        env = {e["name"]: e.get("value") for e in claude["env"]}
        self.assertEqual(env["CLAUDE_SESSION_NAME"], "ollyverse")
        self.assertEqual(env["CLAUDE_SESSION_ORDINAL"], "0")
        self.assertEqual(env["CLAUDE_CAPACITY"], "32")
        self.assertEqual(env["CLAUDE_PERMISSION_MODE"], "acceptEdits")
        self.assertEqual(env["GIT_USER_NAME"], "Matej Feder")
        self.assertEqual(env["GIT_USER_EMAIL"], "feder.mato@gmail.com")
        self.assertEqual(sorted(env["GIT_REPOS"].split()),
                         ["ollyplatform=https://github.com/ollyverse/ollyplatform.git", "ollyweb=https://github.com/ollyverse/ollyweb.git"])
        self.assertIn("POD_NAMESPACE", env)
        self.assertNotIn("DOCKER_HOST", env)
        self.assertFalse(FORBIDDEN_ENV & set(env))

    def test_controller_mounts(self):
        pod = one(self.cluster, "Deployment", "claude-rc")["spec"]["template"]["spec"]
        claude = containers({"spec": pod})["claude"]
        mounts = {(m["name"], m["mountPath"], m.get("subPath"), m.get("readOnly", False)) for m in claude["volumeMounts"]}
        self.assertEqual(mounts, {("home", "/home/claude", "home", False), ("home", "/workspace", "workspace", False),
                                  ("tmp", "/tmp", None, False), ("github", "/etc/claude-rc/github", None, True)})
        volumes = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual(volumes["home"]["persistentVolumeClaim"], {"claimName": "claude-rc"})
        self.assertEqual(volumes["github"]["secret"], {"secretName": "claude-rc-github", "defaultMode": 0o440})
        self.assertIn("emptyDir", volumes["tmp"])

    def test_controller_pvc(self):
        pvc = one(self.cluster, "PersistentVolumeClaim", "claude-rc")
        self.assertEqual(pvc["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(pvc["spec"]["resources"]["requests"]["storage"], "10Gi")
        self.assertNotIn("storageClassName", pvc["spec"])
        sc = render({"persistence": {"storageClassName": "hcloud-volumes"}})
        self.assertEqual(one(sc, "PersistentVolumeClaim", "claude-rc")["spec"]["storageClassName"], "hcloud-volumes")

    def test_controller_rbac_scales_the_workers_only(self):
        role = one(self.cluster, "Role", "claude-rc-controller")
        self.assertEqual(role["rules"], [
            {"apiGroups": ["apps"], "resources": ["statefulsets"], "resourceNames": ["claude-rc-worker"], "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["apps"], "resources": ["statefulsets/scale"], "resourceNames": ["claude-rc-worker"], "verbs": ["get", "update", "patch"]},
            {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
        ])
        rb = one(self.cluster, "RoleBinding", "claude-rc-controller")
        self.assertEqual(rb["roleRef"], {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "claude-rc-controller"})
        self.assertEqual(rb["subjects"], [{"kind": "ServiceAccount", "name": "claude-rc", "namespace": "claude-rc"}])
        self.assertFalse([d for d in self.cluster if d["kind"] in ("ClusterRole", "ClusterRoleBinding")])

    def test_no_github_secret_means_no_mount(self):
        claude = containers(one(self.default, "Deployment", "claude-rc")["spec"]["template"])["claude"]
        self.assertFalse([m for m in claude["volumeMounts"] if m["name"] == "github"])

    def test_controller_can_be_switched_off(self):
        docs = render({"controller": {"enabled": False}})
        self.assertEqual(sorted(d["kind"] for d in docs), ["StatefulSet"])

    # --- workers ----------------------------------------------------------------

    def test_workers_rest_at_zero_parallel_retained(self):
        sts = one(self.cluster, "StatefulSet", "claude-rc-worker")
        self.assertEqual(sts["spec"]["replicas"], 0)
        self.assertEqual(sts["spec"]["podManagementPolicy"], "Parallel")
        self.assertEqual(sts["spec"]["serviceName"], "claude-rc-worker")
        self.assertEqual(sts["spec"]["persistentVolumeClaimRetentionPolicy"], {"whenDeleted": "Retain", "whenScaled": "Retain"})
        [vct] = sts["spec"]["volumeClaimTemplates"]
        self.assertEqual(vct["metadata"]["name"], "home")
        self.assertEqual(vct["spec"]["resources"]["requests"]["storage"], "10Gi")
        self.assertEqual(vct["spec"]["accessModes"], ["ReadWriteOnce"])

    def test_worker_pod(self):
        spec = one(self.cluster, "StatefulSet", "claude-rc-worker")["spec"]["template"]["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertNotIn("serviceAccountName", spec)
        self.assertEqual(spec["nodeSelector"], {"olly.io/pool": "s"})
        for key in ("hostPID", "hostNetwork", "hostIPC"):
            self.assertNotIn(key, spec)
        self.assertFalse([v for v in spec["volumes"] if "hostPath" in v])
        self.assertEqual(spec["securityContext"], {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                                   "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}})
        c = containers({"spec": spec})
        self.assertEqual(sorted(c), ["claude", "dind"])
        privileged = [n for n, x in c.items() if x.get("securityContext", {}).get("privileged")]
        self.assertEqual(privileged, ["dind"])

    def test_worker_claude_container(self):
        c = containers(one(self.cluster, "StatefulSet", "claude-rc-worker")["spec"]["template"])["claude"]
        self.assertTrue(c["tty"] and c["stdin"])
        self.assertEqual(c["securityContext"], {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                                 "capabilities": {"drop": ["ALL"]}})
        self.assertEqual(c["resources"], {"requests": {"cpu": "200m", "memory": "512Mi"}, "limits": {"memory": "1Gi"}})
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual(env["CLAUDE_SESSION_ORDINAL"], "1")
        self.assertEqual(env["CLAUDE_SESSION_NAME"], "ollyverse")
        self.assertEqual(env["DOCKER_HOST"], "unix:///run/docker/docker.sock")
        self.assertFalse(FORBIDDEN_ENV & set(env))
        mounts = {(m["name"], m["mountPath"]) for m in c["volumeMounts"]}
        self.assertEqual(mounts, {("home", "/home/claude"), ("home", "/workspace"), ("tmp", "/tmp"),
                                  ("github", "/etc/claude-rc/github"), ("docker-sock", "/run/docker")})

    def test_worker_dind_container(self):
        c = containers(one(self.cluster, "StatefulSet", "claude-rc-worker")["spec"]["template"])["dind"]
        self.assertEqual(c["image"], "docker:29.9.0-dind")
        # "dockerd" first, or the image's entrypoint adds tcp://0.0.0.0:2375 to our unix socket
        self.assertEqual(c["args"], ["dockerd", "--host=unix:///run/docker/docker.sock", "--group=1000"])
        self.assertEqual({e["name"]: e.get("value") for e in c["env"]}, {"DOCKER_TLS_CERTDIR": ""})
        # root explicitly: the pod-level runAsUser 1000 would otherwise apply and dockerd refuses to start
        self.assertEqual(c["securityContext"], {"privileged": True, "runAsUser": 0, "runAsGroup": 0, "runAsNonRoot": False})
        self.assertEqual(c["resources"], {"requests": {"cpu": "200m", "memory": "256Mi"}, "limits": {"memory": "1.8Gi"}})
        mounts = {(m["name"], m["mountPath"]) for m in c["volumeMounts"]}
        self.assertEqual(mounts, {("docker-sock", "/run/docker"), ("docker-data", "/var/lib/docker")})
        self.assertFalse([p for p in c.get("ports", [])])

    def test_worker_volumes(self):
        spec = one(self.cluster, "StatefulSet", "claude-rc-worker")["spec"]["template"]["spec"]
        volumes = {v["name"]: v for v in spec["volumes"]}
        self.assertEqual(sorted(volumes), ["docker-data", "docker-sock", "github", "tmp"])
        for name in ("docker-data", "docker-sock", "tmp"):
            self.assertIn("emptyDir", volumes[name], name)
        self.assertEqual(volumes["github"]["secret"], {"secretName": "claude-rc-github", "defaultMode": 0o440})

    def test_worker_replicas_follow_the_value(self):
        docs = render({"workers": {"replicas": 2}})
        self.assertEqual(one(docs, "StatefulSet", "claude-rc-worker")["spec"]["replicas"], 2)

    def test_workers_can_be_switched_off(self):
        docs = render({"workers": {"enabled": False}})
        self.assertFalse([d for d in docs if d["kind"] == "StatefulSet"])
        # the controller's Role still names the StatefulSet; harmless, and the chart stays simple


if __name__ == "__main__":
    unittest.main()
