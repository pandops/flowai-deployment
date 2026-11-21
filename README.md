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
| 2.3 platform PostgreSQL | Baseline deployment resources in `qa-e2e/scripts/test-deployment.mjs` | Keep the `postgres` claim, service and separate service roles and schemas. Adopt before switching images. |
| 2.4 NATS and broker bootstrap | Baseline `qa-e2e/containerized-runtime-services/deployment/platform.mjs` | Keep `nats`, JetStream state, live account JWT updates and revocations. Bootstrap fills absent resources only. |
| 2.5 LiteLLM | Existing owned `svc/litellm-gateway/deploy/k8s/chart` 0.1.0, no chart dependencies | Keep its release and database claim. Preserve separate management and data routes and their client boundaries. |
| 2.6 Keycloak | Baseline `qa-e2e/scripts/test-deployment.mjs` starts from Keycloak 26.6.3 | Resolve an immutable upstream pin in the migration slice. Preserve the claim, realm, users and clients. |
| 2.7 ingress | Baseline `qa-e2e/scripts/test-deployment.mjs` | Keep the ingress name, address and worktree port. Ingress owns TLS termination and routing, including the demo origin change. |
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

## Candidate and protected inputs

[Preflight input contract](manifests/README.md)
