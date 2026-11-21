#!/usr/bin/env python3
"""Render the foundation with generated references and no cluster connection."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

from preflight import ROOT, TLS_REFS, protected_refs, runtime_target


def run(args, env):
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, check=False)
    if result.returncode:
        raise SystemExit(f"{args[0]} {args[-1]} failed")
    return result.stdout.decode()


def main():
    namespace = "foundation-preview-dev"
    target = {
        "schema": 1,
        "worktree": "foundation-preview",
        "namespace": namespace,
        "phase": "test",
        "lanAddress": "192.0.2.44",
        "worktreePort": 59000,
        "origin": "https://192.0.2.44:59000",
    }
    tls = {
        name: {"kind": kind, "name": f"preview-{name.lower()}", "keys": keys}
        for name, (kind, *keys) in TLS_REFS.items()
    }
    runtime_target(target, target)
    protected_refs({"schema": 1, "namespace": namespace, "tls": tls}, namespace)
    with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": directory,
            "TMPDIR": directory,
            "KUBECONFIG": "/dev/null",
            "HELMFILE_DISABLE_INSECURE_FEATURES": "true",
            "HELMFILE_UPGRADE_NOTICE_DISABLED": "1",
        }
        helm = run(["helm", "version", "--short"], env).strip().split("+", 1)[0]
        helmfile = run(["helmfile", "version", "--output", "short"], env).strip()
        if helm != "v4.1.4" or helmfile != "1.4.4":
            raise SystemExit("Static qualification requires Helm 4.1.4 and Helmfile 1.4.4")
        state = Path(directory, "foundation.json")
        state.write_text(json.dumps({
            "foundation": {"namespace": namespace, "origin": target["origin"], "tls": tls}
        }))
        state.chmod(0o600)
        command = [
            "helmfile", "--file", ".helmfile/foundation.helmfile.yaml.gotmpl",
            "--skip-deps", "--state-values-file", str(state),
        ]
        run([*command, "lint"], env)
        rendered = run([*command, "template"], env)
        lines = (line for line in rendered.splitlines() if not line.startswith("#") and line != "---")
        document = json.loads("\n".join(lines))
        expected = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "flowai-foundation", "namespace": namespace},
            "data": {
                "origin": target["origin"],
                "tlsReferences": json.dumps(tls, separators=(",", ":"), sort_keys=True),
            },
        }
        if document != expected:
            raise SystemExit("Foundation render differs from the reference contract")
    print("Foundation lint, synthetic Helmfile render and reference structure passed.")


if __name__ == "__main__":
    main()
