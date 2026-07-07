from app.rag.cli import _normalize_argv  # pyright: ignore[reportPrivateUsage]


def test_normalize_argv_defaults_to_sync_when_no_command() -> None:
    assert _normalize_argv([]) == ["sync"]
    assert _normalize_argv(["--plain"]) == ["sync", "--plain"]
    assert _normalize_argv(["--force-rebuild"]) == ["sync", "--force-rebuild"]


def test_normalize_argv_preserves_explicit_sync_after_global_flags() -> None:
    assert _normalize_argv(["--plain", "sync"]) == ["--plain", "sync"]
    assert _normalize_argv(["-v", "sync", "--force-rebuild"]) == ["-v", "sync", "--force-rebuild"]
    assert _normalize_argv(["--plain", "-v", "sync", "--job-name", "manual"]) == [
        "--plain",
        "-v",
        "sync",
        "--job-name",
        "manual",
    ]


def test_normalize_argv_does_not_treat_job_name_sync_as_subcommand() -> None:
    assert _normalize_argv(["--job-name", "sync"]) == ["sync", "--job-name", "sync"]
    assert _normalize_argv(["--job-name=sync"]) == ["sync", "--job-name=sync"]


def test_normalize_argv_keeps_top_level_help_and_version() -> None:
    assert _normalize_argv(["--help"]) == ["--help"]
    assert _normalize_argv(["--version"]) == ["--version"]
