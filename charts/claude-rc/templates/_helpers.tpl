{{- define "claude-rc.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "claude-rc.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "claude-rc.workerName" -}}
{{- printf "%s-worker" (include "claude-rc.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* dict "root" $ "tier" "controller"|"worker" */}}
{{- define "claude-rc.selectorLabels" -}}
app.kubernetes.io/name: {{ include "claude-rc.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .tier }}
{{- end }}

{{- define "claude-rc.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "claude-rc.selectorLabels" . }}
app.kubernetes.io/version: {{ .root.Values.image.tag | default .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
{{- end }}

{{- define "claude-rc.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}

{{- define "claude-rc.sessionName" -}}
{{- .Values.session.name | default .Release.Name }}
{{- end }}

{{- define "claude-rc.gitRepos" -}}
{{- $pairs := list }}
{{- range $name, $url := .Values.git.repos }}
{{- $pairs = append $pairs (printf "%s=%s" $name $url) }}
{{- end }}
{{- join " " $pairs }}
{{- end }}

{{- define "claude-rc.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "claude-rc.claudeSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end }}

{{/* dict "root" $ "ordinal" "0"|"1" */}}
{{- define "claude-rc.claudeEnv" -}}
- name: CLAUDE_SESSION_NAME
  value: {{ include "claude-rc.sessionName" .root | quote }}
- name: CLAUDE_SESSION_ORDINAL
  value: {{ .ordinal | quote }}
- name: CLAUDE_CAPACITY
  value: {{ .root.Values.session.capacity | quote }}
- name: CLAUDE_PERMISSION_MODE
  value: {{ .root.Values.session.permissionMode | quote }}
- name: GIT_REPOS
  value: {{ include "claude-rc.gitRepos" .root | quote }}
- name: GIT_USER_NAME
  value: {{ .root.Values.git.user.name | quote }}
- name: GIT_USER_EMAIL
  value: {{ .root.Values.git.user.email | quote }}
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
{{- end }}

{{- define "claude-rc.claudeVolumeMounts" -}}
- name: home
  mountPath: /home/claude
  subPath: home
- name: home
  mountPath: /workspace
  subPath: workspace
- name: tmp
  mountPath: /tmp
{{- if .Values.github.existingSecret }}
- name: github
  mountPath: /etc/claude-rc/github
  readOnly: true
{{- end }}
{{- end }}

{{/* the volumes both tiers share, except "home" (PVC vs volumeClaimTemplate) */}}
{{- define "claude-rc.sharedVolumes" -}}
- name: tmp
  emptyDir: {}
{{- if .Values.github.existingSecret }}
- name: github
  secret:
    secretName: {{ .Values.github.existingSecret }}
    defaultMode: 0440
{{- end }}
{{- end }}
