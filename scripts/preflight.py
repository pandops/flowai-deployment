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


DATABASE_ROLE_KEYS = [
    "db-api-gateway", "db-audit", "db-env-registry", "db-executor-registry",
    "db-flow-registry", "db-journal", "db-model-registry", "db-source-controller",
    "db-task-manager", "db-team-registry",
]
GATEWAY_ENV_KEYS = [
    "API_GATEWAY_POSTGRES_URL",
    "API_GATEWAY_SESSION_KEY_HEX",
    "API_GATEWAY_JOURNAL_TOKEN",
    "API_GATEWAY_WORKING_TOKEN_PRIVATE_KEY_BASE64",
]
NATS_BOOTSTRAP_KEYS = {
    "operator": ["operator.jwt"],
    "resolverIdentities": ["application-account", "system-account"],
    "credentials": ["user.creds"],
    "resolverSeed": ["application.jwt", "system.jwt"],
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


def file_reference(ref, kind, keys, label):
    shape(ref, "kind name keys", label)
    check(ref["kind"] == kind and matches(ref["name"], LABEL), label)
    check(ref["keys"] == keys, label)


def protected_fields(value, keys, label):
    check(type(value) is dict, label)
    for key in keys:
        check(key in value, f"{label}.{key}")
    check(value.keys() == set(keys), label)


def shared_platform_refs(shared, storage_mode):
    label = "protectedReferences.sharedPlatform"
    protected_fields(shared, ["platformDatabaseAdmin", "serviceDatabaseRole", "natsBootstrap"], label)
    admin_label = f"{label}.platformDatabaseAdmin"
    admin = shared["platformDatabaseAdmin"]
    shape(admin, "secretName secretKey", admin_label)
    check(
        matches(admin["secretName"], LABEL) and admin["secretKey"] == "postgres-password",
        admin_label,
    )
    file_reference(
        shared["serviceDatabaseRole"], "Secret", DATABASE_ROLE_KEYS,
        f"{label}.serviceDatabaseRole",
    )
    broker = shared["natsBootstrap"]
    broker_label = f"{label}.natsBootstrap"
    required = ["operator", "resolverIdentities", "credentials"]
    if storage_mode == "fresh":
        required.append("resolverSeed")
    protected_fields(broker, required, broker_label)
    for name in required:
        file_reference(broker[name], "Secret", NATS_BOOTSTRAP_KEYS[name], f"{broker_label}.{name}")


def identity_routing_refs(bindings, storage_mode):
    label = "protectedReferences.identityRouting"
    mandatory = ["liteLLMGatewayAuth", "liteLLMDatabase", "keycloakReconcile"]
    if storage_mode == "fresh":
        mandatory.append("keycloakBootstrap")
    fields = mandatory.copy()
    if isinstance(bindings, dict) and "liteLLMProviderTrust" in bindings:
        fields.append("liteLLMProviderTrust")
    protected_fields(bindings, fields, label)
    file_reference(
        bindings["liteLLMGatewayAuth"], "Secret",
        ["master-key", "credential-encryption-key", "database-url"],
        f"{label}.liteLLMGatewayAuth",
    )
    check(bindings["liteLLMGatewayAuth"]["name"] == "litellm-gateway-auth",
          f"{label}.liteLLMGatewayAuth.name")
    file_reference(bindings["liteLLMDatabase"], "Secret", ["postgres-password"],
                   f"{label}.liteLLMDatabase")
    file_reference(bindings["keycloakReconcile"], "Secret", ["username", "password"],
                   f"{label}.keycloakReconcile")
    if storage_mode == "fresh":
        bootstrap = bindings["keycloakBootstrap"]
        shape(bootstrap, "admin realm", f"{label}.keycloakBootstrap")
        file_reference(bootstrap["admin"], "Secret", ["username", "password"],
                       f"{label}.keycloakBootstrap.admin")
        file_reference(bootstrap["realm"], "Secret", ["flowai-e2e-realm.json"],
                       f"{label}.keycloakBootstrap.realm")
    if "liteLLMProviderTrust" in bindings:
        trust = bindings["liteLLMProviderTrust"]
        shape(trust, "hostAddress bundle", f"{label}.liteLLMProviderTrust")
        check(matches(trust["hostAddress"], r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}"),
              f"{label}.liteLLMProviderTrust.hostAddress")
        try:
            address = ipaddress.IPv4Address(trust["hostAddress"])
        except ValueError:
            raise InvalidInput(f"{label}.liteLLMProviderTrust.hostAddress") from None
        check(not (address.is_unspecified or address.is_loopback or address.is_multicast),
              f"{label}.liteLLMProviderTrust.hostAddress")
        file_reference(trust["bundle"], "ConfigMap", ["ca.pem"],
                       f"{label}.liteLLMProviderTrust.bundle")


def pinned_inventory_image(image, label):
    pattern = rf"[a-z0-9][a-z0-9.:/-]*/[a-z0-9][a-z0-9._-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?@{DIGEST}"
    check(matches(image, pattern) and ":latest@" not in image.lower()
          and digest(image.rsplit("@", 1)[1]), label)


def adoption_inputs(inventory, namespace, catalog):
    label = "adoptionInputs"
    shape(inventory, "namespace liteLLMImage keycloakImage ingressNodePort workloadImages", label)
    check(inventory["namespace"] == namespace, f"{label}.namespace")
    for field in ("liteLLMImage", "keycloakImage"):
        pinned_inventory_image(inventory[field], f"{label}.{field}")
    protected_fields(inventory["workloadImages"], catalog, f"{label}.workloadImages")
    for name, image in inventory["workloadImages"].items():
        pinned_inventory_image(image, f"{label}.workloadImages.{name}")
    port = inventory["ingressNodePort"]
    check(type(port) is int and 1 <= port <= 65535, f"{label}.ingressNodePort")
    return inventory


def workload_values(catalog, bindings, tls, target, images):
    label = "protectedReferences.platformWorkloads"
    shape(bindings, "fixtureHostAddress services", label)
    host = bindings["fixtureHostAddress"]
    if host is not None:
        try:
            address = ipaddress.IPv4Address(host) if type(host) is str else None
        except ValueError:
            address = None
        check(address and str(address) == host and not (
            address.is_loopback or address.is_unspecified or address.is_multicast
        ), f"{label}.fixtureHostAddress")

    stateful_inputs = [name for name, definition in catalog.items() if definition["mode"] != "web"]
    protected_fields(bindings["services"], stateful_inputs, f"{label}.services")
    releases = {}
    for name, definition in catalog.items():
        mode = definition["mode"]
        values = {"mode": mode, "image": images[name]}
        releases[name] = {"needs": definition["needs"], "values": values}
        if "wait" in definition:
            releases[name]["wait"] = definition["wait"]
        if mode == "web":
            continue
        service_label = f"{label}.services.{name}"
        service = bindings["services"][name]
        extra = definition.get("extra")
        shape(service, "config nats revision" + (" extra" if extra else ""), service_label)
        keys = GATEWAY_ENV_KEYS if mode == "gateway" else ["config.yaml"]
        config_name = f"{name}-env" if mode == "gateway" else f"{name}-config"
        for field, expected_name, expected_keys in (
            ("config", config_name, keys),
            ("nats", f"{name}-nats", ["user.creds"]),
            *([("extra", extra["name"], extra["keys"])] if extra else []),
        ):
            ref_label = f"{service_label}.{field}"
            file_reference(service[field], "Secret", expected_keys, ref_label)
            check(service[field]["name"] == expected_name, f"{ref_label}.name")
        check(matches(service["revision"], LABEL), f"{service_label}.revision")
        values.update(
            config=service["config"], nats=service["nats"], revision=service["revision"],
            standCA=tls["standCA"], trustBundle=tls["trustBundle"],
        )
        if definition.get("origin") or mode == "gateway":
            values["origin"] = target["origin"]
        if definition.get("fixtureHost") and host:
            values["fixtureHost"] = host
        if extra:
            values["extra"] = {**service["extra"], "mount": extra["mount"], "volume": extra["volume"]}
    return releases


def protected_refs(protected, namespace, storage_mode=None, identity_routing=False):
    fields = "schema namespace tls"
    if storage_mode is not None:
        check(storage_mode in ("adopt", "fresh"), "storageMode")
        fields += " sharedPlatform"
    if identity_routing:
        check(storage_mode is not None, "storageMode")
        fields += " identityRouting platformWorkloads"
    protected_fields(protected, fields.split(), "protectedReferences")
    check(type(protected["schema"]) is int and protected["schema"] == 1, "protectedReferences.schema")
    check(protected["namespace"] == namespace, "protectedReferences.namespace")
    shape(protected["tls"], " ".join(TLS_REFS), "protectedReferences.tls")
    for name, (kind, *keys) in TLS_REFS.items():
        label = f"protectedReferences.tls.{name}"
        ref = protected["tls"][name]
        file_reference(ref, kind, keys, label)
    if storage_mode is not None:
        shared_platform_refs(protected["sharedPlatform"], storage_mode)
    if identity_routing:
        identity_routing_refs(protected["identityRouting"], storage_mode)
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


def executor_preflight(argv):
    parser = argparse.ArgumentParser(description="Resolve the on-demand Kubernetes Executor image.")
    parser.add_argument("candidate_manifest", type=Path)
    parser.add_argument("token_file")
    args = parser.parse_args(argv)
    check(matches(args.token_file, r"/[^,\\\x00-\x1f\x7f]+"), "tokenFile")
    token_file = Path(args.token_file)
    private_file(token_file, "tokenFile")
    token = read_bytes(token_file, "tokenFile").strip()
    check(re.fullmatch(rb"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token), "tokenFile")

    manifest = ROOT / args.candidate_manifest
    candidate = read_json(manifest, "candidateManifest")
    shape(candidate, "schema stage chartRevision inputRevision e2eRevision components", "candidateManifest")
    try:
        chart_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        raise InvalidInput("candidateManifest.chartRevision") from None
    # The coordinator supplies and verifies the independently selected input and E2E revisions.
    images = candidate_pins(
        candidate, manifest.parent / "receipts", chart_revision,
        candidate["inputRevision"], candidate["e2eRevision"],
    )
    print(images["executor_k8s_openhands"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "receipt-root", "runtime-target", "owned-target"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("chart-revision", "input-revision", "e2e-revision"):
        parser.add_argument(f"--{name}")
    references = parser.add_mutually_exclusive_group(required=True)
    references.add_argument("--protected-refs", type=Path)
    references.add_argument("--sops-reference-envelope", type=Path)
    parser.add_argument("--age-key-file", type=Path)
    parser.add_argument("--shared-platform-storage", choices=("adopt", "fresh"))
    parser.add_argument("--identity-routing-values", type=Path)
    parser.add_argument("--adoption-inputs", type=Path)
    args = parser.parse_args()
    for name in ("runtime_target", "owned_target"):
        check(getattr(args, name) is not None, name)
    routing = args.identity_routing_values is not None
    adopting = routing and args.shared_platform_storage == "adopt"
    check(adopting == bool(args.adoption_inputs), "adoptionInputs")
    candidate_fields = ("candidate", "receipt_root", "chart_revision", "input_revision", "e2e_revision")
    use_candidate = bool(args.candidate) or not adopting
    for name in candidate_fields:
        check((getattr(args, name) is not None) == use_candidate, name)
    check(bool(args.sops_reference_envelope) == bool(args.age_key_file), "sopsAgeKeyFile")
    private_file(args.runtime_target, "runtimeTarget")
    private_file(args.owned_target, "ownedTarget")
    target = runtime_target(
        read_json(args.runtime_target, "runtimeTarget"),
        read_json(args.owned_target, "ownedTarget"),
    )
    catalog = read_json(ROOT / ".helmfile/platform-workloads.json", "platformWorkloads")
    if adopting:
        private_file(args.adoption_inputs, "adoptionInputs")
        inventory = adoption_inputs(
            read_json(args.adoption_inputs, "adoptionInputs"), target["namespace"], catalog,
        )
    if use_candidate:
        images = candidate_pins(
            read_json(args.candidate, "candidate"), args.receipt_root,
            args.chart_revision, args.input_revision, args.e2e_revision,
        )
    else:
        images = {**inventory["workloadImages"], "litellm-gateway": inventory["liteLLMImage"]}
    if args.protected_refs:
        private_file(args.protected_refs, "protectedReferences")
        references = read_json(args.protected_refs, "protectedReferences")
    else:
        references = decrypt_reference_envelope(args.sops_reference_envelope, args.age_key_file)
    tls = protected_refs(references, target["namespace"], args.shared_platform_storage, routing)
    if routing:
        release_inputs = {
            "target": target,
            "liteLLMImage": images["litellm-gateway"],
        }
        if adopting:
            release_inputs["keycloakAdoptionImage"] = inventory["keycloakImage"]
            release_inputs["ingressNodePort"] = inventory["ingressNodePort"]
        values = {
            "namespace": target["namespace"],
            "storageMode": args.shared_platform_storage,
            "protectedReferences": references,
            "identityRouting": release_inputs,
            "platformWorkloads": workload_values(
                catalog, references["platformWorkloads"], tls, target, images,
            ),
        }
        try:
            with os.fdopen(os.open(args.identity_routing_values,
                                   os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
                json.dump(values, output)
        except OSError:
            raise InvalidInput("identityRoutingValues") from None
    print("Candidate and DTU reference structure verified.")


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["executor"]:
            executor_preflight(sys.argv[2:])
        else:
            main()
    except InvalidInput as error:
        sys.exit(f"Preflight rejected input: {error}")
