#!/usr/bin/env bash
# bump-version.sh — Standardised version bumping for Allow2 Python SDK
# Usage: ./scripts/bump-version.sh [prerelease|patch|minor|major] [--preid alpha|beta|rc]
#
# Python uses PEP 440: 2.0.0a1 (alpha), 2.0.0b1 (beta), 2.0.0rc1 (release candidate)
#
# Examples:
#   ./scripts/bump-version.sh prerelease --preid alpha   # 2.0.0a1 → 2.0.0a2
#   ./scripts/bump-version.sh prerelease --preid beta    # 2.0.0a2 → 2.0.0b1
#   ./scripts/bump-version.sh patch                       # 2.0.0a2 → 2.0.1
#   ./scripts/bump-version.sh minor                       # 2.0.1 → 2.1.0
#   ./scripts/bump-version.sh major                       # 2.1.0 → 3.0.0
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION_FILE="pyproject.toml"
BUMP="${1:-prerelease}"
PREID=""
if [[ "${2:-}" == "--preid" ]]; then PREID="${3:-alpha}"; fi

# Map preid to PEP 440 suffix
pep440_suffix() {
  case "$1" in
    alpha) echo "a" ;;
    beta)  echo "b" ;;
    rc)    echo "rc" ;;
    *)     echo "a" ;;
  esac
}

# Read current version from pyproject.toml
OLD=$(grep '^version = ' "$VERSION_FILE" | head -1 | sed 's/version = "\(.*\)"/\1/')

# Parse version: 2.0.0a1 → major=2 minor=0 patch=0 pre_type=a pre_num=1
if [[ "$OLD" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(a|b|rc)?([0-9]+)?$ ]]; then
  MAJOR="${BASH_REMATCH[1]}"
  MINOR="${BASH_REMATCH[2]}"
  PATCH="${BASH_REMATCH[3]}"
  PRE_TYPE="${BASH_REMATCH[4]:-}"
  PRE_NUM="${BASH_REMATCH[5]:-}"
else
  echo "Cannot parse version: $OLD" >&2; exit 1
fi

case "$BUMP" in
  prerelease)
    SUFFIX=$(pep440_suffix "${PREID:-alpha}")
    if [[ "$PRE_TYPE" == "$SUFFIX" && -n "$PRE_NUM" ]]; then
      NEW="${MAJOR}.${MINOR}.${PATCH}${SUFFIX}$((PRE_NUM + 1))"
    else
      NEW="${MAJOR}.${MINOR}.${PATCH}${SUFFIX}1"
    fi
    ;;
  patch)
    NEW="$MAJOR.$MINOR.$((PATCH + 1))"
    ;;
  minor)
    NEW="$MAJOR.$((MINOR + 1)).0"
    ;;
  major)
    NEW="$((MAJOR + 1)).0.0"
    ;;
  *)
    echo "Usage: $0 [prerelease|patch|minor|major] [--preid alpha|beta|rc]" >&2
    exit 1
    ;;
esac

# Write back
sed -i "s/^version = \"${OLD}\"/version = \"${NEW}\"/" "$VERSION_FILE"

echo "$OLD → $NEW"
git add "$VERSION_FILE"
git commit -m "v$NEW"
# Tag uses semver format for CI publish workflow
TAG="v${MAJOR}.${MINOR}.${PATCH}"
if [[ "$NEW" != "${MAJOR}.${MINOR}.${PATCH}" ]]; then
  # Convert PEP 440 back to semver for tag: 2.0.0a2 → v2.0.0-alpha.2
  TAG_PRE=$(echo "$NEW" | sed "s/${MAJOR}\.${MINOR}\.${PATCH}//")
  TAG_PRE=$(echo "$TAG_PRE" | sed 's/^a/-alpha./; s/^b/-beta./; s/^rc/-rc./')
  TAG="v${MAJOR}.${MINOR}.${PATCH}${TAG_PRE}"
fi
git tag "$TAG"
echo "Tagged $TAG — push with: git push origin master --tags"
