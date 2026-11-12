#!/bin/sh
# Prints one tool version that CI uses, read from the workflow files. The workflows are the
# single source of these versions; the Makefile calls this script instead of repeating them.
#
#   ci-versions.sh python|uv|postgres-image|node [workflows-dir]
#
# Exits with status 1 and names the field when it cannot find exactly one value, for
# example after the layout of a workflow changed. Several jobs may name the same tool
# (backend and web both set up uv and start Postgres); they must agree, and two different
# values fail the same way.
set -eu

field=${1:?usage: ci-versions.sh python|uv|postgres-image|node [workflows-dir]}
dir=${2:-$(dirname "$0")/../.github/workflows}

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
*)
	echo "ci-versions.sh: unknown field '$field'" >&2
	exit 2
	;;
esac

if [ "$(printf '%s\n' "$value" | grep -c .)" != 1 ]; then
	echo "ci-versions.sh: cannot read the $where (found: '$(echo $value)')" >&2
	exit 1
fi
printf '%s\n' "$value"
