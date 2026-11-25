set -eu
umask 077

fail() {
  echo 'NATS resolver continuity check failed' >&2
  exit 1
}

account_key() {
  key="$(cat "$1")"
  case "$key" in
    A*) ;;
    *) fail ;;
  esac
  case "$key" in
    *[!A-Z2-7]*) fail ;;
  esac
  [ "${#key}" -eq 56 ] || fail
  printf '%s' "$key"
}

app="$(account_key /run/resolver-identities/application-account)"
system="$(account_key /run/resolver-identities/system-account)"
[ "$app" != "$system" ] || fail

app_file="/data/resolver/$app.jwt"
system_file="/data/resolver/$system.jwt"
initializing=/data/.flowai-nats-initializing
initialized=/data/.flowai-nats-initialized

if [ "$1" = fresh ] && [ ! -f "$initialized" ]; then
  if [ ! -f "$initializing" ]; then
    [ ! -e /data/jetstream ] || fail
    [ ! -e /data/resolver ] || fail
    touch "$initializing"
  fi

  mkdir -p /data/resolver
  seed_once() {
    target="$1"
    source="$2"
    if [ -e "$target" ]; then
      cmp -s "$source" "$target" || fail
      return
    fi
    [ -s "$source" ] || fail
    temporary="$(mktemp /data/resolver/.seed.XXXXXX)"
    trap 'rm -f "$temporary"' EXIT
    cp "$source" "$temporary"
    ln "$temporary" "$target"
    rm -f "$temporary"
    trap - EXIT
  }
  seed_once "$app_file" /run/resolver-seed/application.jwt
  seed_once "$system_file" /run/resolver-seed/system.jwt
  mv "$initializing" "$initialized"
fi

if [ "$1" = adopt ]; then
  [ -d /data/jetstream ] || fail
fi
[ -s "$app_file" ] && [ -s "$system_file" ] || fail
