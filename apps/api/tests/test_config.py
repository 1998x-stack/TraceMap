"""Tests for the stdlib ``.env`` loader (apps/api/tracemap/config.py)."""
import os

from tracemap import config


def test_parse_env_handles_comments_export_and_quotes():
    text = (
        "# a comment\n"
        "\n"
        "A=1\n"
        "export B=\"two\"\n"
        "C='three'\n"
        "QUOTED=\"a b\"\n"
        "EMPTY=\n"
        "not a key value line\n"
        "1INVALID=x\n"
    )
    assert config.parse_env(text) == {
        "A": "1", "B": "two", "C": "three", "QUOTED": "a b", "EMPTY": "",
    }


def test_load_env_file_never_overrides_real_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRACEMAP_TEST_NEW=fromfile\nTRACEMAP_TEST_KEEP=fromfile\n")
    monkeypatch.delenv("TRACEMAP_TEST_NEW", raising=False)
    monkeypatch.setenv("TRACEMAP_TEST_KEEP", "fromenv")

    applied = config.load_env_file(env_file)

    assert os.environ["TRACEMAP_TEST_NEW"] == "fromfile"
    assert os.environ["TRACEMAP_TEST_KEEP"] == "fromenv"  # real env wins
    assert "TRACEMAP_TEST_NEW" in applied
    assert "TRACEMAP_TEST_KEEP" not in applied
    os.environ.pop("TRACEMAP_TEST_NEW", None)  # not tracked by monkeypatch


def test_dotenv_disabled_ignores_the_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRACEMAP_TEST_OFF=1\n")
    monkeypatch.setenv("TRACEMAP_DOTENV", "0")
    monkeypatch.setenv("TRACEMAP_ENV_FILE", str(env_file))
    monkeypatch.delenv("TRACEMAP_TEST_OFF", raising=False)

    assert config.load_default_env() == []
    assert "TRACEMAP_TEST_OFF" not in os.environ


def test_missing_file_is_a_noop(tmp_path):
    assert config.load_env_file(tmp_path / "does-not-exist.env") == []


def test_default_env_file_is_repo_root_dotenv():
    assert config.default_env_file().name == ".env"
    assert (config.repo_root() / "apps" / "api").is_dir()
