#!/usr/bin/env bash
# Builds every service a host's release manifest names, from source, at exactly the tagged release,
# and installs it into the local Maven repository. The hosts then build from those.
#
#   hosts/install-services.sh            all hosts
#   hosts/install-services.sh edge       one host
#
# A manifest pins <sprout-NAME.version>X.Y.Z</sprout-NAME.version>; this builds tag vX.Y.Z of
# github.com/SaiNayakk/sprout-NAME. It always rebuilds, even if that version is already installed:
# a copy installed from a working tree could differ from the tag, and the gate must test the tag.
# (Why not a package host: see docs, Decisions, ADR-011.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

hosts=("$@")
[ ${#hosts[@]} -eq 0 ] && hosts=($(cd "$ROOT" && ls -d */ | tr -d /))

for host in "${hosts[@]}"; do
  grep -o '<sprout-[a-z-]*\.version>[^<]*<' "$ROOT/$host/pom.xml" | sed 's/<\(sprout-[a-z-]*\)\.version>\(.*\)</\1 \2/' |
  while read -r service version; do
    echo "$service $version: building tag v$version"
    git -c advice.detachedHead=false clone -q --depth 1 --branch "v$version" "https://github.com/SaiNayakk/$service.git" "$WORK/$service-$version"
    built=$(cd "$WORK/$service-$version" && sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' pom.xml | sed -n 2p)
    if [ "$built" != "$version" ]; then
      echo "tag v$version of $service declares version $built; refusing to install it as $version" >&2
      exit 1
    fi
    (cd "$WORK/$service-$version" && mvn -q -B install -DskipTests)
  done
done
