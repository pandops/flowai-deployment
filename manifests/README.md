# Preflight input contract

`scripts/preflight.py` is the executable version-1 schema. It accepts
strict UTF-8 JSON objects with the exact keys below. A coordinator passes
`--candidate`, `--receipt-root`, `--chart-revision`, `--input-revision`,
`--e2e-revision`, `--runtime-target` and `--owned-target`. The coordinator
supplies the expected revisions independently from the checked-out public
chart and input trees and the selected Gitea runner revision.

## Public candidate

The root has `schema: 1`, `stage` (`snapshot` or `stable`), `chartRevision`,
`inputRevision`, `e2eRevision` and `components`. The input revision identifies
the public configuration inputs from which the manifest was resolved. A
manifest can therefore reference already-existing commits without a
self-reference. Each revision is a full lowercase Git SHA. The components
map requires all 15 keys in [the component catalog](components.json).

Each pin has these fields.

| Field | Required identity |
| --- | --- |
| `repository` | `pandops/<slug>` from the component catalog |
| `sourceRevision` | Selected full source commit |
| `buildSourceRevision` | Original full build commit, including when reused |
| `version` | Immutable semantic-release image tag matching the candidate stage |
| `imageDigest` | Manifest digest as `sha256:<64 lower-case hex digits>` |
| `qualificationDigest` | SHA-256 of the exact retained public receipt bytes |
| `schemaInputs` | Array of exact publisher inputs, with `repository`, `sourceRevision`, `path` under `schemas/` and a SHA-256 `digest` per input |

For each pin, `<receipt-root>/<qualificationDigest hex>.json` contains
`schema: 1`, the six pin fields other than `qualificationDigest`,
`workflowPath`, integer GitHub Actions `runId`, and `outcomes`.
The outcomes object has `unit`, `integration` and `build`. Test
outcomes are `success` or the applicable `not-applicable` result.
`build` must be `success`.

Preflight checks completeness, receipt checksum, binding to the candidate
and publisher revisions. The producer in task 3.2 verifies real workflow
results and artifact provenance, compares schema inputs against the Gitea
declarations, and resolves required upstream inputs before offering a
deployment descriptor. Retain public receipts for each selectable manifest.
The first selectable snapshot requires the complete qualified set.

## Private target and protected references

`runtimeTarget` and the independent coordinator-owned `ownedTarget` are
owner-only files. Both have `schema: 1`, `worktree` (directory basename),
`namespace`, `phase` (`development`, `test`, `demo` or `uat`),
`lanAddress`, `worktreePort` and `origin`. The namespace derives from the
worktree using the existing DNS-label normalization and ends with `-dev`.
The origin is `https://<LAN IPv4>:<recorded port>`. Worktree ports are in
59000–59999. Demo and UAT use 4173. The coordinator supplies the assigned
worktree and approved LAN address and port from its own records. Preflight
checks the resolved target against both the derivation and that record.

The named `protectedReferences` object has `schema: 1`, `namespace`
and `tls`. The Gitea-owned wrapper passes an owner-only local JSON file with
`--protected-refs`, or uses `--sops-reference-envelope` with `--age-key-file`
on DTU. In SOPS mode the age identity and encrypted JSON reference envelope
are absolute owner-only regular files. Keep the envelope in protected Gitea,
and keep the identity, verified Gitea input revision and any decrypted
protected values in authorized DTU storage. The SOPS invocation captures
the reference JSON in memory and reports only failing input names.

Each TLS entry has exactly `kind`, a same-namespace object `name`, and the
specified ordered `keys` array. Use the names from the worktree adoption
inventory. The baseline examples show how the reference roles map to
the existing secrets and trust bundle.

| TLS input | Object kind | Baseline object name | Keys | Consumer |
| --- | --- | --- | --- | --- |
| `ingressTLS` | Secret | `ingress-tls` | `tls.crt`, `tls.key` | Ingress HTTPS termination |
| `natsTLS` | Secret | `nats-tls` | `tls.crt`, `tls.key` | NATS listener |
| `platformPostgresTLS` | Secret | `postgres-tls` | `tls.crt`, `tls.key` | Platform PostgreSQL server |
| `standCA` | Secret | `stand-ca` | `ca.pem` | Release clients that trust the stand CA |
| `trustBundle` | ConfigMap | `trust-bundle` | `ca.pem` | Release clients that need the combined public trust bundle |

Charts consume the reference by Kubernetes Secret or ConfigMap key selector,
or by a read-only volume restricted to the declared files. For new Secret
objects TLS charts may use `kubernetes.io/tls` with the standard keys.
Adoption preserves the existing object's type and ownership until its
migration permits a change. The private adapter keeps CA signing keys,
certificate material, service credentials, live broker account state and
rollout recovery inputs within Gitea and DTU. Platform charts reference
consumer-specific values provisioned by the applicable protected DTU phase.
The token-file contract is separate from TLS. MiniMax provider credentials
enter through the write-only model API.

The DTU coordinator must stop before lease acquisition on invalid candidate
evidence and before the dependent release on any missing protected input.
For trust materialization, the later migration uses a private temporary
directory on DTU, owner-only short-lived files, and suppressed or sanitized
Helmfile output. Review evidence records logical input names only. Direct
and encrypted reference modes validate the same shape. Raw credential
fields are rejected by that schema. Presence of cluster objects and
preservation of existing trust require DTU adoption evidence.

[SOPS usage](https://getsops.io/docs/usage/)
· [Kubernetes Secret and TLS key conventions](https://kubernetes.io/docs/concepts/configuration/secret/)

The release owners extend the DTU adapter with named Secret references for
their own charts. Use `secretName` and `secretKey` for scalar inputs and
the object name and allowed key list for file projections. The handoff names
are `platformDatabaseAdmin`, `serviceDatabaseRole`, `natsBootstrap`,
`serviceNatsCredentials`, `executorRegistryNatsSigning`, `liteLLMGatewayAuth`,
`liteLLMDatabase`, `keycloakBootstrap`, `gatewaySessionSigning` and
`serviceEncryptionKeys`. Each migration slice owns its exact key names and
read permissions. A shared chart receives only the named bindings it needs.

### Shared platform reference extension

Use `--shared-platform-storage adopt` or `--shared-platform-storage fresh`
when validating inputs for `.helmfile/platform.helmfile.yaml.gotmpl`. Both
reference input modes accept the same version-1 object. This mode requires a
`sharedPlatform` object alongside `tls`. The foundation-only path continues
to use its original reference shape. The coordinator passes the validated
reference object as `protectedReferences` with the resolved `namespace` and
explicit `storageMode` in private Helmfile state values. These values carry
only references. The selected namespace already owns the projected objects.

| Input under `sharedPlatform` | Selector and files | Consumer |
| --- | --- | --- |
| `platformDatabaseAdmin` | `secretName` and `secretKey: postgres-password`. Baseline Secret is `test-deployment`. | PostgreSQL entry point and database bootstrap |
| `serviceDatabaseRole` | Secret file reference. Use the ten `db-<service>` keys for the roles in the chart, alphabetically. Baseline Secret is `test-deployment`. | Database bootstrap |
| `natsBootstrap.operator` | Secret file reference with `operator.jwt` | NATS server |
| `natsBootstrap.resolverIdentities` | Secret file reference with `application-account` followed by `system-account`. Contents are the existing public account IDs. | NATS resolver guard |
| `natsBootstrap.credentials` | Secret file reference with `user.creds`. Baseline Secret name is `nats-bootstrap`. | JetStream bootstrap |
| `natsBootstrap.resolverSeed` | Fresh-only Secret file reference with `application.jwt` followed by `system.jwt`. Adopt mode rejects this field. | Empty NATS resolver initialization |

Each file reference has `kind: Secret`, `name` and the ordered `keys`. TLS still
comes from `platformPostgresTLS`, `natsTLS` and `standCA`. The DTU phase
verifies the original credentials and TLS trust, materializes the selected
protected objects before the dependent release, and issues short-lived NATS
bootstrap credentials with permissions for the declared stream and consumer
info/create subjects and `_INBOX.deployment.>`. During adoption, the
legacy NATS ConfigMap must transfer with its inventoried owner or be
reconciled under the approved recovery plan. The chart projects only its
nonsecret `nats.conf` and takes `operator.jwt` from the named Secret.

### Identity, LiteLLM and ingress reference extension

Supply `--identity-routing-values <new private file>` together with
`--shared-platform-storage fresh|adopt`. The preflight emits the platform
Helmfile state values to that new file with mode 0600. Keep the input
and output files in private DTU storage and discard temporary copies
after the operation. Do not hand-edit the derived state values.

Under `protectedReferences.identityRouting`, supply these exact selectors.
All projections are same-namespace and contain only the listed files.

| Input | Kind and keys | Use |
| --- | --- | --- |
| `liteLLMGatewayAuth` | Secret `litellm-gateway-auth` with `master-key`, `credential-encryption-key`, `database-url` | LiteLLM reads all three as files. |
| `liteLLMDatabase` | Secret with `postgres-password` | Use the same database credentials as the gateway URL. The baseline stores this key in `litellm-gateway-auth`. |
| `liteLLMProviderTrust` | Optional `hostAddress` and `bundle` containing a ConfigMap reference with `ca.pem` | For the owned provider fixture, reproduce the approved aliases and bundle with public roots and fixture trust. The baseline called the bundle `pricing-ca`. |
| `keycloakReconcile` | Secret with `username`, `password` | Existing authorized master-realm account for lookup and configuration of the single Gateway client. |
| `keycloakBootstrap.admin` | Fresh-only Secret with `username`, `password` | Initial master-realm administrator. |
| `keycloakBootstrap.realm` | Fresh-only Secret with `flowai-e2e-realm.json` | Private startup import including the required roles, groups, clients and claim mappers. Use protected user credentials. |

Ingress consumes the existing `tls.ingressTLS` projection. The client
job uses `tls.standCA` for verification of the same ingress certificate
and public IP. The preflight checks all names and key lists. The DTU
coordinator checks object existence, key presence and actual credentials
before enabling the affected releases.

Fresh mode requires all candidate flags. The platform consumes the exact
receipt-validated image references. Adopt mode always requires
`--adoption-inputs <absolute private inventory file>` containing exactly
`namespace`, `liteLLMImage`, `keycloakImage`, `ingressNodePort` and
`workloadImages`. The latter is a map of all 12 workload names to their
exact inventoried image references. All inventoried images require digests.
For the current-image handoff in task 2.21, omit all candidate flags.
For a later qualified image transition in task 2.22, supply all candidate
flags alongside inventory. This replaces the application and LiteLLM
images while keeping the adopted storage mode, Keycloak image and NodePort.
The protected coordinator verifies running image IDs, owners and storage
identity separately from input structure.

### Platform workloads

A full platform render also requires `protectedReferences.platformWorkloads`.
Its exact fields are `fixtureHostAddress` (an approved IPv4 address or null)
and `services`. The address supplies only the Source Controller and Model
Registry aliases `fixture-provider.invalid` and `host.containers.internal`.
Use the recorded host address when those services use host fixtures.
`services` contains all ten platform service names and `api-gateway`.
Web UI has no protected input.

Each entry contains `config`, `nats` and an opaque, nonsecret `revision`.
Use the original same-namespace `<service>-config` Secret with only
`config.yaml` projected and `<service>-nats` with only `user.creds`
projected. Gateway instead reads four keys individually from
`api-gateway-env`, in the following order.

1. `API_GATEWAY_POSTGRES_URL`
2. `API_GATEWAY_SESSION_KEY_HEX`
3. `API_GATEWAY_JOURNAL_TOKEN`
4. `API_GATEWAY_WORKING_TOKEN_PRIVATE_KEY_BASE64`

Two entries also require an `extra` reference. Admin Panel projects only
`cursor-key-1` from `admin-panel-secrets`. Executor Registry projects
`account-public-key`, `account.jwt`, `account-signing-key.nk`,
`operator-signing-key.nk` and `system.creds`, in that order, from
`executor-registry-nats-keys`. Both retain their original mount paths.
Each reference uses the same `kind`, `name` and ordered `keys` shape as
the TLS references.

The DTU coordinator materializes or retains the protected objects before
Helmfile reads the state. Change a service's revision after updating its
configuration, NATS identity, extra inputs or projected trust. Change the
affected revisions when shared trust changes. Use an opaque access-controlled
rotation or configuration revision identifier. The chart projects the
existing objects and schedules a Pod replacement when the revision changes.
For an origin change, refresh the Source Controller and Admin Panel
configuration for the new origin before their replacement Pods start.
Gateway receives its origin-dependent environment directly from the
validated target.

### Required configuration at handoff

Use the baseline `config.example.yaml` and the platform deployment's
`serviceValues`, `fillConfig` and `apiGatewayEnv` functions to reconcile
the existing private objects. Preserve every existing application key,
credential and identity unless the approved operation rotates it. The
workload chart owns the projections. The protected handoff owns the payloads
and their comparison with the live inputs.

All NATS clients use `tls://nats:4222`, the stand CA and their own projected
`/run/flowai/nats/user.creds`. Keep each service-specific inbox, including
Admin Panel's fixed inbox, and the 5s timeout. Existing service users and
their permissions, account IDs, signing identities and revocations remain
owned by the broker and Executor Registry. Database clients use
`postgres:5432`, database `flowai`, `verify-full` and
`/run/flowai/stand-ca/ca.pem`. The role matches the service's underscore
name. Use the following schema and service-specific bindings.

| Service | Schema | Protected payload and routing requirements |
| --- | --- | --- |
| Source Controller | `source_controller_schema` | Existing cursor and poll dispatcher signing key, poll allowlist, fixture trust and current public base URL. Ingress serves `/webhook/` and `/v1/sources/`. |
| Task Manager | `task_manager_schema` | Existing claim signing key and cursor key. Keep intake and event durable consumers. |
| Journal | `journal_schema` | Existing cursor key and shared Gateway bearer token. Its event durable feeds Gateway's WebSocket path. |
| Audit | `audit_schema` | Existing cursor key and active ID. Keep the audit stream durable and tenant-scoped reads. |
| Team Registry | `team_registry_schema` | Existing team state and outbox behavior. |
| Flow Registry | `flow_registry_schema` | Existing cursor key, active ID and cursor TTL. |
| Model Registry | `model_registry_schema` | Existing LiteLLM master key, task-key encryption keyring, cursor and task claim verification key. Keep `http://litellm-gateway-management:4000` for management and `http://litellm-gateway-data:4000/v1` for both type-specific entries. Resolve the latter through the cluster data Service for Kubernetes and the data-only forwarder alias on the private Docker network. Keep provider allowlists, trust and baseline usage refresh. |
| Env Registry | `env_registry_schema` | Existing encryption keyring, cursor and task claim verification key. Keep the internal launch-parameter API and its authorization. |
| Executor Registry | `executor_registry_schema` | Existing cursor and protected account plus system projections. Retain token issuance, revocation and both concrete Executor types. |
| Admin Panel | None | Existing cursor file and fixed NATS identity. Use the current Keycloak issuer, its JWKS endpoint, audience `flowai-api-gateway-admin` and roles at `/realm_access/roles`. Only `/admin/v1/` is routed to Gateway. Other `/admin/` requests go to Admin Panel. |
| API Gateway | `api_gateway` | TLS database URL with the `api_gateway` role, session key, Journal token and working-token signing key. Use `<origin>/idp/realms/flowai-e2e`, client `flowai-api-gateway-e2e`, callback `<origin>/auth/v1/callback` and team claims at `/teams` in the ID token. Journal stays at `http://journal:8080`. |
| Web UI | None | Pinned service image. Ingress serves its assets and routes API requests to Gateway on the same origin. |

Readiness of the application requires Gateway OIDC discovery through the
actual host relay, Keycloak client readback and Gateway `/healthz`. A Helm
result alone does not establish these conditions. Apply the runner's
ownership, locking, recovery and cleanup policies before enabling E2E.
