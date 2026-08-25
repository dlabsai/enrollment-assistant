#!/bin/bash
set -euo pipefail

readonly CLOC_NPM_PACKAGE="cloc@2.6.0-cloc"

if ! command -v git >/dev/null 2>&1; then
    echo "git is required to enumerate tracked files" >&2
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "count-loc.sh must be run inside the repository" >&2
    exit 1
fi

if command -v cloc >/dev/null 2>&1; then
    CLOC=(cloc)
elif command -v npx >/dev/null 2>&1; then
    CLOC=(npx --yes "${CLOC_NPM_PACKAGE}")
else
    echo "cloc or npx is required to count lines of code" >&2
    exit 1
fi

readonly REPO_ROOT=$(git rev-parse --show-toplevel)
readonly TEMP_DIR=$(mktemp -d)
trap 'rm -rf "${TEMP_DIR}"' EXIT

cd "${REPO_ROOT}"

readonly BACKEND_LIST="${TEMP_DIR}/backend.txt"
readonly FRONTEND_LIST="${TEMP_DIR}/frontend.txt"
readonly TEST_LIST="${TEMP_DIR}/tests.txt"
readonly MIGRATION_LIST="${TEMP_DIR}/migrations.txt"
readonly OPERATIONS_LIST="${TEMP_DIR}/operations.txt"
readonly TEMPLATE_LIST="${TEMP_DIR}/templates.txt"

git ls-files | awk \
    -v backend_list="${BACKEND_LIST}" \
    -v frontend_list="${FRONTEND_LIST}" \
    -v test_list="${TEST_LIST}" \
    -v migration_list="${MIGRATION_LIST}" \
    -v operations_list="${OPERATIONS_LIST}" \
    -v template_list="${TEMPLATE_LIST}" \
    '
    /^backend\/(app|scripts)\/.*\.py$/ && !/^backend\/app\/alembic\// {
        print >> backend_list
    }
    /^frontend\/packages\/[^/]+\/.*\.(ts|tsx|js|css|html)$/ &&
        !/^frontend\/packages\/[^/]+\/tests\// {
        print >> frontend_list
    }
    /^backend\/tests\/.*\.py$/ ||
        /^frontend\/packages\/[^/]+\/tests\/.*\.(ts|tsx|js)$/ {
        print >> test_list
    }
    /^backend\/app\/alembic\/versions\/.*\.py$/ {
        print >> migration_list
    }
    /\.sh$/ || /^backend\/Dockerfile$/ {
        print >> operations_list
    }
    /^backend\/app\/chat\/.*\.j2$/ {
        print >> template_list
    }
    '

count_list() {
    local list_file=$1
    local summary

    if [[ ! -s "${list_file}" ]]; then
        printf '0 0\n'
        return
    fi

    summary=$("${CLOC[@]}" --quiet --csv --list-file="${list_file}" \
        | awk -F, '$2 == "SUM" { print $1, $5 }')

    if [[ -z "${summary}" ]]; then
        echo "cloc did not return a summary for ${list_file}" >&2
        exit 1
    fi

    printf '%s\n' "${summary}"
}

read -r backend_files backend_code < <(count_list "${BACKEND_LIST}")
read -r frontend_files frontend_code < <(count_list "${FRONTEND_LIST}")
read -r test_files test_code < <(count_list "${TEST_LIST}")
read -r migration_files migration_code < <(count_list "${MIGRATION_LIST}")
read -r operations_files operations_code < <(count_list "${OPERATIONS_LIST}")
read -r template_files template_code < <(count_list "${TEMPLATE_LIST}")

production_files=$((backend_files + frontend_files))
production_code=$((backend_code + frontend_code))
total_files=$((production_files + test_files + migration_files + operations_files))
total_code=$((production_code + test_code + migration_code + operations_code))

printf 'Git-tracked lines of code (blank/comment lines excluded)\n\n'
printf '%-34s %8s %12s\n' 'Category' 'Files' 'Code LOC'
printf '%-34s %8s %12s\n' '----------------------------------' '--------' '------------'
printf '%-34s %8d %12d\n' 'Backend application' "${backend_files}" "${backend_code}"
printf '%-34s %8d %12d\n' 'Frontend application' "${frontend_files}" "${frontend_code}"
printf '%-34s %8d %12d\n' 'Production application total' "${production_files}" "${production_code}"
printf '%-34s %8d %12d\n' 'Tests' "${test_files}" "${test_code}"
printf '%-34s %8d %12d\n' 'Database migrations' "${migration_files}" "${migration_code}"
printf '%-34s %8d %12d\n' 'Operational shell/Docker code' "${operations_files}" "${operations_code}"
printf '%-34s %8d %12d\n' 'Total code-like LOC' "${total_files}" "${total_code}"
printf '\nExcluded prompt content:\n'
printf '%-34s %8d %12d\n' 'Jinja prompt templates' "${template_files}" "${template_code}"
printf '\nAlso excluded: lockfiles, docs/Lode, config/manifests, binary assets,\n'
printf 'test fixtures, generated/build artifacts, and frontend-widget/.\n'
printf 'cloc de-duplicates identical files by default.\n'
