# SkillCoach OCI learning deployment

This is a learning project. Nothing in this folder deploys itself to Oracle Cloud.
The live SkillCoach app, Supabase database, Telegram bot and Vercel deployment are
not changed by these files.

## Image pipeline

`.github/workflows/publish-oci-images.yml` validates the Helm chart and container
checks automatically when relevant files change on `oci-learning`, and for
matching pull requests. These triggers only run validation. Publishing is
separately gated to a manual `workflow_dispatch` run on `oci-learning` where you
explicitly select `yes` for `publish_images`. The two ARM64 images are tagged
with the selected Git commit's full SHA; the workflow checks GHCR's package
versions and refuses to reuse a tag. It then updates
`helm/skillcoach/values-oci.yaml` with that SHA. Argo CD can see the new Git
commit and reconcile the chart.

GitHub only makes a manually dispatched workflow available when its workflow
file exists on the repository's default branch. The workflow is now on `main`
through [PR #1](https://github.com/Harshit975shukla/skillcoach-bot/pull/1), so
manual dispatch is available. Run it on `oci-learning`; choose `no` to validate
without publishing. Choosing `yes` uploads the two images to GHCR and updates
`values-oci.yaml`; it does not deploy to OCI.

The images are:

- `ghcr.io/harshit975shukla/skillcoach-bot:<commit-sha>` — web app and slim jobs.
- `ghcr.io/harshit975shukla/skillcoach-bot-media:<commit-sha>` — lesson and
  recovery jobs with Chromium, Mermaid, fonts and ffmpeg.

GHCR packages may be private after first publication. Before Kubernetes can pull
private images, either make both packages public in their GitHub package settings,
or create the `ghcr-pull-secret` in the `skillcoach` namespace using a narrowly
scoped package-read credential. Never put a token in Git, Helm values or chat.
The chart currently expects that pull secret.

The workflow's GitHub token writes only to GHCR and to
`deploy-oci/helm/skillcoach/values-oci.yaml` on `oci-learning`. Its tag is a
commit-SHA reference, and the workflow refuses an existing version rather than
overwriting it.

## Argo CD Application

`argocd/skillcoach.yaml` tells Argo CD to watch the public repository's
`oci-learning` branch, render `helm/skillcoach` with both values files, and sync
to a `skillcoach` namespace. `prune: false` avoids automatically deleting
resources if they disappear from Git. `selfHeal: true` returns changed resources
to the state recorded in Git.

It is a manifest to study, not a command to apply yet. Before using it on a
cluster, check that:

1. OCI access is delegated safely and the Always Free capacity, storage, network
   and possible egress costs are verified. Do not enable paid billing.
2. The images have been published and can be pulled.
3. Argo CD, Traefik, cert-manager and a NetworkPolicy-enforcing CNI are installed.
4. A `ghcr-pull-secret` exists, or both packages have intentionally been made public.
5. Required app and PostgreSQL secrets come from a secret manager, not blank Helm
   placeholders. Backups have a private Object Storage target and a tested restore.
6. The host name and HTTPS certificate are configured.

Do not connect the production Telegram bot or copy production learner data into
this learning deployment. Use a new test bot and an empty test database. Do not
retire Supabase before a separately approved and verified cutover.

## Your lab

1. Read `values-oci.yaml`. It selects GHCR repositories, the image tag, and the
   image-pull Secret. The workflow replaces the tag with the full source commit SHA.
2. Push a relevant change to `oci-learning` and check the automatic validation
   run in **Actions**. The path filters intentionally exclude
   `values-oci.yaml`, so the publishing workflow's own tag update does not start
   another validation run.
3. The workflow is available from **Actions → Publish OCI learning images → Run
   workflow** because its file is on `main`. Select `oci-learning` and keep
   `publish_images` as `no` for validation. Before selecting `yes`, review who
   can pull the GHCR packages; publishing uploads both images and updates
   `values-oci.yaml` but does not deploy.
4. Read `argocd/skillcoach.yaml`. Point out which Git branch and folder Argo CD
   watches, and where it will create the app.
5. Do not apply it to OCI yet. Next, we will learn how Argo CD fetches a Git
   revision and turns a Helm chart into Kubernetes objects on a local practice
   cluster.
