#!/bin/sh
# Prints one tool version that CI uses, read from the workflow files. The workflows are the
# single source of these versions; the Makefile calls this script instead of repeating them.
#
#   ci-versions.sh python|uv|postgres-image|node|pnpm|pnpm-sha512|playwright [workflows-dir]
#
# pnpm and playwright are pinned in frontend/package.json (CI reads them from there as well:
# pnpm/action-setup takes "packageManager", the lockfile takes "@playwright/test").
# pnpm-sha512 is the hex SHA-512 of the pnpm tarball, the "+sha512." part of "packageManager".
#
# The values end up in image names and in a Dockerfile on the calling machine, so only the
# characters a version or an image reference needs are let through.
#
# Exits with status 1 and names the field when it cannot find exactly one value, for
# example after the layout of a workflow changed. Several jobs may name the same tool
# (backend and web both set up uv and start Postgres); they must agree, and two different
# values fail the same way.
set -eu

field=${1:?usage: ci-versions.sh python|uv|postgres-image|node|pnpm|pnpm-sha512|playwright [workflows-dir]}
dir=${2:-$(dirname "$0")/../.github/workflows}
package_json=${CI_VERSIONS_PACKAGE_JSON:-$(dirname "$0")/../frontend/package.json}

# Value of KEY in the "with:" block of the astral-sh/setup-uv step.
setup_uv() {
	awk -v key="$1:" '
		/uses: *astral-sh\/setup-uv@/ { in_step = 1; next }
		in_step && /^ *- / { in_step = 0 }
		in_step && $1 == key { value = $2; gsub(/"/, "", value); print value }
	' "$dir/ci.yml" | sort -u
}

case $field in
python)
	where='python-version of the astral-sh/setup-uv step in ci.yml'
	value=$(setup_uv python-version)
	;;
uv)
	where='version of the astral-sh/setup-uv step in ci.yml'
	value=$(setup_uv version)
	;;
postgres-image)
	where='image of the postgres service in ci.yml'
	value=$(sed -n 's/^ *image: *\(postgres:[^ ]*\) *$/\1/p' "$dir/ci.yml" | sort -u)
	;;
node)
	where='node-version of the actions/setup-node step in commitlint.yml'
	value=$(sed -n 's/^ *node-version: *"\{0,1\}\([^" ]*\)"\{0,1\} *$/\1/p' "$dir/commitlint.yml")
	;;
pnpm)
	where='pnpm version in "packageManager" of frontend/package.json'
	value=$(sed -n 's/^ *"packageManager": *"pnpm@\([0-9][0-9.]*\)+sha512\.[0-9a-f]*".*$/\1/p' "$package_json")
	;;
pnpm-sha512)
	where='"+sha512." hash of pnpm in "packageManager" of frontend/package.json'
	value=$(sed -n 's/^ *"packageManager": *"pnpm@[0-9][0-9.]*+sha512\.\([0-9a-f]\{128\}\)".*$/\1/p' "$package_json")
	;;
playwright)
	where='exact version of "@playwright/test" in frontend/package.json'
	value=$(sed -n 's/^ *"@playwright\/test": *"\([0-9][0-9.]*\)".*$/\1/p' "$package_json")
	;;
*)
	echo "ci-versions.sh: unknown field '$field'" >&2
	exit 2
	;;
esac

if [ "$(case $value in
*[!0-9A-Za-z.:_/@-]*)
	echo "ci-versions.sh: refusing the $where: it holds a character outside 0-9 A-Z a-z . : _ / @ -" >&2
	exit 1
	;;
esac
printf '%s\n' "$value" | grep -c .)" != 1 ]; then
	echo "ci-versions.sh: cannot read the $where (found: '$(echo $value)')" >&2
	exit 1
fi
printf '%s\n' "$value"
