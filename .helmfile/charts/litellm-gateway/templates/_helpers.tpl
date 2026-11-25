{{- define "litellm-gateway.labels" -}}
app.kubernetes.io/name: litellm-gateway
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "litellm-gateway.selector" -}}
app.kubernetes.io/name: litellm-gateway
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "litellm-gateway.validate" -}}
{{- if ne .Release.Name "litellm-gateway" -}}
{{- fail "the existing release identity is litellm-gateway" -}}
{{- end -}}
{{- if not (has .Values.storageMode (list "fresh" "adopt")) -}}
{{- fail "storageMode must be fresh or adopt" -}}
{{- end -}}
{{- $image := required "LiteLLM image from preflight is required" .Values.image -}}
{{- if or (not (regexMatch "^[^@[:space:]]+/[^/@:[:space:]]+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$" $image)) (hasSuffix ":latest" (lower $image)) -}}
{{- fail "LiteLLM image requires an explicit version tag" -}}
{{- end -}}
{{- if and (eq .Values.storageMode "fresh") (not (hasPrefix "ghcr.io/pandops/flowai-litellm-gateway:" $image)) -}}
{{- fail "fresh LiteLLM requires the qualified candidate image" -}}
{{- end -}}
{{- end -}}

{{/* Exec probe: GET a path on LiteLLM's loopback listener, exit 0 only on 200. */}}
{{- define "litellm-gateway.probe" -}}
import sys, urllib.request; sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:4000{{ . }}", timeout=3).status == 200 else 1)
{{- end -}}
