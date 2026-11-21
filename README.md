# FlowAI deployment foundation

The baseline export is `9cf0d0c5f0769b286119be8f12ff6e4edd1d8d0b` from Gitea
`flowai`. This repository owns public release definitions, chart source and
locks, nonsecret defaults and redacted candidate pins. Gitea owns the runner,
contract declarations, and SOPS-encrypted environment inputs. DTU owns the
resolved environment, decrypted files, live Kubernetes Secrets and instance
state. Production operation is outside the approved change.

## Static qualification

Run `python3 -B scripts/qualify-static.py` on Linux with Python 3.9 or later,
Helm 4.1.4 and Helmfile 1.4.4. It uses a generated reference-only fixture,
private tmpfs and an empty kubeconfig. Helmfile lints the local chart and
renders one ConfigMap to verify the namespace, origin and TLS reference
shape. There are zero chart dependencies. The chart version is the initial
version of this owned static chart. The static state uses the
`foundation-preview` kube context and rejects every namespace except the
synthetic fixture namespace. Use only lint and template with this state.

The default workflow is dispatch-only with `contents: read`. Dispatch it
against a revision containing the chart and pass its full SHA as
`expected_source_sha`. The seed checks for the qualification script before
downloading any tool. The workflow renders with synthetic inputs and does
not use Gitea, registry or DTU access.

[Helmfile 1.4.4 state and CLI reference](https://github.com/helmfile/helmfile/blob/v1.4.4/docs/index.md)
· [Helm lint](https://helm.sh/docs/helm/helm_lint/)
· [Helm chart dependencies](https://helm.sh/docs/topics/charts/#chart-dependencies)

## Interfaces for chart owners

Place platform releases and values under `.helmfile/`, with each owned chart
under `.helmfile/charts/<release>/`. Platform entry points use one release
graph across DTU phases. Chart owners add release names, exact local chart
paths, explicit `needs`, public defaults and protected reference inputs
in their migration slice. Preserve inventoried Kubernetes names, selectors,
claims, and release ownership during adoption. Keep the K8s Executor under
`.helmfile/executor.helmfile.yaml.gotmpl` as an on-demand entry point.
The Docker Executor runs on the host. MockServer has its own Gitea state.

Use the resolved `namespace` for Helm releases and same-namespace references.
Use the resolved HTTPS `origin` for ingress, OIDC issuer and redirects,
secure cookie origin-dependent settings, and Web UI same-origin routing.
The Gitea coordinator owns worktree port allocation and the port 4173
handoff. Charts consume those decisions. For images owned by FlowAI, accept
the fully resolved `ghcr.io/pandops/<package>:<version>@sha256:<digest>`
reference from preflight. A release for an upstream image records its exact
upstream version and digest independently.

For an upstream chart, check whether it preserves existing resource and
release identities before choosing it. Record upstream provenance and license,
exact chart version, archive checksum and dependency lock. Vendor the
reviewed dependency chart bytes and use `--skip-deps` for offline renders.
Helm generates `Chart.lock` when a chart declares dependencies. The static
chart has neither dependencies nor a generated lock.

| Slice | Choice or approved source | Ownership and migration handoff |
| --- | --- | --- |
| 2.1 foundation | Owned `flowai-foundation` 0.1.0, dependency-free | Static reference render |
| 2.3 platform PostgreSQL | [Owned `postgres` 0.1.0](.helmfile/charts/postgres/Chart.yaml), dependency-free | Keep the `postgres` Deployment, Service and claim and the existing service roles and schemas. The release includes the `database-roles` bootstrap job. |
| 2.4 NATS and broker bootstrap | [Owned `nats` 0.1.0](.helmfile/charts/nats/Chart.yaml), dependency-free | Keep the `nats` Deployment, Service and claim, JetStream state and the live account JWT with its revocations. The release includes the `nats-bootstrap` job. |
| 2.5 LiteLLM | [Owned `litellm-gateway` 0.2.0](.helmfile/charts/litellm-gateway/Chart.yaml), derived from the baseline chart | Keep its release, database claim and isolated listeners. |
| 2.6 Keycloak | [Owned `keycloak` and `keycloak-client` 0.1.0](.helmfile/charts/keycloak/Chart.yaml) | Use the approved current image and claim for first adoption. Fresh uses official Keycloak 26.6.3. Reconcile the Gateway client through ingress. |
| 2.7 ingress | [Owned `ingress` 0.1.0](.helmfile/charts/ingress/Chart.yaml) | Preserve `ingress` and `ingress-host`, certificate identity, address and worktree port. |
| 2.8–2.19 platform workloads | Baseline `platform.mjs` and `test-deployment.mjs` | Each release owns its workload and receives only its own protected bindings. Existing service, broker, network and database boundaries apply. |
| 2.20 MockServer | Gitea `fixtures/mockserver/.helmfile/` | Pin its upstream digest in Gitea and use the approved shared fixture namespace. |
| 3.3 K8s Executor | Existing owned `executor/k8s-openhands/deploy/k8s/chart` 0.1.0, no chart dependencies | On-demand. Accept `namespace`, `releaseName`, `candidateManifest` and private `tokenFile`. Scope team, tag and release lifecycle to their owner. |

The migration slices own chart selections and exact external dependencies
for releases where the inventory names baseline manifests. Task 2.21 owns
live resource inventory, the approved maintenance window, rollback inputs
and preservation of certificate and state identity. Task 2.22 owns the later
qualified image transition. Task 3.2 owns candidate and receipt resolution.
Task 3.5 owns the shared OpenHands runtime pin. The current repository
contains the component catalog and version-1 input contract.

## Shared platform release graph

[The platform state](.helmfile/platform.helmfile.yaml.gotmpl) defines
`<namespace>/postgres` and `<namespace>/nats` as independent roots. Protected
objects are supplied by DTU before Helmfile writes for these
releases. Each release waits for its server and completes its post-install
or post-upgrade bootstrap before downstream charts can depend on it.
Service chart owners declare `<namespace>/postgres` and/or
`<namespace>/nats` in `needs` according to their existing edges. The same
state is used across worktree phases.

The charts render the baseline Service selectors `app: postgres` and
`app: nats`, matching the Recreate Deployments. PostgreSQL uses TCP 5432,
database `flowai` and `/var/lib/postgresql/data/pgdata`. The NATS client uses
TLS on TCP 4222 and the broker keeps `/data/jetstream` and `/data/resolver`
on its data volume. PostgreSQL bootstraps the nine service roles and the API
Gateway role mapped in [roles.yaml](.helmfile/charts/postgres/files/roles.yaml).
The API Gateway schema is `api_gateway`. Bootstrap creates absent roles
and schemas in a transaction and aborts if it finds conflicting ownership,
role settings or public grants. Existing role passwords remain unchanged.

The release handoff must explicitly select `storageMode`. In `adopt` the
Deployments reference the original, already-bound `postgres` and `nats`
claims. This keeps those claims outside Helm's release inventory and
preserves them through first-install recovery. Read-only startup guards
require an initialized PostgreSQL 16 directory and the inventoried NATS
resolver entries and JetStream directory. In `fresh` the charts create retained
`local-path` claims, 1 GiB and 2 GiB respectively, and initialize empty storage.
The DTU coordinator verifies claim UIDs and PV backing identities and owns
fresh-versus-adopt selection. Keep the chosen mode fixed for each installed
release. Restore an existing deployment under the agreed recovery procedure.

For an adopted broker, transfer the existing operator JWT and account
identifiers through the protected path. NATS uses the system account
declared in the operator JWT and reads the current account JWTs directly
from the original full resolver store. The chart has no resolver preload
configuration. The fresh-only initialization writes a protected pair of
account JWTs into an empty claim and marks it initialized. Once initialized,
a missing resolver entry stops the Pod. The broker bootstrap issues
create requests only after a stream or consumer lookup returns its
specific JetStream absence error. Its credentials grant only the required
JetStream info/create calls. The protected DTU phase issues and removes
the short-lived bootstrap credential. Existing static and dynamic streams
and durable consumers remain in place.

### Shared upstream image provenance

The images retain the exact indices from the Gitea baseline. Each chart
has zero dependencies, so Helm has no dependency lock to generate.

| Use | Upstream version | Pinned Docker Hub index digest |
| --- | --- | --- |
| PostgreSQL server and bootstrap | PostgreSQL 16.15, package `16.15-1.pgdg13+2`, baseline tag `16` | `sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54` |
| NATS server | `2.11.17-alpine` | `sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00` |
| JetStream bootstrap | NATS Box `0.18.1`, NATS CLI `0.2.4` | `sha256:abb33f930d25425dce3472039a0ffac7427344f7c0b7ef9849b9fe45bb8895fe` |

[PostgreSQL image source](https://github.com/docker-library/postgres)
· [NATS Server v2.11.17 JetStream API and configuration](https://github.com/nats-io/nats-server/tree/v2.11.17/server)
· [NATS Box v0.18.1](https://github.com/nats-io/nats-box/tree/v0.18.1)

The five stream and service durable definitions are from the tracked
`platform.mjs` and the six `svc/*/schemas/consumers.json` declarations at
the baseline above. The protected account and signing state stays on DTU.
Task 2.21 must verify live pin and volume identity, transfer trust and
record original ownership, backups and rollback inputs before adoption.

## Identity, LiteLLM and ingress release graph

The platform state adds these releases when given the reference-only
output of the identity-routing preflight. The charts have no dependencies
to download. The release graph keeps `litellm-gateway` and `keycloak` as
independent roots. Ingress depends on `keycloak`. The `keycloak-client`
release depends on `ingress` and waits for its post-install or upgrade
job. The existing API Gateway, Source Controller, Admin Panel and Web UI
Services must already be present for ingress to resolve their names.
Their chart slices add the remaining edges when those releases join the
state. In particular, API Gateway can depend on `keycloak` and must consume
the same origin before traffic is handed back.

- LiteLLM keeps its original Deployment, StatefulSet and
  `data-litellm-gateway-postgresql-0` claim identity. It uses the same
  PostgreSQL 16 pin, 1 GiB volume claim template and PGDATA path as the
  baseline. First adoption reuses the existing Helm release and requires
  the initialized claim. The only Services exposed by the gateway
  Deployment are `litellm-gateway-management.<namespace>.svc.cluster.local:4000`
  and `litellm-gateway-data.<namespace>.svc.cluster.local:4000`. Both use
  the baseline digest-pinned nginx sidecars with distinct allowlists and
  route to LiteLLM on loopback. The management listener admits the owning
  model registry, and the data listener admits labeled task Pods in the
  same namespace. The host coordinator separately forwards only the data
  Service to the owned Docker task network through the private data relay.
  Verify this transport and the data label authority during the two-lane
  rollout. The charts create no relay or host-port binding for LiteLLM.
- Keycloak keeps the `keycloak` claim mounted at `/opt/keycloak/data`.
  Fresh mode mounts a private startup import and uses
  `quay.io/keycloak/keycloak:26.6.3@sha256:9b0330756022422149aa6502eb2def8cd47c6e1b000c7c65cdb13e7c0133e992`.
  Adoption mounts the existing claim with a startup storage guard and
  runs the inventoried legacy image without importing a realm or setting
  bootstrap credentials. Verify the data directory and ownership against
  the live inventory. Any later move from the existing custom image to
  official bytes requires compatibility and recovery evidence on a copy
  of the original volume. The origin reconciliation job makes a targeted
  update to the existing Gateway client's redirect URIs and web origins.
  It keeps the baseline loopback fixture entries, verifies the
  issuer over TLS and reads back the updated client. The Admin API token
  and the private credentials are never placed in commands or logs.
- Ingress retains the TLS edge on 8443, the inventoried NodePort for
  existing deployments, and the baseline Keycloak, webhook, Source,
  administration, Gateway and Web UI routes. The host coordinator owns
  the recorded worktree port and 4173 demo or UAT handoff. It keeps the
  worktree port reservation during either phase and uses the same runtime
  target to derive the issuer, redirects and Gateway settings. The
  cluster-side job uses the ingress Service and verifies the external
  hostname against the stand CA, independently of the host relay.

Before first adoption, record the existing owners, image and volume
identities, trust references, client origin fields and restore point in
protected DTU storage. During the approved locked cutover, inventory
every resource transferred to Helmfile, keep both database claims and
the Keycloak claim bound, and keep the previous release/configuration
records. Recover a failed first install using those records. Restore
the compatible images, backups and origin inputs before resuming writes.
For LiteLLM retain the original PostgreSQL backup and encryption key.
For Keycloak take a consistent storage backup with Keycloak stopped.
On an origin rollback, restore the previous Keycloak hostname, ingress
config and Gateway settings before rerunning client reconciliation and
moving the host relay. The protected coordinator verifies actual storage,
images, routing, sessions and trust before recording continuity.

[Keycloak 26.6.3 database configuration](https://github.com/keycloak/keycloak/blob/26.6.3/quarkus/config-api/src/main/java/org/keycloak/config/database/Database.java)
· [Keycloak realm import and export](https://www.keycloak.org/server/importExport)
· [Keycloak 26.6.3 client update implementation](https://github.com/keycloak/keycloak/blob/26.6.3/services/src/main/java/org/keycloak/services/resources/admin/ClientResource.java)

## Candidate and protected inputs

[Preflight input contract](manifests/README.md)
