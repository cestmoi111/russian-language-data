#!/bin/sh
# Download kaikki.org dumps into .cache/, resuming until each is complete
# (the server drops long connections, so one curl call is rarely enough).
#   sh scripts/dict/fetch.sh en ru fr de ...
cd "$(dirname "$0")/../../.cache" || exit 1
get() {
  name=$1; url=$2
  want=$(curl -sIL "$url" | grep -i '^content-length' | tail -1 | tr -dc 0-9)
  while :; do
    have=$(stat -c %s "$name" 2>/dev/null || echo 0)
    [ -n "$want" ] && [ "$have" -gt "$want" ] && { echo "$name larger than on server, restarting"; rm -f "$name"; continue; }
    [ -n "$want" ] && [ "$have" -eq "$want" ] && break
    curl -sL -C - --max-time 900 -o "$name" "$url"
    sleep 2
  done
  echo "$name $have/$want done"
}
for l in "$@"; do
  if [ "$l" = en ]; then
    get en-raw.jsonl.gz https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz &
  else
    get $l-extract.jsonl.gz https://kaikki.org/dictionary/downloads/$l/$l-extract.jsonl.gz &
  fi
done
wait
