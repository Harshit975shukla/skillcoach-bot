# SkillCoach OCI learning deployment

This is a learning project. Nothing in this folder deploys itself to Oracle Cloud.
The live SkillCoach app, Supabase database, Telegram bot and Vercel deployment are
not changed by these files.

## Image pipeline

`.github/workflows/publish-oci-images.yml` is manual-only. It first validates the
Helm chart and container checks. It publishes only if you select `yes` for
`publish_images`, and only when you run it on the `oci-learning` branch. The two
ARM64 images are tagged with the selected Git commit's full SHA; the workflow
checks GHCR's package versions and refuses to reuse a tag. It then updates
`helm/skillcoach/values-oci.yaml` with that SHA. Argo CD can see the new Git commit
and reconcile the chart.

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
2. On GitHub, open **Actions → Publish OCI learning images → Run workflow**.
   Run it on `oci-learning`; leave `publish_images` as `no` to validate without
   publishing. Publishing uploads both images to GitHub Packages but does not
   deploy to OCI. The source repository is public; package visibility depends on
   GHCR settings, so choose `yes` only after reviewing who can pull the images.
3. After a successful publish, compare the SHA shown in the Actions run with
   `image.tag` in `values-oci.yaml`. Explain why the tag is not `latest`.
4. Read `argocd/skillcoach.yaml`. Point out which Git branch and folder Argo CD
   watches, and where it will create the app.
5. Do not apply it to OCI yet. Next, we will learn how Argo CD fetches a Git
   revision and turns a Helm chart into Kubernetes objects on a local practice
   cluster.
