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
