set -eu

request() {
  nats -s tls://nats:4222 --tlsca /run/flowai/stand-ca/ca.pem \
    --creds /run/bootstrap/user.creds --inbox-prefix _INBOX.deployment \
    --no-context request --raw --reply-timeout=5s "$@" 2>/dev/null
}

ensure() {
  info="$1"
  absent="$2"
  create="$3"
  payload="$4"
  response="$(request "$info")" || return 1
  if printf '%s' "$response" | jq -e 'type == "object" and .error == null and (.config | type == "object")' >/dev/null 2>&1; then
    return
  fi
  printf '%s' "$response" | jq -e --argjson code "$absent" \
    '.error.code == 404 and .error.err_code == $code' >/dev/null 2>&1 || return 1
  response="$(request "$create" "$payload")" || return 1
  printf '%s' "$response" | jq -e 'type == "object" and .error == null and (.config | type == "object")' >/dev/null 2>&1
}

for file in /etc/bootstrap/stream-*.json; do
  name="$(jq -er '.name' "$file")"
  ensure "\$JS.API.STREAM.INFO.$name" 10059 "\$JS.API.STREAM.CREATE.$name" "$(cat "$file")" || exit 1
done

for file in /etc/bootstrap/consumer-*.json; do
  stream="$(jq -er '.stream_name' "$file")"
  durable="$(jq -er '.config.durable_name' "$file")"
  ensure "\$JS.API.CONSUMER.INFO.$stream.$durable" 10014 \
    "\$JS.API.CONSUMER.CREATE.$stream.$durable" "$(cat "$file")" || exit 1
done
