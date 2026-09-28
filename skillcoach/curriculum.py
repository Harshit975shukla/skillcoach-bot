"""Reviewed lessons for exact catalog topics, with deterministic core sessions.

Every factual claim was checked against the official page listed in the lesson's references on the
review date. Exercises default to free local or GitHub-hosted tooling. Nothing here is personalized.
"""

REVIEWED_AT = "2026-09-28 (checked against the official docs listed below)"

CI_WORKFLOW = """```yaml
name: build-once
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - run: |
          mkdir -p dist
          echo "built from ${{ github.sha }}" > dist/app.txt
          sha256sum dist/app.txt > dist.sha256
      - uses: actions/upload-artifact@v7
        with:
          name: dist
          path: |
            dist
            dist.sha256
          retention-days: 3
  verify:
    needs: build
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: dist
      - run: sha256sum --check dist.sha256
```"""

CI_CACHE = """```yaml
      - uses: actions/setup-node@v7
        with:
          node-version: 24
          cache: npm
      - run: npm ci
```"""

K8S_MANIFEST = """```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-declarative
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: web-declarative
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: web-declarative
    spec:
      containers:
        - name: nginx
          image: nginx:1.28
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: 80
            periodSeconds: 5
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
```"""

TF_ROOT = """```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

resource "random_pet" "name" {
  length = 2
}

resource "local_file" "hello" {
  filename = "${path.module}/out/hello.txt"
  content  = "Hello, ${random_pet.name.id}\\n"
}

data "local_file" "notes" {
  filename = "${path.module}/notes.txt"
}

output "notes_length" {
  value = length(data.local_file.notes.content)
}
```"""

TF_MODULE = """```hcl
# modules/greeting/main.tf
variable "name" {
  type = string
}

output "message" {
  value = "Hello, ${var.name}!"
}
```
```hcl
# main.tf (root module)
module "greeting" {
  source   = "./modules/greeting"
  for_each = toset(["dev", "prod"])
  name     = each.key
}

output "messages" {
  value = { for key, m in module.greeting : key => m.message }
}
```"""

GHA_CLAIMS = """```yaml
name: oidc-claims
on: workflow_dispatch
permissions:
  contents: read
  id-token: write
jobs:
  claims:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/github-script@v9
        with:
          script: |
            const token = await core.getIDToken('sts.amazonaws.com');
            const claims = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
            core.info(`sub=${claims.sub}`);
            core.info(`aud=${claims.aud}`);
            core.info(`ref=${claims.ref} environment=${claims.environment ?? 'none'}`);
```"""

GHA_TRUST = """```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:OWNER/REPO:ref:refs/heads/main"
        }
      }
    }
  ]
}
```"""

GHA_DEPLOY = """```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: prod
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v7
      - uses: aws-actions/configure-aws-credentials@v6
        with:
          role-to-assume: arn:aws:iam::123456789012:role/gha-deploy
          aws-region: ap-south-1
      - run: aws sts get-caller-identity
```"""


REVIEWED = {
    "ci pipeline design stages artifacts and caching": {
        "id": "ci-pipeline",
        "lesson": {
            "title": "CI pipeline design: stages, artifacts and caching",
            "why": (
                "A CI pipeline is a team's most-used feedback loop. Good design fails fast on cheap checks, "
                "runs expensive work only when it is needed, and ships exactly the build that was tested. "
                "Interviewers probe it because slow, flaky or leaky pipelines cost every engineer time daily, "
                "and a careless cache or artifact can leak data or deploy something nobody tested."
            ),
            "what": (
                "In GitHub Actions a workflow contains jobs. Every job gets a fresh runner, and jobs run in "
                "parallel unless `needs:` orders them, which is how you build stages. Files never flow between "
                "jobs by themselves: **artifacts** carry build outputs to later jobs or keep them after the run, "
                "while the **dependency cache** speeds up repeated downloads across runs. GitHub's docs are "
                "explicit that the two are not interchangeable."
            ),
            "concepts": [
                {
                    "name": "Stages are a dependency graph",
                    "body": (
                        "Jobs start in parallel; `needs: [lint, test]` makes a job wait for others to succeed, "
                        "so your stages are really a graph. Put cheap, high-signal checks (lint, unit tests) "
                        "first and in parallel, and let slow integration or deploy jobs depend on them. "
                        "`concurrency` with `cancel-in-progress: true` cancels a superseded run on the same "
                        "branch, and `timeout-minutes` stops a hung job from burning runner time. Set a default "
                        "`permissions: contents: read` and grant more only to the job that needs it."
                    ),
                },
                {
                    "name": "Artifacts: build once, promote the same output",
                    "body": (
                        "`actions/upload-artifact` stores files from a job; `actions/download-artifact` fetches "
                        "them in a later job of the same run (other runs need a token and run ID). Since v4, "
                        "artifacts are immutable: upload each name once per run, so matrix jobs need unique names "
                        "such as `dist-${{ matrix.os }}`. `retention-days` can shorten storage but cannot exceed "
                        "the repository or organization limit. Build once, then test and deploy that same "
                        "artifact; rebuilding in the deploy job means you ship something you never tested."
                    ),
                },
                {
                    "name": "Dependency caching: keys, restore-keys and scope",
                    "body": (
                        "`actions/cache` first looks for an exact `key` match (a cache hit), then a prefix match, "
                        "then each `restore-keys` prefix in order, taking the most recent match. On a miss, a new "
                        "cache is saved when the job succeeds; an existing cache is never changed, so derive the "
                        "key from what matters, for example `${{ runner.os }}-npm-${{ hashFiles('**/package-lock.json') }}`. "
                        "Runs can restore caches from the current branch, the default branch and, for pull "
                        "requests, the base branch. Entries unused for 7 days are removed; the default limit is "
                        "10 GB per repository. `setup-node` and `setup-python` can manage the cache for you."
                    ),
                },
                {
                    "name": "Cache security and correctness",
                    "body": (
                        "A cache is an optimisation, never a source of truth: the job must still pass on a cold "
                        "miss. Never write secrets or credentials into a cached path, because anyone who can open "
                        "a pull request can read base-branch caches. Low-trust triggers such as "
                        "`pull_request_target`, `issue_comment` and `workflow_run` get read-only access to the "
                        "default branch's cache scope to prevent cache poisoning; use `actions/cache/restore` "
                        "or `cache-mode: read` there, and let a trusted `push` workflow keep the cache warm."
                    ),
                },
            ],
            "e2e": [
                "A push or pull request matches the workflow's top-level `on:` triggers.",
                "`concurrency` cancels an older in-progress run for the same branch.",
                "Lint and unit-test jobs start in parallel on fresh runners and restore the dependency cache.",
                "On a cache miss, dependencies install from the registry; the cache is saved when the job succeeds.",
                "The build job (`needs: [lint, test]`) produces `dist/` and uploads it as an artifact with a unique name.",
                "Integration tests download that exact artifact and test it.",
                "A deploy job gated by an environment downloads the same artifact and releases it without rebuilding.",
                "Artifacts expire after their retention period; caches unused for 7 days are evicted.",
            ],
            "tasks": [
                {
                    "name": "Redesign a slow single-job pipeline",
                    "goal": "Turn one long job into a staged graph that fails fast.",
                    "steps": [
                        "Start from a single job that runs, in order: install, lint, unit tests, build, integration tests, deploy.",
                        "Split it into jobs `lint`, `test`, `build`, `integration`, `deploy` and write each job's `needs:`.",
                        "Mark which jobs can run in parallel and which is the slowest path.",
                        "Add a top-level `concurrency` group with `cancel-in-progress: true`, `timeout-minutes` per job and `permissions: contents: read`.",
                        "Write one sentence: which failure now reports fastest, and why.",
                    ],
                    "minutes": 8,
                },
                {
                    "name": "Predict cache hits and misses",
                    "goal": "Reason precisely about cache keys, restore-keys and branch scope.",
                    "steps": [
                        "Write this step for a Node project:\n" + CI_CACHE,
                        "Now write the equivalent explicit `actions/cache` key using `runner.os` and `hashFiles('**/package-lock.json')`, plus one `restore-keys` prefix.",
                        "Predict hit, partial restore or miss: (a) re-run with an unchanged lockfile; (b) lockfile changed; (c) a new branch created from main; (d) a pull request from a fork.",
                        "Explain why a partial restore is followed by a fresh install and a new cache entry.",
                    ],
                    "minutes": 10,
                },
                {
                    "name": "Build once, verify the same artifact",
                    "goal": "Prove the later job tests exactly the bytes the build produced.",
                    "steps": [
                        "In a public GitHub repository (standard GitHub-hosted runners are free there), add `.github/workflows/build-once.yml`:\n"
                        + CI_WORKFLOW,
                        "Push, open the run and confirm `verify` prints `dist/app.txt: OK`.",
                        "Change the verify job to rebuild the file instead of downloading it, and explain why the check would no longer prove anything.",
                        "Delete the workflow file or the test repository when done; the artifact expires after 3 days.",
                    ],
                    "minutes": 12,
                },
                {
                    "name": "Review a flawed pipeline",
                    "goal": "Spot design defects an interviewer would expect you to catch.",
                    "steps": [
                        "The deploy job runs `npm run build` again instead of downloading the tested artifact.",
                        "Three matrix jobs each upload an artifact named `report`.",
                        "The cache key is the static string `deps`, and a step writes an npm token into `~/.npm`, the cached path.",
                        "No job has `timeout-minutes`, and every job has write permissions.",
                        "For each item, state the failure it causes and the one-line fix.",
                    ],
                    "minutes": 10,
                },
            ],
            "key_terms": [
                "Job — a set of steps that runs on one fresh runner; jobs run in parallel unless ordered by `needs`.",
                "`needs` — makes a job wait for other jobs to succeed; how stages are expressed.",
                "Artifact — files uploaded from a job, downloadable by later jobs or after the run until retention ends.",
                "Dependency cache — reusable files (such as package downloads) restored by key across workflow runs.",
                "Cache key / restore-keys — exact match first, then ordered prefix fallbacks; the newest match wins.",
                "`concurrency` — groups runs so a newer run can cancel or queue behind an older one.",
                "Cache poisoning — writing a malicious cache that a more privileged workflow later restores.",
            ],
            "safety": (
                "Exercises 1, 2 and 4 are paper exercises. Exercise 3 uses a public GitHub repository, where "
                "standard GitHub-hosted runners are free; in a private repository it consumes your included "
                "minutes. Use synthetic files only and never put tokens in artifacts, caches or logs."
            ),
            "cleanup": [
                "Delete the practice workflow file or the throwaway repository.",
                "Optionally delete the run's artifact from the run page; otherwise it expires after the 3-day retention.",
            ],
            "references": [
                "https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching",
                "https://docs.github.com/en/actions/tutorials/store-and-share-data",
                "https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts",
                "https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax",
            ],
            "interview_question": (
                "Your team's pull-request pipeline takes 25 minutes, fails randomly about once a day, and the "
                "deploy job rebuilds the app before shipping it. Walk me through how you would redesign it, "
                "and how you would prove the change helped."
            ),
            "interview_points": [
                "Measure first: per-job duration and failure rate from run history.",
                "Stage as a graph: cheap parallel checks first, `needs` for slow jobs, cancel superseded runs.",
                "Cache keyed on the lockfile, with a job that still passes on a cold miss.",
                "Build once and promote the same artifact; add a checksum or provenance check.",
                "Quarantine and fix flaky tests instead of adding blind retries.",
            ],
        },
        "core": (
            "**Core idea:** a pipeline is a graph of jobs, not a script.\n"
            "- Jobs run in parallel on fresh runners; `needs:` creates stages. Put lint and unit tests "
            "first so the cheapest failure reports first.\n"
            "- **Artifacts** move build output between jobs in a run. They are immutable per name since "
            "v4, so each uploader needs a unique name. Build once; test and deploy that same artifact.\n"
            "- **Caches** speed up dependency installs across runs. Exact `key` hit first, then ordered "
            "`restore-keys` prefixes. Key on the lockfile hash, e.g. "
            "`hashFiles('**/package-lock.json')`. A cache can never be edited, only replaced by a new key.\n"
            "- Caches are readable by anyone who can open a pull request, so never cache secrets. "
            "Low-trust triggers get read-only access to the default branch's cache.\n"
            "- Guard rails: `concurrency` + `cancel-in-progress`, `timeout-minutes`, and "
            "`permissions: contents: read` by default.\n\n"
            "**Artifact vs cache in one line:** artifacts are outputs you keep or pass on; caches are "
            "inputs you would rather not download again."
        ),
        "architecture": {
            "title": "CI pipeline: stages, cache and one artifact",
            "pattern": "flow",
            "labels": [
                "Push / pull request",
                "Lint + unit tests",
                "Dependency cache",
                "Build job",
                "Artifact store",
                "Test + deploy jobs",
            ],
            "connections": [
                (0, 1, "request"),
                (2, 1, "control"),
                (1, 3, "request"),
                (3, 4, "request"),
                (4, 5, "request"),
            ],
            "stages": [
                (
                    "Fail fast in parallel",
                    "Cheap checks run first, in parallel, on fresh runners.",
                    "A push starts lint and unit tests in parallel. Each job gets a fresh runner, so nothing is "
                    "shared unless you pass it on deliberately. The cheapest failure reports first.",
                    [0],
                    {1: "starting"},
                ),
                (
                    "Restore the dependency cache",
                    "An exact key hit restores packages; a miss installs and saves a new entry.",
                    "The job restores dependencies keyed on the lockfile hash. On an exact hit it skips the "
                    "download. On a miss it installs normally and saves a new cache when the job succeeds.",
                    [1],
                    {2: "complete", 1: "healthy"},
                ),
                (
                    "Build once",
                    "The build waits for the checks, then uploads one immutable artifact.",
                    "The build job needs lint and tests to pass. It produces the output once and uploads it "
                    "as an artifact with a unique name. Since version four, that artifact cannot be overwritten.",
                    [2, 3],
                    {3: "complete", 4: "complete"},
                ),
                (
                    "Promote the tested bytes",
                    "Later jobs download the same artifact instead of rebuilding.",
                    "Integration tests and the deploy job download that same artifact. Rebuilding in the deploy "
                    "job would ship something that was never tested. A checksum proves the bytes match.",
                    [4],
                    {5: "healthy"},
                ),
            ],
        },
    },
    "kubernetes pods deployments and replica sets": {
        "id": "k8s-deployments",
        "lesson": {
            "title": "Kubernetes Pods, ReplicaSets and Deployments",
            "why": (
                "Almost every stateless workload on Kubernetes runs as a Deployment. When a rollout stalls, "
                "a pod keeps restarting or a rollback is needed at 2 a.m., you need to know which controller "
                "owns what and what the rolling-update numbers actually mean. That is exactly what interviews "
                "test with 'walk me through a bad rollout'."
            ),
            "what": (
                "A **Pod** is the smallest deployable unit: one or more containers that share a network "
                "identity and volumes. A **ReplicaSet** keeps a stable number of matching Pods running. A "
                "**Deployment** manages ReplicaSets to roll out new versions at a controlled rate and keeps "
                "old ReplicaSets for rollback. You normally create Deployments and never manage their "
                "ReplicaSets directly."
            ),
            "concepts": [
                {
                    "name": "Pods are disposable",
                    "body": (
                        "Containers in a Pod share one IP and port space and can share volumes. Pods are not "
                        "repaired in place: a bare Pod whose node fails is simply gone. Controllers create "
                        "replacement Pods with new names and IPs, which is why clients reach workloads through a "
                        "Service, not a Pod IP. Inspect ownership with "
                        "`kubectl get pod <name> -o jsonpath='{.metadata.ownerReferences[0].kind}'`."
                    ),
                },
                {
                    "name": "ReplicaSets keep the count; labels decide membership",
                    "body": (
                        "A ReplicaSet compares the Pods matching its label selector with `replicas` and creates "
                        "or deletes Pods to close the gap. Membership is by labels, so selectors must match the "
                        "Pod template labels. A Deployment adds a `pod-template-hash` label so each of its "
                        "ReplicaSets selects only its own Pods; the ReplicaSet is named "
                        "`<deployment>-<hash>`. The Kubernetes docs say not to manage ReplicaSets owned by a "
                        "Deployment."
                    ),
                },
                {
                    "name": "Rolling updates: maxSurge and maxUnavailable",
                    "body": (
                        "A rollout starts only when the Pod template (`.spec.template`) changes; scaling does not "
                        "create one. With the default RollingUpdate strategy, `maxSurge` and `maxUnavailable` both "
                        "default to 25%. Surge rounds up and unavailable rounds down, so with 3 replicas you get "
                        "at most 1 extra Pod and 0 unavailable. The new ReplicaSet scales up only as fast as new "
                        "Pods become ready. `Recreate` stops all old Pods first, which causes downtime."
                    ),
                },
                {
                    "name": "Stalled rollouts and rollback",
                    "body": (
                        "If new Pods never become ready (bad image, failing readiness probe, quota), the rollout "
                        "stalls while old Pods keep serving within `maxUnavailable`. After "
                        "`progressDeadlineSeconds` (default 600) the Deployment reports "
                        "`ProgressDeadlineExceeded`, but it does **not** roll back on its own. You run "
                        "`kubectl rollout undo`. Old ReplicaSets are kept up to `revisionHistoryLimit` "
                        "(default 10). The selector is immutable after creation."
                    ),
                },
            ],
            "e2e": [
                "`kubectl apply` sends the Deployment to the API server, which stores it.",
                "The Deployment controller creates a ReplicaSet named `<deployment>-<pod-template-hash>`.",
                "The ReplicaSet controller creates Pods from the template until the count matches `replicas`.",
                "The scheduler assigns each Pod to a node; the kubelet pulls the image and starts containers.",
                "A Pod counts as available once ready for `minReadySeconds` (default 0).",
                "Changing the image creates a new ReplicaSet; it scales up within maxSurge while the old one scales down within maxUnavailable.",
                "If new Pods never become ready, the rollout stalls and eventually reports ProgressDeadlineExceeded.",
                "`kubectl rollout undo` scales the previous ReplicaSet back up; old ReplicaSets beyond revisionHistoryLimit are garbage-collected.",
            ],
            "tasks": [
                {
                    "name": "Watch a ReplicaSet heal a Deployment",
                    "goal": "See ownership and self-healing with your own eyes.",
                    "steps": [
                        "Create a free local cluster: `kind create cluster --name lesson` (needs Docker), or open the free Killercoda Kubernetes playground in a browser.",
                        "`kubectl create deployment web --image=nginx:1.27 --replicas=3`",
                        "`kubectl get deploy,rs,pods --show-labels` and note the `pod-template-hash` label.",
                        "Delete one Pod with `kubectl delete pod <name>`, then run `kubectl get pods -w` and watch a replacement with a new name appear.",
                        "Print the deleted Pod's replacement owner: `kubectl get pod <new-name> -o jsonpath='{.metadata.ownerReferences[0].kind}'`",
                    ],
                    "minutes": 8,
                },
                {
                    "name": "Roll out and roll back",
                    "goal": "Connect a template change to a new ReplicaSet and back again.",
                    "steps": [
                        "`kubectl set image deployment/web nginx=nginx:1.28` (the container is named after the image).",
                        "`kubectl rollout status deployment/web`, then `kubectl get rs` to see two ReplicaSets.",
                        "`kubectl scale deployment/web --replicas=4` and confirm with `kubectl rollout history deployment/web` that scaling added no revision.",
                        "`kubectl rollout undo deployment/web` and check which ReplicaSet now has the Pods.",
                    ],
                    "minutes": 10,
                },
                {
                    "name": "Diagnose a stalled rollout",
                    "goal": "Prove that a bad rollout keeps old Pods serving and does not self-revert.",
                    "steps": [
                        "`kubectl scale deployment/web --replicas=3`, then `kubectl set image deployment/web nginx=nginx:0.0-does-not-exist`",
                        "`kubectl rollout status deployment/web --timeout=60s` fails; `kubectl get pods` shows one new Pod in ErrImagePull or ImagePullBackOff.",
                        "Explain the numbers: with 3 replicas and 25% defaults, surge rounds up to 1 and unavailable rounds down to 0, so all 3 old Pods keep serving.",
                        "Read the reason with `kubectl describe pod <new-pod>`, then recover with `kubectl rollout undo deployment/web`.",
                    ],
                    "minutes": 12,
                },
                {
                    "name": "Write the Deployment declaratively",
                    "goal": "Own the manifest fields that control safety.",
                    "steps": [
                        "Save and `kubectl apply -f web.yaml`:\n" + K8S_MANIFEST,
                        "Explain why `selector.matchLabels` must match the template labels, and what happens if you later try to change the selector.",
                        "Explain what `maxUnavailable: 0` with a readiness probe guarantees during an update, and what it costs.",
                    ],
                    "minutes": 10,
                },
            ],
            "key_terms": [
                "Pod — one or more containers sharing a network identity and volumes; replaced, never repaired.",
                "ReplicaSet — keeps a stable number of Pods matching its selector.",
                "Deployment — manages ReplicaSets for controlled rollouts and rollback.",
                "pod-template-hash — label a Deployment adds so each ReplicaSet selects only its own Pods.",
                "maxSurge / maxUnavailable — rolling-update limits; both default to 25% (surge rounds up, unavailable down).",
                "progressDeadlineSeconds — time before a stuck rollout reports ProgressDeadlineExceeded (default 600).",
                "revisionHistoryLimit — how many old ReplicaSets are kept for rollback (default 10).",
            ],
            "safety": (
                "Everything runs on a free local kind cluster (Docker required) or the free Killercoda browser "
                "playground; no cloud account is needed. The same objects work on managed clusters such as "
                "EKS, but those clusters and any LoadBalancer Services are billed."
            ),
            "cleanup": [
                "`kind delete cluster --name lesson` removes the whole local cluster.",
                "On Killercoda, simply end the session.",
            ],
            "references": [
                "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/",
                "https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/",
                "https://kubernetes.io/docs/concepts/workloads/pods/",
                "https://kind.sigs.k8s.io/docs/user/quick-start/",
            ],
            "interview_question": (
                "You deploy a new image and `kubectl rollout status` hangs. Users report no errors yet. "
                "Explain what Kubernetes is doing with the old and new Pods at this moment, how you find the "
                "cause, and exactly how you get back to a good state."
            ),
            "interview_points": [
                "Two ReplicaSets exist; the new one is limited by maxSurge, the old keeps serving within maxUnavailable.",
                "Readiness gates progress: unready new Pods stall the rollout instead of taking traffic.",
                "Diagnose with rollout status, get rs, describe pod and events (image pull, probe, quota).",
                "The Deployment does not roll back on its own; ProgressDeadlineExceeded only reports it.",
                "Recover with `kubectl rollout undo`, then fix and re-roll; consider maxUnavailable 0 for critical apps.",
            ],
        },
        "core": (
            "**Core idea:** you declare a Deployment; controllers do the rest.\n"
            "- **Pod**: containers sharing one IP and volumes. Disposable: replaced with a new name and IP, "
            "never repaired.\n"
            "- **ReplicaSet**: keeps `replicas` Pods matching its label selector. A Deployment labels each "
            "ReplicaSet's Pods with `pod-template-hash`. Don't manage those ReplicaSets yourself.\n"
            "- **Deployment**: a rollout starts only when `.spec.template` changes. Scaling is not a new "
            "revision.\n"
            "- **Rolling update math**: `maxSurge` and `maxUnavailable` default to 25%. Surge rounds up, "
            "unavailable rounds down: 3 replicas means at most 1 extra Pod and 0 unavailable.\n"
            "- **Bad rollout**: new Pods never get ready, so old Pods keep serving. After "
            "`progressDeadlineSeconds` (600 s) it reports ProgressDeadlineExceeded but does not roll back. "
            "You run `kubectl rollout undo`.\n\n"
            "Today's exercises use a free local **kind** cluster or Killercoda, not a billed cloud cluster."
        ),
        "architecture": {
            "title": "Deployment rollout: two ReplicaSets and a rollback",
            "pattern": "flow",
            "labels": [
                "kubectl / API server",
                "Deployment controller",
                "ReplicaSet v1 (old)",
                "ReplicaSet v2 (new)",
                "Pods serving traffic",
            ],
            "connections": [
                (0, 1, "control"),
                (1, 2, "control"),
                (1, 3, "control"),
                (2, 4, "request"),
                (3, 4, "request"),
            ],
            "stages": [
                (
                    "Desired state is stored",
                    "You change the Pod template; the API server stores the new spec.",
                    "Applying a new image changes the Pod template. The API server stores the Deployment. "
                    "Controllers watch for that change and act on it; kubectl never starts containers itself.",
                    [0],
                    {1: "starting"},
                ),
                (
                    "A new ReplicaSet surges",
                    "The Deployment creates ReplicaSet v2 and scales it within maxSurge.",
                    "The Deployment controller creates a second ReplicaSet for the new template. With three "
                    "replicas and the default limits, it adds at most one extra Pod while the old Pods keep serving.",
                    [1, 2, 4],
                    {2: "healthy", 3: "starting"},
                ),
                (
                    "Readiness gates progress",
                    "Old Pods scale down only as new Pods become ready.",
                    "Each new Pod must pass its readiness check before the old ReplicaSet shrinks. If new Pods "
                    "never become ready, the rollout stalls and the old version keeps handling traffic.",
                    [3, 4],
                    {3: "unhealthy", 2: "healthy"},
                ),
                (
                    "Undo restores the old ReplicaSet",
                    "The Deployment reports the stall; you run kubectl rollout undo.",
                    "After the progress deadline, the Deployment reports that the rollout has stalled but does "
                    "not revert. Rollout undo scales the previous ReplicaSet back up from the saved revision history.",
                    [2, 3],
                    {2: "healthy", 3: "complete", 4: "healthy"},
                ),
            ],
        },
    },
    "terraform providers resources data sources and modules": {
        "id": "terraform-building-blocks",
        "lesson": {
            "title": "Terraform building blocks: providers, resources, data sources and modules",
            "why": (
                "Every Terraform codebase is built from four pieces. Most real incidents come from the seams "
                "between them: an unpinned provider upgrade, a data source read at the wrong time, or a module "
                "whose internals someone reached into. Interviewers use these to tell apart people who have "
                "run `terraform apply` from people who can own a shared codebase."
            ),
            "what": (
                "**Providers** are plugins that talk to an API (AWS, Kubernetes, or even your local disk). "
                "**Resources** are objects Terraform creates, updates and destroys, and records in state. "
                "**Data sources** only read existing information. **Modules** are directories of `.tf` files "
                "that you call with inputs and whose outputs you use, so that code can be reused."
            ),
            "concepts": [
                {
                    "name": "Providers, versions and the lock file",
                    "body": (
                        "`required_providers` gives each provider a source such as `hashicorp/aws` and a version "
                        "constraint such as `~> 6.0`. `terraform init` selects versions and records them, with "
                        "checksums, in `.terraform.lock.hcl`; later runs reuse that selection. Commit the lock "
                        "file so upgrades go through review, and move within your constraints with "
                        "`terraform init -upgrade`. The lock file tracks providers only, not modules."
                    ),
                },
                {
                    "name": "Resources versus data sources",
                    "body": (
                        "A `resource` block is managed: Terraform plans create, update or replace actions and "
                        "stores the result in state. A `data` block is read-only: Terraform queries it during "
                        "planning, but defers the read to apply when an argument depends on a value not known "
                        "until apply. Use data sources to look up things you do not manage, such as an existing "
                        "VPC or AMI, and never to 'import' something you intend to own."
                    ),
                },
                {
                    "name": "Modules: inputs, outputs and versions",
                    "body": (
                        "Every configuration is a root module; a `module` block calls a child module from "
                        "`source`. Pass inputs as arguments and read results only through `module.<name>.<output>`, "
                        "never by reaching into its resources. `version` is available only for registry "
                        "modules. Because the lock file does not pin modules, a loose constraint can pull a "
                        "newer module release on a fresh `init`, so use an exact version where reproducibility "
                        "matters."
                    ),
                },
                {
                    "name": "Provider configurations and aliases",
                    "body": (
                        "A `provider` block configures a provider, for example a region. Add more configurations "
                        "with `alias` and select one per resource with `provider = aws.west`, or pass one into a "
                        "module with `providers = { aws = aws.west }`. The `version` argument inside a provider "
                        "block is deprecated; put versions in `required_providers`. Keep credentials out of "
                        "provider blocks and use environment, SSO or OIDC credentials instead."
                    ),
                },
            ],
            "e2e": [
                "You write configuration with `required_providers`, resources, data sources and module calls.",
                "`terraform init` downloads providers that satisfy the constraints and writes `.terraform.lock.hcl`.",
                "`terraform init` also installs child modules from their sources.",
                "`terraform validate` checks the configuration's syntax and internal consistency.",
                "`terraform plan` refreshes state, reads data sources and shows the difference from the desired configuration.",
                "`terraform apply` creates, updates or replaces resources in dependency order and records them in state.",
                "Outputs from modules and the root module expose selected values.",
                "`terraform destroy` removes the managed resources; data sources never delete anything.",
            ],
            "tasks": [
                {
                    "name": "Initialise providers and read the lock file",
                    "goal": "See exactly what `init` records and why it is committed.",
                    "steps": [
                        "Install Terraform (or OpenTofu, using `tofu` instead of `terraform`). No cloud account is needed.",
                        "In an empty folder, create `notes.txt` with any text, then save `main.tf`:\n"
                        + TF_ROOT,
                        "Run `terraform init` and open `.terraform.lock.hcl`: find the selected versions and the hashes.",
                        "Write one sentence on what would happen in CI if this file were not committed.",
                    ],
                    "minutes": 8,
                },
                {
                    "name": "Compare a resource and a data source",
                    "goal": "Tell managed objects from read-only lookups in a plan.",
                    "steps": [
                        "Run `terraform plan`: note which blocks are create actions and that the `data` block is only read.",
                        "`terraform apply`, then `terraform state list`: the lookup is listed as `data.local_file.notes`. Explain why `terraform destroy` will never delete `notes.txt`.",
                        "Change `length = 2` to `3` and plan again: which resources are replaced, and why does `local_file` follow?",
                        "Delete `out/hello.txt` by hand and plan again. Explain what Terraform proposes.",
                    ],
                    "minutes": 10,
                },
                {
                    "name": "Build and call a module",
                    "goal": "Pass inputs in and read outputs out.",
                    "steps": [
                        "Create the module and call it twice with `for_each`:\n" + TF_MODULE,
                        "Run `terraform init` again (new modules must be installed), then `terraform apply` and `terraform output messages`.",
                        "Explain why `version` cannot be added to this local `source`, and what you would use for a registry module.",
                    ],
                    "minutes": 12,
                },
                {
                    "name": "Fix the broken configuration",
                    "goal": "Diagnose the mistakes people make at the seams.",
                    "steps": [
                        'A teammate wrote `source = "hashicorp/randomm"`: what does `init` report, and why?',
                        'Another added `version = "1.0.0"` to a module whose source is `./modules/greeting`.',
                        "A third referenced a resource inside the child module directly from the root instead of an output.",
                        "A fourth deleted `.terraform.lock.hcl` to 'fix' a checksum error. For each, give the error or risk and the fix.",
                        "Finish with `terraform destroy` to remove the local files.",
                    ],
                    "minutes": 10,
                },
            ],
            "key_terms": [
                "Provider — plugin that implements resources and data sources for one API.",
                "`required_providers` — source address and version constraint per provider.",
                "`.terraform.lock.hcl` — records selected provider versions and checksums; commit it.",
                "Resource — managed object Terraform creates, updates, replaces and destroys.",
                "Data source — read-only lookup; may be deferred to apply if inputs are unknown.",
                "Module — directory of .tf files called with inputs and exposing outputs.",
                "Provider alias — an additional provider configuration selected with `provider =`.",
            ],
            "safety": (
                "The exercises use only the `random` and `local` providers, which never call a cloud API, so "
                "they are free and safe. If you try the same patterns with a cloud provider, use a sandbox "
                "account, read the plan before every apply and run `terraform destroy` afterwards."
            ),
            "cleanup": [
                "`terraform destroy` removes the local files created by the exercises.",
                "Delete the practice folder, including `.terraform/` and the state files.",
            ],
            "references": [
                "https://developer.hashicorp.com/terraform/language/files/dependency-lock",
                "https://developer.hashicorp.com/terraform/language/providers/requirements",
                "https://developer.hashicorp.com/terraform/language/data-sources",
                "https://developer.hashicorp.com/terraform/language/block/module",
                "https://developer.hashicorp.com/terraform/language/block/provider",
            ],
            "interview_question": (
                "After a routine pipeline run, `terraform plan` suddenly wants to replace several resources, "
                "although nobody changed the configuration. What could have changed between the two runs, "
                "and how would you design the codebase so this cannot happen silently?"
            ),
            "interview_points": [
                "Provider version drift: lock file missing, not committed, or `init -upgrade` in CI.",
                "Module version drift: a registry module with a loose constraint picked a newer release.",
                "A data source now returns a different value (for example the latest AMI).",
                "Real drift made outside Terraform, which the refresh detected.",
                "Controls: commit the lock file, exact module versions, reviewed plans, pinned lookups.",
            ],
        },
        "core": (
            "**Core idea:** four building blocks, and most bugs live at the seams between them.\n"
            "- **Provider**: plugin for an API. Pin it in `required_providers` (source + constraint). "
            "`terraform init` writes the selected version and checksums to `.terraform.lock.hcl`. "
            "Commit it; upgrade deliberately with `init -upgrade`.\n"
            "- **Resource**: managed. Planned, applied, recorded in state, destroyable.\n"
            "- **Data source**: read-only lookup, normally during plan. It is deferred to apply when an "
            "input is unknown until then.\n"
            "- **Module**: a directory you call with inputs; read results only via "
            "`module.<name>.<output>`. `version` works only for registry modules, and the lock file does "
            "not pin modules.\n"
            "- **Alias**: a second provider configuration (e.g. another region), selected with "
            "`provider = aws.west`.\n\n"
            "Today's exercises use the `random` and `local` providers: real Terraform, zero cloud cost."
        ),
        "architecture": {
            "title": "Terraform: from configuration to managed state",
            "pattern": "flow",
            "labels": [
                "Configuration (.tf)",
                "terraform init",
                "Providers + lock file",
                "Plan",
                "Apply + state",
                "Child module outputs",
            ],
            "connections": [
                (0, 1, "control"),
                (1, 2, "control"),
                (0, 3, "request"),
                (3, 4, "request"),
                (5, 3, "request"),
            ],
            "stages": [
                (
                    "Init selects providers",
                    "Init installs providers that satisfy constraints and records them in the lock file.",
                    "Terraform init reads required providers, installs matching versions and records the "
                    "selection with checksums in the dependency lock file. Later runs reuse that selection until "
                    "you upgrade deliberately.",
                    [0, 1],
                    {2: "complete"},
                ),
                (
                    "Plan reads, then compares",
                    "Data sources are read; resources are compared with state.",
                    "Plan refreshes state and reads data sources, unless their inputs are unknown until apply. "
                    "It then compares desired resources with recorded state and shows each create, update or replace.",
                    [2, 4],
                    {3: "waiting"},
                ),
                (
                    "Modules expose outputs",
                    "The root module uses a child module only through its outputs.",
                    "A child module receives inputs and exposes outputs. The root module uses those outputs, not "
                    "the module's internal resources, so the module can change safely behind its interface.",
                    [4],
                    {5: "healthy", 3: "healthy"},
                ),
                (
                    "Apply records state",
                    "Apply changes resources in dependency order and saves the result.",
                    "Apply performs the reviewed plan in dependency order and records every managed resource in "
                    "state. Data sources are never managed, so destroy never deletes what they read.",
                    [3],
                    {4: "complete"},
                ),
            ],
        },
    },
    "github actions permissions oidc secrets and runners": {
        "id": "gha-security",
        "lesson": {
            "title": "GitHub Actions security: permissions, OIDC, secrets and runners",
            "why": (
                "A CI system holds the keys to production. Most real Actions incidents come from a few "
                "patterns: over-privileged tokens, long-lived cloud keys stored as secrets, untrusted pull "
                "request code running with secrets, and mutable third-party actions. Knowing the exact rules "
                "is what separates 'I use GitHub Actions' from 'I can secure a delivery pipeline'."
            ),
            "what": (
                "Each job gets an automatic `GITHUB_TOKEN` whose access you set with `permissions:`. Instead "
                "of storing cloud keys, a job can request a short-lived OpenID Connect (OIDC) token that a "
                "cloud provider exchanges for temporary credentials. Secrets are encrypted values with strict "
                "rules about where they are available, and runners are the machines that execute your jobs."
            ),
            "concepts": [
                {
                    "name": "GITHUB_TOKEN and permissions",
                    "body": (
                        "Before each job, GitHub creates an installation token limited to the repository; it "
                        "expires when the job finishes or reaches its maximum lifetime. If you specify any "
                        "permission, every permission you do not list becomes `none`; `permissions: {}` "
                        "removes all. Set `contents: read` at the top and grant writes such as "
                        "`pull-requests: write` only on the job that needs them. Events created with "
                        "`GITHUB_TOKEN` do not start new workflow runs (except manual dispatch events)."
                    ),
                },
                {
                    "name": "OIDC: short-lived cloud credentials",
                    "body": (
                        "`permissions: id-token: write` lets a job request a signed JWT; it grants no write "
                        "access to repository content. For AWS, the IAM OIDC provider is "
                        "`https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com` for "
                        "the official action. The role's trust policy must check `aud` and `sub`, for example "
                        "`repo:OWNER/REPO:ref:refs/heads/main`. When a job uses an environment, `sub` becomes "
                        "`repo:OWNER/REPO:environment:prod`. Avoid broad wildcards in `sub`."
                    ),
                },
                {
                    "name": "Secrets and untrusted input",
                    "body": (
                        "Except for `GITHUB_TOKEN`, secrets are not passed to workflows triggered from forks or "
                        "by Dependabot, and not automatically to reusable workflows. Redaction relies on exact "
                        "matches, so never store structured data such as a JSON blob as one secret; use "
                        "`::add-mask::` for derived values. Put deployment secrets behind an environment with "
                        "required reviewers. Pass untrusted values such as a pull request title into scripts "
                        "through `env:` variables, never inline `${{ }}` in `run:`."
                    ),
                },
                {
                    "name": "Runners and supply chain",
                    "body": (
                        "GitHub-hosted runners are fresh, isolated VMs for each job. Self-hosted runners give "
                        "no such guarantee and, per GitHub, should almost never be used for public repositories. "
                        "Pinning a third-party action to a full-length commit SHA is the only way to use it as "
                        "an immutable release. `pull_request_target` runs with the base repository's token, "
                        "secrets and cache access, so executing fork code there is a 'pwn request'. Since "
                        "June 2026 actions/checkout refuses to fetch a fork pull request's head or merge commit "
                        "in that context by default, but fetching it another way (`git`, `gh`) is still unsafe."
                    ),
                },
            ],
            "e2e": [
                "A push to main or a manual dispatch starts the deploy workflow.",
                "The job declares `permissions: contents: read` and `id-token: write`, and optionally an environment with reviewers.",
                "The runner requests an OIDC JWT from GitHub with audience `sts.amazonaws.com`.",
                "configure-aws-credentials calls `sts:AssumeRoleWithWebIdentity` with that JWT.",
                "AWS checks the signature, issuer, `aud` and `sub` against the role's trust policy.",
                "STS returns temporary credentials for the role; no long-lived key exists anywhere.",
                "Later steps call AWS with those credentials and only the role's permissions.",
                "The credentials and the job's GITHUB_TOKEN expire; the hosted runner VM is discarded.",
            ],
            "tasks": [
                {
                    "name": "Tighten a workflow's permissions",
                    "goal": "Apply least privilege to GITHUB_TOKEN.",
                    "steps": [
                        "Take any workflow without a `permissions:` block and add `permissions: contents: read` at the top level.",
                        "One job comments on pull requests: grant `pull-requests: write` on that job only.",
                        "Explain what happens to `issues` and `packages` access once you list any permission.",
                        "Explain why `permissions: {}` is the right choice for a job that needs no API access.",
                    ],
                    "minutes": 8,
                },
                {
                    "name": "Inspect your OIDC claims without a cloud account",
                    "goal": "See the exact `sub` and `aud` a cloud trust policy would check.",
                    "steps": [
                        "In a public practice repository (GitHub-hosted runners are free there), add:\n"
                        + GHA_CLAIMS,
                        "Run it from the Actions tab. The job prints only claims, never the token itself.",
                        "Add `environment: practice` to the job, run again and compare how `sub` changed.",
                        "Delete the workflow when finished.",
                    ],
                    "minutes": 12,
                },
                {
                    "name": "Write and test a trust policy on paper",
                    "goal": "Limit which workflows can assume a cloud role.",
                    "steps": [
                        "Read this AWS role trust policy:\n" + GHA_TRUST,
                        "Can a workflow on branch `feature/x` assume the role? A job using `environment: prod`? Explain using the `sub` values you printed.",
                        "Rewrite the condition so only jobs in the `prod` environment can assume it. The job that uses the role looks like this:\n"
                        + GHA_DEPLOY,
                        "Explain what `repo:OWNER/*` in a `StringLike` condition would allow, and why that is risky.",
                    ],
                    "minutes": 10,
                },
                {
                    "name": "Review a risky workflow",
                    "goal": "Find the supply-chain and secret-handling defects.",
                    "steps": [
                        "It runs on `pull_request_target`, checks out the pull request's head commit and runs `npm test` with a deploy secret in `env`.",
                        'A step runs `echo "${{ github.event.pull_request.title }}"` inline in `run:`.',
                        "A third-party action is referenced by a moving major tag, and the job uses a self-hosted runner in a public repository.",
                        "Cloud credentials are stored as one JSON blob secret.",
                        "For each defect, describe the attack and the fix.",
                    ],
                    "minutes": 10,
                },
            ],
            "key_terms": [
                "GITHUB_TOKEN — per-job installation token scoped to the repository; access set by `permissions:`.",
                "`id-token: write` — lets a job request an OIDC JWT; grants no repository write access.",
                "`sub` claim — identifies repository and ref or environment; the key trust-policy condition.",
                "`aud` claim — intended audience; `sts.amazonaws.com` for the official AWS action.",
                "Environment — deployment target with protection rules and its own secrets.",
                "Commit-SHA pinning — the only immutable way to reference an action.",
                "`pull_request_target` — runs in the base repository context with its secrets; never run fork code.",
            ],
            "safety": (
                "Exercises 1, 3 and 4 are paper exercises and exercise 2 needs only a free public GitHub "
                "repository. Never print tokens or secrets, even in a practice repository. If you later create "
                "a real AWS role, use a sandbox account and a least-privilege permission policy."
            ),
            "cleanup": [
                "Delete the practice workflow or repository.",
                "If you created an AWS OIDC provider or role while experimenting, delete them when finished.",
            ],
            "references": [
                "https://docs.github.com/en/actions/concepts/security/github_token",
                "https://docs.github.com/en/actions/concepts/security/openid-connect",
                "https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws",
                "https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets",
                "https://docs.github.com/en/actions/reference/security/secure-use",
            ],
            "interview_question": (
                "Your company stores an AWS access key as a repository secret so GitHub Actions can deploy. "
                "Security asks you to remove it. Design the replacement, including exactly what AWS checks "
                "and how you stop a feature branch or a fork from deploying to production."
            ),
            "interview_points": [
                "OIDC federation: IAM OIDC provider plus a role; `id-token: write` in the job.",
                "Trust policy checks `aud` and an exact `sub`, ideally the prod environment.",
                "Environment with required reviewers, deploying only from main.",
                "Least-privilege role permissions and a top-level `contents: read` default.",
                "Forks get no secrets and cannot mint a matching `sub`; never use pull_request_target to run fork code.",
            ],
        },
        "core": (
            "**Core idea:** give every job the least access, for the shortest time.\n"
            "- `permissions:` sets GITHUB_TOKEN access. List any permission and all others become `none`. "
            "Default to `contents: read`; add writes per job.\n"
            "- **OIDC** replaces stored cloud keys. `id-token: write` lets the job request a signed JWT, "
            "and AWS STS swaps it for temporary credentials. The trust policy must check `aud` "
            "(`sts.amazonaws.com`) and an exact `sub`, e.g. `repo:OWNER/REPO:environment:prod`.\n"
            "- **Secrets** are not given to fork or Dependabot runs. Don't store a JSON blob as one secret: "
            "redaction needs exact matches. Pass untrusted text via `env:`, not inline `${{ }}`.\n"
            "- **Runners and actions**: hosted runners are fresh VMs. Avoid self-hosted runners on public "
            "repos. Pin third-party actions to a full commit SHA, and never run fork code under "
            "`pull_request_target`.\n\n"
            "Today's exercises need only a free public GitHub repository."
        ),
        "architecture": {
            "title": "GitHub Actions OIDC deploy without stored keys",
            "pattern": "flow",
            "labels": [
                "Deploy job (id-token: write)",
                "GitHub OIDC provider",
                "AWS STS",
                "Role trust policy",
                "AWS resources",
            ],
            "connections": [(0, 1, "request"), (0, 2, "request"), (2, 3, "control"), (0, 4, "request")],
            "stages": [
                (
                    "Request an identity token",
                    "The job asks GitHub for a signed JWT for audience sts.amazonaws.com.",
                    "The deploy job has permission to request an identity token. GitHub's OIDC provider issues a "
                    "short-lived signed token whose subject names the repository and branch or environment.",
                    [0],
                    {1: "complete"},
                ),
                (
                    "Exchange it with AWS",
                    "The official action calls AssumeRoleWithWebIdentity with the token.",
                    "The configure credentials action sends the token to AWS security token service and asks to "
                    "assume one specific role. No access key is stored in GitHub at any point.",
                    [1],
                    {2: "waiting"},
                ),
                (
                    "Trust policy decides",
                    "AWS checks issuer, signature, audience and the exact subject claim.",
                    "AWS validates the token and compares the audience and subject with the role's trust policy. "
                    "A feature branch or fork produces a different subject, so the request is denied.",
                    [2],
                    {3: "healthy", 2: "healthy"},
                ),
                (
                    "Temporary, least-privilege access",
                    "Later steps use short-lived credentials limited by the role's policy.",
                    "Security token service returns temporary credentials. Later steps can call only what the "
                    "role's permission policy allows, and the credentials expire on their own.",
                    [3],
                    {4: "healthy"},
                ),
            ],
        },
    },
}


def normalize(topic: str) -> str:
    import re

    return " ".join(re.sub(r"[^a-z0-9]+", " ", (topic or "").casefold()).split())


def reviewed_entry(topic: str):
    return REVIEWED.get(normalize(topic))


def reviewed_lesson(topic: str):
    entry = reviewed_entry(topic)
    if entry is None:
        return None
    return {**entry["lesson"], "reviewed_at": REVIEWED_AT}
