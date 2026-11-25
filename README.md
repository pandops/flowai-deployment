# FlowAI deployment foundation

The baseline export is `9cf0d0c5f0769b286119be8f12ff6e4edd1d8d0b` from Gitea
`flowai`. This repository owns public release definitions, chart source and
locks, nonsecret defaults and redacted candidate pins. Gitea owns the runner,
contract declarations, and SOPS-encrypted environment inputs. DTU owns the
resolved environment, decrypted files, live Kubernetes Secrets and instance
state. Production operation is outside the approved change.

## Static qualification

The dispatch-only workflow runs static qualification inline with
`contents: read`, Helm 4.1.4 and Helmfile 1.4.4. It verifies the checkout
against `expected_source_sha` before installing tools. It uses generated
reference-only inputs, private tmpfs and an empty kubeconfig. It lints and
renders the foundation and platform, checks the exact release inventory and
verifies image pin propagation. Run the same workflow step locally with
the pinned tools on Linux. The check requires no Gitea, registry or DTU
access.

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
the fully resolved `ghcr.io/pandops/<package>:<version>` reference from
preflight. Upstream images use explicit version tags as well.

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
| 2.8–2.19 platform workloads | [Owned `platform-workload` 0.1.0](.helmfile/charts/platform-workload/Chart.yaml), dependency-free | Each release owns its workload and receives only its own protected bindings. Existing service, broker, network and database boundaries apply. |
| 2.20 MockServer | Gitea `fixtures/mockserver/.helmfile/` | Select its upstream version tag in Gitea and use the approved shared fixture namespace. |
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

The charts use these upstream tags. They have no chart dependencies.

| Use | Tag |
| --- | --- |
| PostgreSQL server and bootstrap | `16.15` |
| NATS server | `2.11.17-alpine` |
| JetStream bootstrap | NATS Box `0.18.1` |

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
independent roots. Ingress depends on Keycloak and the four releases that
own its upstream Services. The Keycloak client hook depends on ingress.

The Gateway opens its HTTP listener after OIDC discovery at the public
issuer. Its Helm release creates its Service and Deployment without a
Helm readiness wait, allowing ingress to resolve the Service and start.
The host coordinator enables the existing relay on the approved port after
the ingress NodePort is available and explicitly waits for Gateway
`/healthz` before marking the deployment ready. The Keycloak client hook
reconciles the client over cluster ingress with the external issuer identity.

- LiteLLM keeps its original Deployment, StatefulSet and
  `data-litellm-gateway-postgresql-0` claim identity. It uses PostgreSQL 16.15 and retains
  the baseline 1 GiB volume claim template and PGDATA path. First adoption reuses the existing Helm release and requires
  the initialized claim. The only Services exposed by the gateway
  Deployment are `litellm-gateway-management.<namespace>.svc.cluster.local:4000`
  and `litellm-gateway-data.<namespace>.svc.cluster.local:4000`. Both use
  versioned nginx sidecars with distinct allowlists and
  route to LiteLLM on loopback. The management listener admits the owning
  model registry, and the data listener admits labeled task Pods in the
  same namespace. The host coordinator separately forwards only the data
  Service to the owned Docker task network through the private data relay.
  Verify this transport and the data label authority during the two-lane
  rollout. The charts create no relay or host-port binding for LiteLLM.
- Keycloak keeps the `keycloak` claim mounted at `/opt/keycloak/data`.
  Fresh mode mounts a private startup import and uses
  `quay.io/keycloak/keycloak:26.6.3`.
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

## Platform workload releases

[The workload catalog](.helmfile/platform-workloads.json) defines the ten
platform services, API Gateway and Web UI. Every release owns its original
Deployment and ClusterIP Service. The chart keeps the `app` selectors, port
8080, probe behavior and production image entry points. Eleven releases
project their own NATS identity with the stand CA and trust bundle. The
nine data-owning services and Gateway depend on the shared PostgreSQL
release. Admin Panel has no database. Web UI keeps its TCP readiness probe
and reaches the Gateway through the browser's same-origin routes.

Source Controller and Model Registry can map the baseline host fixture
aliases to the coordinator's verified address. The release graph does not
publish the fixture. Model Registry owns the management access to LiteLLM
and returns the data-plane URL by Executor type. Both baseline URLs use
`http://litellm-gateway-data:4000/v1`. Kubernetes resolves the Service and
the private Docker task network resolves the data-only forwarder alias.
The host coordinator verifies those separate transports before testing.

## Candidate and protected inputs

[Preflight input contract](manifests/README.md)
