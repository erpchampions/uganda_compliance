#!/usr/bin/env bash
# Ruff lint/format for the Python files changed since $1 (a commit/ref).
# The legacy code base does not pass ruff repo-wide, so:
#   * new files, and files that passed both `ruff check` and `ruff format --check` at the base, must pass both;
#   * legacy files that failed either at the base must not get more `ruff check` findings (they are not
#     reformatted wholesale: that would conflict with every merge from upstream `develop`).
set -uo pipefail
base="$1"
status=0
mapfile -t files < <(git diff --name-only --diff-filter=ACMR "$base" -- '*.py')
if [ ${#files[@]} -eq 0 ]; then
	echo "No Python files changed since $base"
	exit 0
fi

count() { ruff check --quiet --output-format concise --stdin-filename "$1" - 2>/dev/null | grep -c . ; }
clean_at_base() {
	git show "$base:$1" | ruff check --quiet --stdin-filename "$1" - >/dev/null 2>&1 &&
		git show "$base:$1" | ruff format --check --quiet --stdin-filename "$1" - >/dev/null 2>&1
}

for f in "${files[@]}"; do
	if git cat-file -e "$base:$f" 2>/dev/null && ! clean_at_base "$f"; then
		before=$(git show "$base:$f" | count "$f")
		after=$(count "$f" < "$f")
		if [ "$after" -gt "$before" ]; then
			echo "::error file=$f::legacy file: ruff findings went from $before to $after"
			ruff check "$f"
			status=1
		else
			echo "legacy file (not required to pass): $f ($before -> $after ruff findings)"
		fi
	else
		ruff check "$f" || status=1
		ruff format --check --diff "$f" || status=1
	fi
done
exit $status
