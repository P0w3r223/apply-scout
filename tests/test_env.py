"""Loading a local .env: parsing, precedence, and not leaking values."""

from __future__ import annotations

from apply_scout.env import load_dotenv, parse_dotenv


def test_parses_assignments_and_ignores_noise():
    parsed = parse_dotenv(
        "\n".join(
            [
                "# a comment",
                "",
                "ANTHROPIC_API_KEY=sk-abc",
                "export GITHUB_TOKEN=ghp_xyz",
                '  QUOTED="spaced value"  ',
                "SINGLE='single'",
                "not-an-assignment",
            ]
        )
    )

    assert parsed == {
        "ANTHROPIC_API_KEY": "sk-abc",
        "GITHUB_TOKEN": "ghp_xyz",
        "QUOTED": "spaced value",
        "SINGLE": "single",
    }


def test_a_hash_inside_a_value_is_kept():
    """Guessing where an inline comment starts would corrupt a key that contains '#'."""
    assert parse_dotenv("KEY=sk-a#b")["KEY"] == "sk-a#b"


def test_an_empty_value_stays_empty_rather_than_being_dropped():
    assert parse_dotenv("KEY=") == {"KEY": ""}


def test_loads_into_the_environment_and_reports_only_names(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
    environ: dict[str, str] = {}

    applied = load_dotenv(env_file, environ=environ)

    assert applied == ("ANTHROPIC_API_KEY",)  # the name is safe to log, the value is not
    assert environ["ANTHROPIC_API_KEY"] == "sk-secret"


def test_an_exported_variable_wins_over_the_file(tmp_path):
    """A stale file must never override what the shell or CI explicitly set."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    environ = {"ANTHROPIC_API_KEY": "from-shell"}

    applied = load_dotenv(env_file, environ=environ)

    assert applied == ()
    assert environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_a_missing_file_is_not_an_error(tmp_path):
    """Running with no .env is the normal case in CI and under cassette replay."""
    environ: dict[str, str] = {}
    assert load_dotenv(tmp_path / "absent.env", environ=environ) == ()
    assert environ == {}


def test_a_directory_in_place_of_the_file_is_tolerated(tmp_path):
    directory = tmp_path / ".env"
    directory.mkdir()
    assert load_dotenv(directory, environ={}) == ()
