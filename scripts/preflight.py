#!/usr/bin/env python3
"""Validate public candidate evidence and DTU references without contacting DTU."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMIT = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
NUMBER = r"(?:0|[1-9][0-9]*)"
PRERELEASE_ID = rf"(?:{NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
STABLE = rf"{NUMBER}\.{NUMBER}\.{NUMBER}"
SNAPSHOT = rf"{STABLE}-{PRERELEASE_ID}(?:\.{PRERELEASE_ID})*"
TLS_REFS = {
    "ingressTLS": ("Secret", "tls.crt", "tls.key"),
    "natsTLS": ("Secret", "tls.crt", "tls.key"),
    "platformPostgresTLS": ("Secret", "tls.crt", "tls.key"),
    "standCA": ("Secret", "ca.pem"),
    "trustBundle": ("ConfigMap", "ca.pem"),
}


class InvalidInput(Exception):
    pass


def check(condition, name):
    if not condition:
        raise InvalidInput(name)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def parse_json(raw, label):
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidInput(label) from None


def reject_constant(_):
    raise ValueError


def read_bytes(path, label):
    try:
        return path.read_bytes()
    except OSError:
        raise InvalidInput(label) from None


def read_json(path, label):
    return parse_json(read_bytes(path, label), label)


def shape(value, keys, label):
    check(type(value) is dict and value.keys() == set(keys.split()), label)


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def revision(value):
    return matches(value, COMMIT) and value != "0" * 40


def digest(value):
    return matches(value, DIGEST) and value != "sha256:" + "0" * 64


def worktree_namespace(worktree):
    check(
        type(worktree) is str and worktree not in (".", "..")
        and re.fullmatch(r"[^/\\\x00-\x1f\x7f]+", worktree),
        "worktree",
    )
    base = re.sub(r"[^a-z0-9-]+", "-", worktree.lower()).strip("-")[:59].rstrip("-")
    namespace = f"{base}-dev"
    check(base and not namespace.startswith("kube-"), "namespace")
    return namespace


def runtime_target(runtime, expected):
    fields = "schema worktree namespace phase lanAddress worktreePort origin"
    shape(runtime, fields, "runtimeTarget")
    shape(expected, fields, "ownedTarget")
    check(type(runtime["schema"]) is int and runtime["schema"] == 1, "runtimeTarget.schema")
    namespace = worktree_namespace(runtime["worktree"])
    check(runtime["namespace"] == namespace, "namespace")
    phase = runtime["phase"]
    check(phase in ("development", "test", "demo", "uat"), "phase")
    port = runtime["worktreePort"]
    check(type(port) is int and 59000 <= port <= 59999, "worktreePort")
    address = runtime["lanAddress"]
    try:
        ip = ipaddress.IPv4Address(address) if type(address) is str else None
    except ValueError:
        ip = None
    check(
        ip and str(ip) == address and not (
            ip.is_loopback or ip.is_unspecified or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.packed[0] == 0
        ),
        "lanAddress",
    )
    origin_port = 4173 if phase in ("demo", "uat") else port
    check(runtime["origin"] == f"https://{address}:{origin_port}", "origin")
    for key in fields.split():
        check(type(expected[key]) is type(runtime[key]) and expected[key] == runtime[key], key)
    return runtime


def protected_refs(protected, namespace):
    shape(protected, "schema namespace tls", "protectedReferences")
    check(type(protected["schema"]) is int and protected["schema"] == 1, "protectedReferences.schema")
    check(protected["namespace"] == namespace, "protectedReferences.namespace")
    shape(protected["tls"], " ".join(TLS_REFS), "protectedReferences.tls")
    for name, (kind, *keys) in TLS_REFS.items():
        label = f"protectedReferences.tls.{name}"
        ref = protected["tls"][name]
        shape(ref, "kind name keys", label)
        check(ref["kind"] == kind and matches(ref["name"], LABEL), label)
        check(ref["keys"] == keys, label)
    return protected["tls"]


def private_file(path, label):
    try:
        info = path.lstat()
    except OSError:
        raise InvalidInput(label) from None
    check(
        path.is_absolute() and stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
        label,
    )


def decrypt_reference_envelope(envelope, age_key):
    private_file(envelope, "sopsReferenceEnvelope")
    private_file(age_key, "sopsAgeKeyFile")
    try:
        result = subprocess.run(
            ["sops", "decrypt", "--input-type", "json", "--output-type", "json", str(envelope)],
            env={"PATH": os.environ["PATH"], "SOPS_AGE_KEY_FILE": str(age_key)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise InvalidInput("sopsReferenceEnvelope") from None
    check(result.returncode == 0, "sopsReferenceEnvelope or sopsAgeKeyFile")
    return parse_json(result.stdout, "protectedReferences")


def schema_inputs(inputs, catalog, label):
    check(type(inputs) is list, label)
    existing = set()
    for item in inputs:
        shape(item, "repository sourceRevision path digest", label)
        repo = item["repository"]
        path = item["path"]
        check(type(repo) is str and repo in catalog, label)
        check(revision(item["sourceRevision"]) and digest(item["digest"]), label)
        check(matches(path, r"schemas/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.json"), label)
        check((repo, path) not in existing, label)
        existing.add((repo, path))


def candidate_pins(candidate, receipt_root, chart_revision, input_revision, e2e_revision):
    components = read_json(ROOT / "manifests/components.json", "components")
    fields = "schema stage chartRevision inputRevision e2eRevision components"
    shape(candidate, fields, "candidate")
    check(type(candidate["schema"]) is int and candidate["schema"] == 1, "candidate.schema")
    stage = candidate["stage"]
    check(stage in ("snapshot", "stable"), "candidate.stage")
    for key, expected in (
        ("chartRevision", chart_revision),
        ("inputRevision", input_revision),
        ("e2eRevision", e2e_revision),
    ):
        check(revision(expected) and candidate[key] == expected, f"candidate.{key}")

    pins = candidate["components"]
    check(type(pins) is dict and pins.keys() <= components.keys(), "candidate.components")
    catalog = {f"pandops/{slug}": component for component, slug in components.items()}
    missing = [
        f"pandops/{slug} (selected source revision unavailable)"
        for component, slug in components.items()
        if type(pins.get(component)) is not dict
    ]
    check(not missing, "missing pins: " + ", ".join(missing))
    version_pattern = SNAPSHOT if stage == "snapshot" else STABLE
    outputs = {}
    for component, slug in components.items():
        repository = f"pandops/{slug}"
        pin = pins[component]
        selected = pin.get("sourceRevision")
        label = f"{repository} at {selected if revision(selected) else 'unresolved source revision'}"
        fields = "repository sourceRevision buildSourceRevision version imageDigest qualificationDigest schemaInputs"
        shape(pin, fields, f"{label}: image or qualification pin incomplete")
        check(pin["repository"] == repository, f"{label}: repository")
        check(revision(selected), f"{label}: sourceRevision")
        check(revision(pin["buildSourceRevision"]), f"{label}: buildSourceRevision")
        check(matches(pin["version"], version_pattern), f"{label}: version")
        check(digest(pin["imageDigest"]), f"{label}: imageDigest")
        checksum = pin["qualificationDigest"]
        check(digest(checksum), f"{label}: qualificationDigest")
        schema_inputs(pin["schemaInputs"], catalog, f"{label}: schemaInputs")
        for item in pin["schemaInputs"]:
            publisher = pins[catalog[item["repository"]]]
            check(item["sourceRevision"] == publisher.get("sourceRevision"), f"{label}: publisher revision")
        verify_receipt(pin, receipt_root, label)
        outputs[component] = f'ghcr.io/{repository}:{pin["version"]}@{pin["imageDigest"]}'
    return outputs


def verify_receipt(pin, receipt_root, label):
    checksum = pin["qualificationDigest"].removeprefix("sha256:")
    label = f"{label}: qualification receipt"
    raw = read_bytes(receipt_root / f"{checksum}.json", label)
    check(hashlib.sha256(raw).hexdigest() == checksum, label)
    receipt = parse_json(raw, label)
    fields = "repository sourceRevision buildSourceRevision version imageDigest schemaInputs"
    shape(receipt, f"schema {fields} workflowPath runId outcomes", label)
    check(type(receipt["schema"]) is int and receipt["schema"] == 1, label)
    check(all(receipt[key] == pin[key] for key in fields.split()), label)
    check(matches(receipt["workflowPath"], r"\.github/workflows/[A-Za-z0-9_-]+\.ya?ml"), label)
    check(type(receipt["runId"]) is int and receipt["runId"] > 0, label)
    outcomes = receipt["outcomes"]
    shape(outcomes, "unit integration build", label)
    for key in ("unit", "integration"):
        check(outcomes[key] in ("success", "not-applicable"), label)
    check(outcomes["build"] == "success", label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "receipt-root", "runtime-target", "owned-target"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("chart-revision", "input-revision", "e2e-revision"):
        parser.add_argument(f"--{name}", required=True)
    references = parser.add_mutually_exclusive_group(required=True)
    references.add_argument("--protected-refs", type=Path)
    references.add_argument("--sops-reference-envelope", type=Path)
    parser.add_argument("--age-key-file", type=Path)
    args = parser.parse_args()
    check(bool(args.sops_reference_envelope) == bool(args.age_key_file), "sopsAgeKeyFile")
    private_file(args.runtime_target, "runtimeTarget")
    private_file(args.owned_target, "ownedTarget")
    target = runtime_target(
        read_json(args.runtime_target, "runtimeTarget"),
        read_json(args.owned_target, "ownedTarget"),
    )
    candidate_pins(
        read_json(args.candidate, "candidate"), args.receipt_root,
        args.chart_revision, args.input_revision, args.e2e_revision,
    )
    if args.protected_refs:
        private_file(args.protected_refs, "protectedReferences")
        references = read_json(args.protected_refs, "protectedReferences")
    else:
        references = decrypt_reference_envelope(args.sops_reference_envelope, args.age_key_file)
    protected_refs(references, target["namespace"])
    print("Candidate and DTU reference structure verified.")


if __name__ == "__main__":
    try:
        main()
    except InvalidInput as error:
        sys.exit(f"Preflight rejected input: {error}")
