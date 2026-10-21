{{/* Common name helpers */}}
{{- define "skillcoach.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "skillcoach.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s" (include "skillcoach.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "skillcoach.labels" -}}
app.kubernetes.io/name: {{ include "skillcoach.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "skillcoach.selectorLabels" -}}
app.kubernetes.io/name: {{ include "skillcoach.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* PostgreSQL names */}}
{{- define "skillcoach.pg.fullname" -}}
{{- printf "%s-postgresql" (include "skillcoach.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The in-cluster DATABASE_URL. Uses the headless service DNS name. */}}
{{- define "skillcoach.databaseUrl" -}}
{{- $pg := .Values.postgresql -}}
{{- printf "postgresql://%s:$(POSTGRES_PASSWORD)@%s:%v/%s?sslmode=disable" $pg.username (include "skillcoach.pg.fullname" .) $pg.port $pg.database -}}
{{- end -}}

{{/* Pod-level security shared by every pod that runs the app image. */}}
{{- define "skillcoach.appPodSecurity" -}}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .Values.security.appUid }}
  runAsGroup: {{ .Values.security.appUid }}
  fsGroup: {{ .Values.security.appUid }}
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{/* Container-level security: no root, no extra rights, read-only files. */}}
{{- define "skillcoach.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end -}}

{{/* The only writable folder: Python's tempfile and gunicorn use /tmp. */}}
{{- define "skillcoach.tmpMount" -}}
volumeMounts:
  - name: tmp
    mountPath: /tmp
{{- end -}}

{{- define "skillcoach.tmpVolume" -}}
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: {{ .Values.security.tmpSize }}
{{- end -}}

{{/* The Secret that holds the HTTPS certificate. */}}
{{- define "skillcoach.tlsSecretName" -}}
{{- .Values.ingress.tls.secretName | default (printf "%s-tls" (include "skillcoach.fullname" .)) -}}
{{- end -}}
