"""Hands-on local labs for the non-AWS module catalog."""

from skillcoach.lab_models import Lab, LocalRoute, Step

MODULE_LABS: tuple[Lab, ...] = (
    Lab(
        id="fault-domain-calculator",
        title="Model fault-domain blast radius with Python",
        topics=("Regions availability zones and fault domains",),
        minutes=25,
        goal="Compare single-zone and multi-zone placement so a zone failure does not surprise your design.",
        references=(
            "https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html",
            "https://learn.microsoft.com/en-us/azure/reliability/availability-zones-overview",
        ),
        scenario=(
            Step(
                "A small internal API runs on two identical VMs in one availability zone. The zone has a power event. What should you expect?",
                (
                    "Both VMs can be lost because they share the same fault domain.",
                    "One VM always stays up because two instances are automatically isolated even when placed together.",
                    "The cloud provider automatically moves them to another region.",
                    "Only storage fails; compute is independent of zones.",
                ),
                "Multiple instances help only when they are spread across independent failure domains. Two VMs in one zone still share a zone-level dependency.",
            ),
            Step(
                "The team wants a higher availability target without changing regions. Which first design change best reduces zone blast radius?",
                (
                    "Place instances and data replicas across at least two zones supported by the service.",
                    "Use larger VM sizes in the same zone.",
                    "Add a nightly backup in the same zone.",
                    "Put the database and app on the same host to reduce latency.",
                ),
                "Zone spreading reduces common-mode zone failure. Larger instances may improve capacity, but they do not separate failure domains.",
            ),
            Step(
                "A dependency is available only in one zone. What is the honest architecture review outcome?",
                (
                    "Record it as a single-zone dependency and align the SLO or mitigation with that risk.",
                    "Ignore it because the application tier is multi-zone.",
                    "Claim the workload is zone redundant if most resources are spread.",
                    "Move only DNS to another zone and consider it fixed.",
                ),
                "Reliability depends on the weakest critical dependency. Multi-zone front ends cannot hide a required single-zone backend.",
            ),
            Step(
                "A region-wide outage is in scope for disaster recovery. What does a multi-zone design in one region provide?",
                (
                    "Protection from many zone failures, but not from losing the whole region.",
                    "Full regional disaster recovery with no extra design.",
                    "Automatic active-active behavior in every other region.",
                    "No benefit compared with one zone.",
                ),
                "Availability zones are independent locations inside a region. Regional DR needs separate regional recovery choices.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 standard library",
            steps=(
                "Create a workspace: mkdir -p lab-fault-domains && cd lab-fault-domains",
                "Create sim.py with a services dict mapping api to zones ['z1','z2'] and db to ['z1']; add a failed='z1' variable.",
                "Run python sim.py to print which components remain after removing the failed zone; observe db is unavailable.",
                "Edit the db zones to ['z1','z2'] and rerun python sim.py; observe both components survive a single-zone failure.",
                "Change failed to 'region' and make the script mark all zones down; observe why multi-region recovery is a different design.",
            ),
            cleanup=("cd .. && rm -rf lab-fault-domains",),
        ),
    ),
    Lab(
        id="process-signal-triage",
        title="Triage a runaway process with ps and signals",
        topics=("Linux processes signals and systemd",),
        minutes=25,
        goal="Find a noisy Linux process, request graceful shutdown, and know when stronger signals are justified.",
        references=(
            "https://man7.org/linux/man-pages/man1/ps.1.html",
            "https://man7.org/linux/man-pages/man1/kill.1.html",
        ),
        scenario=(
            Step(
                "A Python worker is using unexpected CPU. Before stopping it, what should you collect first?",
                (
                    "Use ps to capture PID, command, CPU, memory, and parent process.",
                    "Send SIGKILL immediately so logs stay clean.",
                    "Delete the executable and wait for the process to exit.",
                    "Reboot the host before checking process details.",
                ),
                "A snapshot with ps preserves evidence and identifies the process tree. SIGKILL first is tempting but prevents graceful cleanup and loses context.",
            ),
            Step(
                "The process should flush state on shutdown. Which signal is the normal first request?",
                (
                    "SIGTERM, because it asks the process to terminate and can be handled.",
                    "SIGKILL, because every service handles it gracefully.",
                    "SIGSTOP, because it writes application checkpoints.",
                    "SIGHUP, because it always means shutdown.",
                ),
                "kill sends SIGTERM by default, giving programs a chance to clean up. SIGKILL cannot be caught or handled.",
            ),
            Step(
                "After SIGTERM, the process stays alive and ignores repeated requests. What is the careful next step?",
                (
                    "Confirm the PID is still the same process, then escalate if policy allows.",
                    "Reuse the old PID hours later without checking it.",
                    "Kill every Python process on the host.",
                    "Change file permissions under /proc to force exit.",
                ),
                "PIDs can be reused, so verify the target before escalation. Killing by language or name risks unrelated workloads.",
            ),
            Step(
                "The service is managed by systemd on a normal Linux host. Which command gives service-aware status?",
                (
                    "systemctl status service-name",
                    "ps -ef only; systemd has no service state.",
                    "kill -l service-name",
                    "cat /etc/passwd service-name",
                ),
                "systemctl understands units, restarts, and recent state. ps is useful process evidence, but not a full service-manager view.",
            ),
        ),
        local=LocalRoute(
            tools="Bash or WSL with coreutils; systemd optional",
            steps=(
                "Create a sandbox: mkdir -p lab-linux-signals && cd lab-linux-signals",
                "Start a harmless process: python3 -c 'import time; time.sleep(300)' & echo $! > pid.txt",
                "Run ps -o pid,ppid,stat,pcpu,pmem,cmd -p $(cat pid.txt) and note the PID and command.",
                "Run kill -TERM $(cat pid.txt); then ps -p $(cat pid.txt) || echo stopped and observe graceful termination.",
                "If your environment has systemd, run systemctl --user status; in WSL without systemd, note that systemctl may be unavailable.",
            ),
            cleanup=(
                "kill -TERM $(cat pid.txt) 2>/dev/null || true",
                "cd .. && rm -rf lab-linux-signals",
            ),
        ),
    ),
    Lab(
        id="bisect-broken-script",
        title="Find a regression with git bisect",
        topics=("Git bisect revert and incident recovery",),
        minutes=30,
        goal="Use git bisect to locate a bad commit, then choose a safe recovery action.",
        references=("https://git-scm.com/docs/git-bisect", "https://git-scm.com/docs/git-revert"),
        scenario=(
            Step(
                "A test passed last week and fails today. You know one good commit and the current bad commit. What command sequence starts the search?",
                (
                    "git bisect start; git bisect bad; git bisect good <known-good>",
                    "git revert HEAD; git bisect good HEAD",
                    "git reset --hard main; git bisect skip",
                    "git branch -D main; git bisect start",
                ),
                "bisect needs one bad and one good boundary. Reverting first changes the evidence and can hide the commit you need to find.",
            ),
            Step(
                "At each checked-out commit, what should drive the good or bad answer?",
                (
                    "Run the smallest reliable test that reproduces the symptom.",
                    "Judge by the commit author or message style.",
                    "Mark merge commits bad and normal commits good.",
                    "Use file size changes as the signal.",
                ),
                "Bisect is only as reliable as the test oracle. Metadata may suggest a culprit but cannot prove the regression.",
            ),
            Step(
                "bisect identifies a public commit on main as the first bad commit. What is usually safer than rewriting main history?",
                (
                    "Create a new commit with git revert <bad-commit> after reviewing impact.",
                    "Run git reset --hard before the bad commit on main and force push.",
                    "Delete the repository and reclone.",
                    "Tag the bad commit as stable.",
                ),
                "git revert records an inverse change without rewriting shared history. Force pushing main can disrupt everyone else.",
            ),
            Step(
                "The bisect lands on a commit where the test cannot run because dependencies are missing. What should you do?",
                (
                    "Use git bisect skip for that commit and continue.",
                    "Mark it good so bisect finishes faster.",
                    "Mark it bad because broken setup is always the bug.",
                    "Stop and assume the previous commit is guilty.",
                ),
                "skip tells Git that this commit cannot classify the bug. Guessing good or bad can point bisect at the wrong change.",
            ),
        ),
        local=LocalRoute(
            tools="Git and Python 3 standard library",
            steps=(
                "Create a repo: mkdir -p lab-git-bisect && cd lab-git-bisect && git init",
                "Write calc.py returning 2+2 and test_calc.py asserting the output is 4; run git add . && git -c user.name=SkillCoach -c user.email=sc@example.com commit -m good.",
                "Run echo notes > README.md && git add . && git -c user.name=SkillCoach -c user.email=sc@example.com commit -m docs; change calc.py to return 5 and commit as bad.",
                "Run git bisect start; git bisect bad HEAD; git bisect good HEAD~2.",
                "Run python -m unittest test_calc.py, mark the commit bad or good as instructed, then run git bisect reset.",
                "Practice recovery with git revert --no-edit HEAD, rerun the test, and inspect git log --oneline.",
            ),
            cleanup=("cd .. && rm -rf lab-git-bisect",),
        ),
    ),
    Lab(
        id="json-cli-validator",
        title="Build a JSON-checking Python CLI",
        topics=(
            "Python CLI automation and structured logging",
            "JSON YAML configuration and schema validation",
        ),
        minutes=30,
        goal="Create a small CLI that validates JSON input and logs actionable errors without leaking data.",
        references=(
            "https://docs.python.org/3/library/argparse.html",
            "https://docs.python.org/3/library/logging.html",
        ),
        scenario=(
            Step(
                "An automation script needs a required config path and an optional --verbose flag. Which standard library module should parse that CLI?",
                (
                    "argparse, because it defines arguments, help, types, and exits consistently.",
                    "logging, because it parses every command-line option before it writes structured application logs.",
                    "csv, because flags are comma-separated values.",
                    "subprocess, because all arguments must be shell commands.",
                ),
                "argparse is the CLI parser in the standard library. logging records events but does not define command-line interfaces.",
            ),
            Step(
                "The config file is malformed JSON. What should the CLI do for automation callers?",
                (
                    "Exit non-zero and log a concise error with the file name and parse problem.",
                    "Print a stack trace and still exit 0.",
                    "Silently create an empty default config.",
                    "Upload the file to a service for repair.",
                ),
                "Automation depends on exit status. A clear non-zero failure is safer than masking bad configuration.",
            ),
            Step(
                "The config contains a field named token. What should structured logs avoid?",
                (
                    "Logging the secret value; log the key name or validation category instead.",
                    "Logging timestamps, because timestamps are secrets.",
                    "Using levels such as INFO or ERROR.",
                    "Writing any message before successful validation.",
                ),
                "Logs should be useful but not expose secrets. Key names and error categories usually provide enough context.",
            ),
            Step(
                "A required key is missing. Which behavior best supports idempotent automation?",
                (
                    "Report the missing key and leave the input file unchanged.",
                    "Guess a value and write it into the config.",
                    "Delete the file so the next run starts fresh.",
                    "Retry forever until a human edits the file.",
                ),
                "Validation should not mutate inputs unexpectedly. Guessing can create hidden configuration drift.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3.12 standard library",
            steps=(
                "Create a sandbox: mkdir -p lab-json-cli && cd lab-json-cli",
                "Create validate.py using argparse for config, json.load for parsing, and logging.basicConfig(level=logging.INFO).",
                "Make the script require service and owner keys; on JSONDecodeError or missing keys, log an error and exit with status 2.",
                "Run python validate.py missing.json and observe a non-zero failure.",
                'Create config.json with {"service":"api","owner":"team-a","token":"demo"}; run python validate.py config.json.',
                "Edit the script so it logs token_present=true without printing the token value.",
            ),
            cleanup=("cd .. && rm -rf lab-json-cli",),
        ),
    ),
    Lab(
        id="bicep-offline-lint",
        title="Validate an Azure Bicep template offline",
        topics=("Azure Bicep ARM and deployment operations",),
        minutes=30,
        goal="Compile and lint a Bicep template locally without signing in or deploying anything.",
        references=(
            "https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview",
            "https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/bicep-cli",
            "https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/linter",
        ),
        scenario=(
            Step(
                "A teammate asks you to test a Bicep file but you must not create cloud resources. Which action is appropriate?",
                (
                    "Run bicep build or az bicep build locally and inspect the generated ARM JSON.",
                    "Run az deployment group create against production because validation must use real resources.",
                    "Paste credentials into the template so validation can authenticate.",
                    "Disable the linter because it requires deployment.",
                ),
                "Bicep build is a local compilation step. A deployment command would contact Azure and may create resources.",
            ),
            Step(
                "The linter warns that a parameter has an insecure default. What is the best response?",
                (
                    "Remove the secret-like default and pass values securely at deployment time.",
                    "Rename the parameter so the linter stops recognizing it.",
                    "Commit the real secret as the default value.",
                    "Ignore all linter warnings because build succeeded.",
                ),
                "The linter catches risky patterns before deployment. Renaming to hide intent does not reduce the secret-handling risk.",
            ),
            Step(
                "main.bicep compiles into main.json. What has been proven?",
                (
                    "The Bicep syntax and type model can be translated to an ARM template.",
                    "Azure accepted and created the resources.",
                    "All naming rules for every region are guaranteed.",
                    "The template is free to run in any subscription.",
                ),
                "Build proves local compilation, not a live deployment. Provider validation and policy checks happen later.",
            ),
            Step(
                "You need to compare a generated ARM template in code review. Which file should be treated as the source of truth?",
                (
                    "The Bicep source, with generated JSON reviewed only when useful.",
                    "Only the generated JSON, deleting Bicep after every build.",
                    "A screenshot of the Azure portal.",
                    "The deployment output from someone else's subscription.",
                ),
                "Bicep is the authored source. Generated JSON is derived and can help review, but it should not replace the source file.",
            ),
        ),
        local=LocalRoute(
            tools="Bicep CLI or Azure CLI with az bicep; no Azure login required",
            steps=(
                "Create a sandbox: mkdir -p lab-azure-bicep && cd lab-azure-bicep",
                "Create main.bicep with targetScope = 'resourceGroup' and a storage account resource using a parameterized name; do not deploy it.",
                "Run bicep build main.bicep or az bicep build --file main.bicep; observe main.json is generated locally.",
                "Add a bad secret-like default such as param adminPassword string = 'Password123!' and run bicep lint main.bicep if available.",
                "Remove the insecure default, rebuild, and note that no Azure account, credentials, or charges were used.",
            ),
            cleanup=("cd .. && rm -rf lab-azure-bicep",),
        ),
    ),
    Lab(
        id="pubsub-emulator-flow",
        title="Exercise Pub/Sub flow on the local emulator",
        topics=("Google Pub Sub delivery ordering and retries",),
        minutes=35,
        goal="Publish and pull a message against the local Pub/Sub emulator without a Google Cloud project.",
        references=(
            "https://cloud.google.com/pubsub/docs/emulator",
            "https://cloud.google.com/pubsub/docs/publish-receive-messages-client-library",
        ),
        scenario=(
            Step(
                "You need to test Pub/Sub message handling on a laptop with no cloud credentials. What should you use?",
                (
                    "The Pub/Sub emulator and an emulator host variable.",
                    "A production topic with a throwaway name because deleting it later removes all risk.",
                    "A public bucket as a message queue.",
                    "A service account key copied from another project.",
                ),
                "The emulator is designed for local development and avoids production calls. Borrowed credentials create security and audit risks.",
            ),
            Step(
                "Your client accidentally ignores the emulator environment variable. What is the risk?",
                (
                    "It may try to contact the real Pub/Sub service instead of localhost.",
                    "It will automatically create an emulator topic in every region.",
                    "Messages will be encrypted twice and become unreadable.",
                    "The emulator will publish to production on your behalf.",
                ),
                "Clients must point at the emulator endpoint. Without that, normal client behavior may target the live service.",
            ),
            Step(
                "A pulled message is not acknowledged before the deadline. What behavior should your handler tolerate?",
                (
                    "The message can be delivered again, so processing should be idempotent.",
                    "The message is permanently deleted.",
                    "The topic is disabled until manual repair.",
                    "All later messages are discarded.",
                ),
                "Pub/Sub is at-least-once unless exactly-once features are specifically used. Handlers should tolerate duplicate delivery.",
            ),
            Step(
                "A test requires strict order for related events. What design should you check before relying on observed order?",
                (
                    "Use ordering keys and verify the feature is enabled for the publisher and subscription path.",
                    "Assume pull order is always publish order.",
                    "Create more subscriptions to force ordering.",
                    "Shorten the ack deadline to sort messages.",
                ),
                "Ordering requires explicit ordering-key support. More subscribers can increase parallelism, not guarantee order.",
            ),
        ),
        local=LocalRoute(
            tools="Google Cloud CLI Pub/Sub emulator; Python 3 standard library",
            steps=(
                "Create a sandbox: mkdir -p lab-gcp-pubsub && cd lab-gcp-pubsub; no cloud project is deployed and no charges occur.",
                "Start the emulator in one terminal: gcloud beta emulators pubsub start --host-port=127.0.0.1:8085",
                "In another terminal run gcloud beta emulators pubsub env-init and export the printed PUBSUB_EMULATOR_HOST value.",
                "Use curl or a small Python urllib script to call the emulator REST endpoint to create a topic and subscription under a fake project id.",
                "Publish one JSON message, pull it, acknowledge it, and observe all activity stays on localhost.",
            ),
            cleanup=("Stop the emulator with Ctrl+C", "cd .. && rm -rf lab-gcp-pubsub"),
        ),
    ),
    Lab(
        id="multistage-image-volume",
        title="Shrink a Docker image and persist data",
        topics=(
            "Docker images layers build cache and multi-stage builds",
            "Container storage volumes and data persistence",
        ),
        minutes=35,
        goal="Use a multi-stage Dockerfile and a named volume to separate image contents from runtime data.",
        references=(
            "https://docs.docker.com/build/building/multi-stage/",
            "https://docs.docker.com/engine/storage/volumes/",
            "https://docs.docker.com/reference/dockerfile/",
        ),
        scenario=(
            Step(
                "A final image contains compilers and test fixtures only needed during build. What Dockerfile pattern addresses this?",
                (
                    "Use a multi-stage build and copy only the runtime artifact into the final stage.",
                    "Run apt clean and keep the compiler in the final stage.",
                    "Mount the Docker socket inside the image.",
                    "Store build tools in a named volume.",
                ),
                "Multi-stage builds keep build-only tools out of the runtime image. Cleaning caches helps size but does not remove unnecessary packages.",
            ),
            Step(
                "A container writes user uploads inside its writable layer. What happens when the container is removed?",
                (
                    "The layer is removed with the container, so data should be in a volume if it must persist.",
                    "Docker automatically moves the files into the image.",
                    "The files become host environment variables.",
                    "The data is replicated to every image tag.",
                ),
                "Container layers are ephemeral. Docker volumes are the managed mechanism for persistent container data.",
            ),
            Step(
                "You need repeatable rebuilds after changing only application code. What Dockerfile ordering helps cache reuse?",
                (
                    "Copy dependency manifests before copying frequently changing source files.",
                    "Put COPY . . as the first instruction in every stage.",
                    "Disable the build cache for all local builds.",
                    "Install dependencies after the CMD instruction.",
                ),
                "Layer cache keys include prior instructions and file contents. Copying stable manifests first avoids reinstalling dependencies for every source edit.",
            ),
            Step(
                "The app must run as a non-root user in the final image. Which choice supports that goal?",
                (
                    "Create or select a non-root user and set USER in the runtime stage.",
                    "Run the build stage as root and assume the final stage inherits nothing.",
                    "Publish the container port only on localhost.",
                    "Use a named volume for /root.",
                ),
                "USER controls the runtime identity in an image stage. Port binding and volumes do not change the process user.",
            ),
        ),
        local=LocalRoute(
            tools="Docker or Podman",
            steps=(
                "Create a sandbox: mkdir -p lab-docker-multistage && cd lab-docker-multistage",
                "Create app.py that appends a line to /data/events.txt and prints the file contents.",
                "Create a Dockerfile with a builder stage that byte-compiles app.py and a final python:3-slim stage that copies app.py, creates /data, and sets CMD.",
                "Run docker build -t skillcoach/multistage-lab . and note the final image uses only the runtime stage.",
                "Run docker volume create sc-lab-data; docker run --rm -v sc-lab-data:/data skillcoach/multistage-lab twice and observe data persists.",
            ),
            cleanup=(
                "docker volume rm sc-lab-data 2>/dev/null || true",
                "docker image rm skillcoach/multistage-lab 2>/dev/null || true",
                "cd .. && rm -rf lab-docker-multistage",
            ),
        ),
    ),
    Lab(
        id="probe-failing-pod",
        title="Debug a failing Kubernetes readiness probe",
        topics=(
            "Kubernetes readiness liveness and startup probes",
            "Kubernetes troubleshooting events logs and ephemeral containers",
        ),
        minutes=40,
        goal="Use kubectl events, logs, and probe configuration to explain why a pod is not ready.",
        references=(
            "https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/",
            "https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/",
            "https://kind.sigs.k8s.io/docs/user/quick-start/",
        ),
        scenario=(
            Step(
                "A Deployment shows AVAILABLE 0 even though a pod is Running. What should you inspect first?",
                (
                    "kubectl describe pod to see readiness probe failures and events.",
                    "Delete the namespace immediately and recreate every workload so probe history is erased.",
                    "Increase replicas until one becomes ready by chance.",
                    "Disable all probes permanently.",
                ),
                "describe shows conditions and probe events. Scaling or removing probes can hide the failure instead of diagnosing it.",
            ),
            Step(
                "The readiness probe checks /ready but the app serves /healthz. What is the correct fix?",
                (
                    "Change the readinessProbe path to the endpoint that reports readiness.",
                    "Change it to a liveness probe only.",
                    "Set initialDelaySeconds to one hour.",
                    "Remove the Service selector.",
                ),
                "Readiness should match the app's readiness endpoint. Long delays or selector changes avoid traffic but do not make the probe meaningful.",
            ),
            Step(
                "The app needs 90 seconds to warm its cache and liveness kills it at 30 seconds. What probe pattern helps?",
                (
                    "Add a startupProbe so liveness waits until startup succeeds.",
                    "Use readinessProbe to restart the container.",
                    "Set failureThreshold to zero.",
                    "Replace probes with a NodePort service.",
                ),
                "startupProbe gates liveness during slow startup. Readiness controls traffic, not restarts.",
            ),
            Step(
                "A minimal container lacks curl and shell tools. You need live network debugging. What Kubernetes feature can help?",
                (
                    "Use kubectl debug with an ephemeral container if policy allows it.",
                    "Install packages by editing the running image layer.",
                    "Copy host binaries into every node.",
                    "Store credentials in an environment variable for curl.",
                ),
                "Ephemeral containers are intended for debugging running pods. Modifying images or adding secrets at debug time creates risk and drift.",
            ),
        ),
        local=LocalRoute(
            tools="Docker or Podman; kind; kubectl",
            steps=(
                "Create a local cluster: kind create cluster --name sc-probes",
                "Apply a Deployment using nginx with a readinessProbe path /missing on port 80.",
                "Run kubectl get pods and observe the pod Running but not Ready.",
                "Run kubectl describe pod -l app=sc-probe and find readiness probe HTTP 404 events.",
                "Patch or reapply the Deployment with readinessProbe path / and wait for kubectl rollout status deploy/sc-probe.",
                "Optionally run kubectl logs deploy/sc-probe to connect probe results with container logs.",
            ),
            cleanup=("kind delete cluster --name sc-probes",),
        ),
    ),
    Lab(
        id="tofu-local-drift",
        title="Detect local IaC drift with OpenTofu",
        topics=(
            "OpenTofu infrastructure workflows and compatibility",
            "Terraform state locking backends and drift",
        ),
        minutes=35,
        goal="Plan and apply a local-only resource, then detect drift without touching any cloud provider.",
        references=(
            "https://opentofu.org/docs/language/resources/",
            "https://developer.hashicorp.com/terraform/language/resources",
            "https://developer.hashicorp.com/terraform/language/state",
        ),
        scenario=(
            Step(
                "A plan shows one local file will be created. What should happen before apply in a reviewed workflow?",
                (
                    "Review the plan output and confirm it matches the intended change.",
                    "Apply immediately because local resources are harmless and never require review.",
                    "Delete the state file to make the plan smaller.",
                    "Commit provider credentials into variables.",
                ),
                "The plan is the review point for intended changes. Local resources are safer but still can change files and state.",
            ),
            Step(
                "Someone edits the managed file outside OpenTofu. What command detects the drift in normal workflow?",
                (
                    "tofu plan or terraform plan, because it compares configuration, state, and real objects.",
                    "git status only, because state is not involved.",
                    "tofu fmt, because formatting refreshes resources.",
                    "rm terraform.tfstate, because drift disappears when state is gone.",
                ),
                "Plan refreshes and compares managed objects. Formatting only changes style, and deleting state loses tracking.",
            ),
            Step(
                "A resource B reads a value from resource A. How should the dependency usually be expressed?",
                (
                    "Reference A's attribute from B so the graph captures the dependency.",
                    "Rely on the order blocks appear in the file.",
                    "Add a sleep command before B.",
                    "Run apply twice every time.",
                ),
                "References create graph edges. File order and sleeps are brittle and do not express intent.",
            ),
            Step(
                "A plan wants to replace a resource after a harmless metadata edit. What is the safest next action?",
                (
                    "Understand why replacement is required before applying.",
                    "Approve because all replacements are free.",
                    "Delete state so the replacement is hidden.",
                    "Disable planning in CI.",
                ),
                "Replacement can cause downtime or data loss depending on the resource. Review the reason rather than hiding it.",
            ),
        ),
        local=LocalRoute(
            tools="OpenTofu or Terraform with the local provider",
            steps=(
                "Create a sandbox: mkdir -p lab-tofu-drift && cd lab-tofu-drift",
                'Create main.tf with required_providers local and a local_file resource writing content = "managed" to filename = "note.txt".',
                "Run tofu init and tofu apply -auto-approve, or use terraform init and terraform apply -auto-approve.",
                "Edit note.txt manually to say drifted, then run tofu plan or terraform plan and observe drift is detected.",
                "Restore by running tofu apply -auto-approve or terraform apply -auto-approve, then inspect note.txt.",
            ),
            cleanup=(
                "tofu destroy -auto-approve (or terraform destroy -auto-approve if you used Terraform)",
                "cd .. && rm -rf lab-tofu-drift",
            ),
        ),
    ),
    Lab(
        id="actions-permission-cache",
        title="Review GitHub Actions permissions and cache keys",
        topics=(
            "GitHub Actions permissions OIDC secrets and runners",
            "CI pipeline design stages artifacts and caching",
        ),
        minutes=30,
        goal="Harden a workflow by narrowing token permissions and making cache keys match dependencies.",
        references=(
            "https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions",
            "https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication",
            "https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/caching-dependencies-to-speed-up-workflows",
        ),
        scenario=(
            Step(
                "A CI job only checks out code and runs tests. What GITHUB_TOKEN permission is usually enough?",
                (
                    "contents: read",
                    "contents: write",
                    "id-token: write",
                    "actions: write",
                ),
                "Read-only source access is enough for a test job. Write permissions or OIDC tokens should be granted only when needed.",
            ),
            Step(
                "A cache key is just linux-node. Dependencies change but stale packages keep restoring. What should the key include?",
                (
                    "A hash of the dependency lock file.",
                    "The latest commit author's username.",
                    "A random number every run.",
                    "The workflow run URL.",
                ),
                "Lock-file hashes invalidate caches when dependencies change. A random key disables useful cache reuse.",
            ),
            Step(
                "A pull_request workflow from forks has access to repository secrets. What is the safer assumption?",
                (
                    "Treat forked PR code as untrusted and avoid exposing secrets to it.",
                    "All forked code is trusted because it passed checkout.",
                    "Secrets are safe if echoed only once.",
                    "Use write-all permissions so tests can fix failures.",
                ),
                "Workflows can execute contributor code. Least privilege and secret isolation reduce risk.",
            ),
            Step(
                "A deployment job needs cloud federation through OIDC. Which permission is specifically required?",
                (
                    "id-token: write for the job that requests the OIDC token.",
                    "contents: write on every job.",
                    "packages: delete on the workflow.",
                    "issues: write because deployments create issues.",
                ),
                "GitHub requires id-token: write to mint OIDC tokens. Grant it only on jobs that federate to a cloud provider.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 standard library; text editor",
            steps=(
                "Create a sandbox: mkdir -p lab-actions-review/.github/workflows && cd lab-actions-review",
                "Create .github/workflows/ci.yml with permissions: write-all, actions/cache using key linux-node, and a test step.",
                "Write a Python script that scans ci.yml text and fails if it finds permissions: write-all or a cache key without hashFiles.",
                "Run python review_workflow.py and observe it reports both issues.",
                "Change permissions to contents: read and cache key to include ${{ hashFiles('package-lock.json') }}, then rerun the script.",
            ),
            cleanup=("cd .. && rm -rf lab-actions-review",),
        ),
    ),
    Lab(
        id="helm-template-values",
        title="Render a Helm chart with safe values",
        topics=("Helm charts values releases and rollback",),
        minutes=30,
        goal="Render chart templates locally and catch an unsafe Service type before installing anything.",
        references=(
            "https://helm.sh/docs/chart_template_guide/getting_started/",
            "https://helm.sh/docs/helm/helm_template/",
        ),
        scenario=(
            Step(
                "You need to see Kubernetes manifests from a chart without connecting to a cluster. Which command fits?",
                (
                    "helm template RELEASE CHART with the intended values files.",
                    "helm rollback RELEASE before installing it.",
                    "kubectl apply --dry-run=server without rendering Helm.",
                    "helm uninstall RELEASE to print manifests.",
                ),
                "helm template renders locally client-side. Rollback and uninstall operate on installed releases.",
            ),
            Step(
                "A values file changes service.type from ClusterIP to LoadBalancer in a local lab. What should review flag?",
                (
                    "It can request external load balancer provisioning when installed in a real cluster.",
                    "It only changes a label and has no operational effect.",
                    "It encrypts the Service manifest.",
                    "It forces Helm to use GitOps reconciliation.",
                ),
                "Service type affects exposure and infrastructure. A local render is the right time to catch unintended external exposure.",
            ),
            Step(
                "A release upgrade fails after changing values. What Helm concept supports returning to a prior revision?",
                (
                    "helm rollback to a stored release revision.",
                    "helm template, which stores every release revision.",
                    "kubectl logs, which rewrites the release history.",
                    "Chart.yaml apiVersion, which auto-reverts failed upgrades.",
                ),
                "Helm stores release revisions and can roll back installed releases. Rendering alone does not create release history.",
            ),
            Step(
                "Two environments use the same chart with different replica counts. What is the maintainable pattern?",
                (
                    "Keep chart templates common and use environment-specific values files.",
                    "Copy the whole chart once per environment.",
                    "Edit rendered YAML by hand after each template run.",
                    "Hard-code production values in every template.",
                ),
                "Values files separate configuration from templates. Copying charts creates drift and repeated fixes.",
            ),
        ),
        local=LocalRoute(
            tools="Helm 3",
            steps=(
                "Create a chart: helm create lab-helm-values && cd lab-helm-values",
                "Run helm template demo . > rendered-default.yaml and inspect the Service type in the output.",
                "Create values-lab.yaml with service.type: ClusterIP and replicaCount: 1, then run helm template demo . -f values-lab.yaml.",
                "Create values-risky.yaml with service.type: LoadBalancer and render again; observe the manifest exposure change before any install.",
                "Run helm lint . and fix any local chart edits if lint reports an issue.",
            ),
            cleanup=("cd .. && rm -rf lab-helm-values",),
        ),
    ),
    Lab(
        id="prometheus-self-scrape",
        title="Scrape Prometheus itself and query health",
        topics=("Prometheus scraping labels cardinality and PromQL",),
        minutes=35,
        goal="Run Prometheus locally, scrape its own metrics, and query target health.",
        references=(
            "https://prometheus.io/docs/prometheus/latest/getting_started/",
            "https://prometheus.io/docs/prometheus/latest/configuration/configuration/",
            "https://grafana.com/docs/grafana/latest/dashboards/",
        ),
        scenario=(
            Step(
                "A target is missing from Prometheus. Which configuration section normally lists scrape jobs and target addresses?",
                (
                    "scrape_configs",
                    "alertmanagers_only",
                    "remote_write_targets",
                    "dashboard_panels",
                ),
                "scrape_configs defines what Prometheus scrapes. Dashboards visualize data but do not configure scrape targets.",
            ),
            Step(
                "The up metric for a target is 0. What does that indicate?",
                (
                    "Prometheus could not successfully scrape that target at the last scrape.",
                    "The application returned more than zero requests.",
                    "The dashboard panel is hidden.",
                    "Prometheus disabled all labels.",
                ),
                "up is the standard scrape success signal. It is not an application request count.",
            ),
            Step(
                "A team wants to add user_id as a Prometheus label on every request metric. What concern should you raise?",
                (
                    "High-cardinality labels can create many time series and hurt performance.",
                    "Prometheus labels cannot contain underscores.",
                    "Labels are encrypted, so cardinality is irrelevant.",
                    "Only Grafana can add labels to metrics.",
                ),
                "Labels define time series cardinality. Unbounded user identifiers are a common source of operational pain.",
            ),
            Step(
                "A Grafana dashboard panel is blank but Prometheus has data. What should you check first?",
                (
                    "The panel query, time range, and data source selection.",
                    "Delete the Prometheus data directory immediately.",
                    "Change scrape_interval to one hour.",
                    "Assume the exporter is compromised.",
                ),
                "Visualization issues often come from query or time-range mismatch. Deleting data destroys evidence.",
            ),
        ),
        local=LocalRoute(
            tools="Docker or Podman; curl",
            steps=(
                "Create a sandbox: mkdir -p lab-prometheus && cd lab-prometheus",
                "Create prometheus.yml with a global scrape_interval and one job named prometheus targeting localhost:9090 so Prometheus scrapes itself inside the container.",
                'Run docker run --rm --name sc-prom -p 9090:9090 -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml" prom/prometheus',
                "Open http://localhost:9090/targets and observe the prometheus target health.",
                "Query http://localhost:9090/api/v1/query?query=up with curl and observe up for the scrape target.",
            ),
            cleanup=("docker rm -f sc-prom 2>/dev/null || true", "cd .. && rm -rf lab-prometheus"),
        ),
    ),
    Lab(
        id="slo-error-budget",
        title="Calculate an SLO error budget from logs",
        topics=("SLIs SLOs error budgets and reliability targets",),
        minutes=30,
        goal="Turn request logs into an availability SLI and decide whether the error budget is being burned too fast.",
        references=(
            "https://sre.google/sre-book/service-level-objectives/",
            "https://sre.google/workbook/alerting-on-slos/",
        ),
        scenario=(
            Step(
                "A checkout service has request logs with status codes. Which SLI is most direct for user-visible availability?",
                (
                    "The percentage of valid requests that return successful responses.",
                    "The number of engineers on call during the busiest customer traffic period.",
                    "The size of the deployment manifest.",
                    "The average age of servers.",
                ),
                "Availability SLIs should measure user-visible success. Staffing or file size can influence reliability but are not direct service indicators.",
            ),
            Step(
                "The SLO is 99.9% monthly success. What is the error budget?",
                (
                    "0.1% of valid requests may fail before the target is missed.",
                    "99.9% of requests may fail.",
                    "Exactly one incident per month.",
                    "No failures are allowed ever.",
                ),
                "The budget is the complement of the SLO. It is not an incident count unless you define a separate policy.",
            ),
            Step(
                "A new release consumes half the monthly budget in one hour. What should the team consider?",
                (
                    "Pause risky changes and investigate, following the agreed error-budget policy.",
                    "Ignore it until the calendar month ends.",
                    "Lower the SLO retroactively.",
                    "Delete the failed requests from the logs.",
                ),
                "Fast budget burn is actionable. Changing targets or data after the fact breaks trust in the SLO.",
            ),
            Step(
                "An alert fires on every single 500 response, including one-off failures. What is the likely issue?",
                (
                    "The alert is too noisy and should align with meaningful SLO burn.",
                    "Every single error must page the whole company.",
                    "The SLI should count deployments instead of requests.",
                    "The service has no users.",
                ),
                "SLO-based alerting focuses on significant budget burn. Paging on isolated errors creates noise and fatigue.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 standard library",
            steps=(
                "Create a sandbox: mkdir -p lab-slo-budget && cd lab-slo-budget",
                "Create requests.csv with columns status,count and rows 200,9950 plus 500,50.",
                "Write budget.py that reads the CSV, computes success rate, error rate, and remaining budget for a 99.9 SLO.",
                "Run python budget.py and observe that 50 failures out of 10000 requests exceeds a 0.1% budget.",
                "Change failures to 5, rerun, and observe the budget is mostly intact.",
            ),
            cleanup=("cd .. && rm -rf lab-slo-budget",),
        ),
    ),
    Lab(
        id="catalog-owner-check",
        title="Validate Backstage service ownership metadata",
        topics=(
            "Developer portals service catalogs and ownership",
            "Internal developer platforms golden paths and self service",
        ),
        minutes=30,
        goal="Check a catalog descriptor for ownership and lifecycle fields before it enters a developer portal.",
        references=(
            "https://backstage.io/docs/features/software-catalog/descriptor-format/",
            "https://backstage.io/docs/features/software-catalog/system-model/",
        ),
        scenario=(
            Step(
                "A service catalog entry has no owner. What is the platform risk?",
                (
                    "Users cannot tell which team is accountable for support and changes.",
                    "The service automatically becomes more secure.",
                    "Backstage converts it into a database resource.",
                    "The repository is deleted during ingestion.",
                ),
                "Ownership is a core catalog purpose. Missing owners weaken support paths and accountability.",
            ),
            Step(
                "A team wants every new service to start from the same tested template. What platform concept does that support?",
                (
                    "A golden path for common setup and standards.",
                    "Manual snowflake provisioning for each team.",
                    "Removing self-service to require tickets for everything.",
                    "Hiding documentation until production.",
                ),
                "Golden paths make the recommended way easy and repeatable. Ticket-only flows slow teams and reduce adoption.",
            ),
            Step(
                "A descriptor says lifecycle: production but points to a prototype with no on-call owner. What should review do?",
                (
                    "Challenge the metadata and align lifecycle with operational reality.",
                    "Accept it because lifecycle is decorative.",
                    "Delete all prototype code.",
                    "Move the owner field into a README only.",
                ),
                "Catalog metadata drives trust and discovery. Mislabeling maturity creates bad operational expectations.",
            ),
            Step(
                "Two services depend on the same database resource. How should the catalog model help?",
                (
                    "Represent components and resources so dependency relationships are discoverable.",
                    "Force both services into one repository.",
                    "Hide resource ownership to avoid blame.",
                    "Replace runtime monitoring with catalog YAML.",
                ),
                "The catalog can model ownership and relationships. It complements, not replaces, runtime telemetry.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 standard library; text editor",
            steps=(
                "Create a sandbox: mkdir -p lab-backstage-catalog && cd lab-backstage-catalog",
                "Create catalog-info.yaml for a Component with apiVersion, kind, metadata.name, spec.type, spec.lifecycle, and spec.owner.",
                "Write check_catalog.py that reads the file as text and verifies kind: Component plus spec owner and lifecycle lines exist.",
                "Run python check_catalog.py and observe success.",
                "Remove the owner line, rerun the checker, and observe it fails before the descriptor is shared.",
            ),
            cleanup=("cd .. && rm -rf lab-backstage-catalog",),
        ),
    ),
    Lab(
        id="mlflow-local-run",
        title="Track a local MLflow experiment run",
        topics=("ML experiment tracking reproducibility and model registries",),
        minutes=35,
        goal="Log parameters and metrics to a local MLflow tracking store and identify what belongs in a model registry.",
        references=(
            "https://mlflow.org/docs/latest/ml/tracking/quickstart/",
            "https://mlflow.org/docs/latest/ml/model-registry/",
        ),
        scenario=(
            Step(
                "Two training runs produce different accuracy values. What should you log to make comparison meaningful?",
                (
                    "Parameters, metrics, code version, and artifacts needed to reproduce the run.",
                    "Only the final screenshot of the terminal after the best metric appears, with no run inputs saved.",
                    "The developer's laptop hostname as the only field.",
                    "Nothing, because local experiments are disposable.",
                ),
                "Experiment tracking records inputs and outputs for comparison. A screenshot is hard to query or reproduce.",
            ),
            Step(
                "A model is approved for wider use. What does a model registry add beyond raw run logs?",
                (
                    "Versioned model lifecycle metadata such as aliases, annotations, and lineage.",
                    "Automatic proof that the model is unbiased.",
                    "Free unlimited GPU capacity.",
                    "A replacement for all tests and monitoring.",
                ),
                "A registry organizes model versions and lifecycle state. It does not prove quality or remove operational validation.",
            ),
            Step(
                "A metric improves but the dataset changed silently. What concern should you raise?",
                (
                    "The run may not be comparable unless dataset identity is tracked.",
                    "Higher metrics are always enough for approval.",
                    "The registry will infer the old dataset automatically.",
                    "Delete the weaker run so reports look clean.",
                ),
                "Reproducibility needs data lineage or identifiers. Better metrics without comparable inputs can mislead reviewers.",
            ),
            Step(
                "The local MLflow UI is bound to localhost. What is the safe lab posture?",
                (
                    "Keep it local and do not expose experiment data publicly.",
                    "Bind it to 0.0.0.0 and share without authentication.",
                    "Store real customer data in example runs.",
                    "Commit the mlruns directory with secrets.",
                ),
                "Local-only practice avoids exposing metadata or artifacts. Public binding and real data create privacy risk.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 venv with MLflow installed from pip; localhost only",
            steps=(
                "Create a sandbox: mkdir -p lab-mlflow-local && cd lab-mlflow-local",
                "Create and activate a virtual environment, then install mlflow if it is not already available: python -m pip install mlflow",
                "Create train.py that starts an MLflow run, logs param alpha=0.1, metric accuracy=0.82, and a small artifact file.",
                "Run python train.py, then run mlflow ui --host 127.0.0.1 --port 5000.",
                "Open http://127.0.0.1:5000 and compare the run metadata; keep all data local and use no real secrets.",
            ),
            cleanup=("Stop mlflow ui with Ctrl+C", "cd .. && rm -rf lab-mlflow-local"),
        ),
    ),
    Lab(
        id="cost-allocation-tags",
        title="Allocate shared cloud costs from a CSV",
        topics=(
            "Cloud cost allocation tags budgets and anomaly detection",
            "Cost-aware architecture forecasting and accountability",
        ),
        minutes=30,
        goal="Use tags and a shared-cost rule to produce an accountable cost allocation report.",
        references=(
            "https://www.finops.org/framework/capabilities/allocation/",
            "https://www.finops.org/framework/capabilities/workload-optimization/",
            "https://docs.python.org/3/library/csv.html",
        ),
        scenario=(
            Step(
                "A monthly cost export has many rows with missing team tags. What is the FinOps impact?",
                (
                    "Costs cannot be reliably allocated, weakening accountability.",
                    "Missing tags always mean the resources are free and should be excluded from every report.",
                    "The cloud provider deletes untagged resources automatically.",
                    "Budgets become unnecessary because tags are optional.",
                ),
                "Allocation depends on metadata such as tags or accounts. Missing tags create shared or unallocated spend that must be handled.",
            ),
            Step(
                "A shared logging platform supports three teams. What is a reasonable allocation practice?",
                (
                    "Define and document a split rule, such as usage-based or agreed percentage allocation.",
                    "Charge all shared costs to the newest team.",
                    "Ignore shared costs so totals look lower.",
                    "Randomly assign costs each month.",
                ),
                "Shared costs need transparent rules. Random or hidden allocation prevents teams from acting on spend.",
            ),
            Step(
                "A service doubles spend after traffic stays flat. What should an anomaly workflow do?",
                (
                    "Flag it for review with owner, service, and recent change context.",
                    "Assume the bill is wrong and delete all resources.",
                    "Wait a year for a trend.",
                    "Remove the cost row from the report.",
                ),
                "Anomaly detection is a prompt to investigate with context. Deleting resources blindly can cause outages.",
            ),
            Step(
                "A team wants lower cost but must keep latency SLOs. What optimization framing is best?",
                (
                    "Rightsize and schedule resources while validating performance requirements.",
                    "Turn off production monitoring first.",
                    "Use the smallest resource everywhere without testing.",
                    "Move all costs to another team tag.",
                ),
                "Optimization balances cost, utilization, and requirements. Tag shifting does not reduce actual usage.",
            ),
        ),
        local=LocalRoute(
            tools="Python 3 standard library",
            steps=(
                "Create a sandbox: mkdir -p lab-finops-tags && cd lab-finops-tags",
                "Create costs.csv with columns service,team,cost and include api,team-a,100 plus logging,,60 plus batch,team-b,40.",
                "Write allocate.py using csv.DictReader to total direct costs and split blank-team shared rows equally across known teams.",
                "Run python allocate.py and observe team totals include a share of logging.",
                "Add a row api,team-a,500 and rerun; flag any service whose cost more than doubles compared with the prior sample.",
            ),
            cleanup=("cd .. && rm -rf lab-finops-tags",),
        ),
    ),
    Lab(
        id="api-adr-tradeoff",
        title="Write an API architecture decision record",
        topics=(
            "API design versioning authentication and rate limiting",
            "Technical decision records and stakeholder communication",
        ),
        minutes=30,
        goal="Capture an API design decision with context, options, consequences, and a rollback signal.",
        references=(
            "https://docs.aws.amazon.com/wellarchitected/latest/framework/reliability.html",
            "https://owasp.org/API-Security/editions/2023/en/0x11-t10/",
        ),
        scenario=(
            Step(
                "A public API change breaks old mobile clients. What design practice should have reduced that risk?",
                (
                    "Version the API or preserve backward compatibility during migration.",
                    "Remove authentication until all clients upgrade so every version behaves the same.",
                    "Return HTTP 200 for every error.",
                    "Hide the change from release notes.",
                ),
                "Versioning and compatibility protect clients during change. Removing auth or masking errors creates security and operability risks.",
            ),
            Step(
                "Traffic spikes from one client can starve others. Which control belongs in the architecture decision?",
                (
                    "Rate limiting or quotas with documented client behavior.",
                    "Unlimited retries with no backoff.",
                    "A single shared API key for all clients.",
                    "Disabling logs during spikes.",
                ),
                "Rate limits protect shared capacity and set expectations. Unlimited retries can amplify overload.",
            ),
            Step(
                "Stakeholders disagree between synchronous REST and asynchronous events. What should an ADR capture?",
                (
                    "Context, considered options, decision, consequences, and review triggers.",
                    "Only the winning option with no trade-offs.",
                    "A transcript of every meeting without a decision.",
                    "Credentials needed to deploy the chosen design.",
                ),
                "ADRs explain why a decision was made and when to revisit it. Omitting trade-offs weakens future learning.",
            ),
            Step(
                "An ADR includes a rollback signal. Which signal is most useful?",
                (
                    "A measurable indicator such as error rate, latency, or client adoption threshold.",
                    "A vague feeling that the design is unpopular.",
                    "The number of slides in the design deck.",
                    "Whether the implementation used a new font.",
                ),
                "Rollback or revisit triggers should be observable. Vague preferences do not support timely action.",
            ),
        ),
        local=LocalRoute(
            tools="Text editor; Python 3 standard library optional",
            steps=(
                "Create a sandbox: mkdir -p lab-api-adr && cd lab-api-adr",
                "Write adr-001-api-versioning.md with sections Status, Context, Options, Decision, Consequences, and Review trigger.",
                "In Options, compare URI versioning, header versioning, and backward-compatible additive changes for a mobile API.",
                "Add controls for authentication, rate limiting, and client migration communication; do not include real secrets.",
                "Optionally write a Python script that checks the ADR contains every required section before review.",
            ),
            cleanup=("cd .. && rm -rf lab-api-adr",),
        ),
    ),
)

_MODULE_IDS = (
    "foundations",
    "linux",
    "git",
    "automation",
    "azure",
    "gcp",
    "containers",
    "kubernetes",
    "iac",
    "delivery",
    "gitops",
    "observability",
    "sre",
    "platform",
    "mlops",
    "finops",
    "architecture",
)

MODULE_OF: dict[str, str] = {
    lab.id: module_id for lab, module_id in zip(MODULE_LABS, _MODULE_IDS, strict=True)
}
