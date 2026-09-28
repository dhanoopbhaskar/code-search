import pytest

from src.engine.redactor import Redactor


def test_redact_api_key() -> None:
    redactor = Redactor()
    text = 'API_KEY = "sk-1234567890abcdef"'
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result
    assert "sk-1234567890abcdef" not in result


def test_redact_jwt() -> None:
    redactor = Redactor()
    text = "token = eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.dGVzdA"
    result, count = redactor.redact(text)
    assert count >= 1
    assert "[REDACTED]" in result


def test_redact_aws_key() -> None:
    redactor = Redactor()
    text = "aws_key = AKIAIOSFODNN7EXAMPLE"
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_private_key() -> None:
    redactor = Redactor()
    text = "-----BEGIN PRIVATE KEY-----\nABC123\n-----END PRIVATE KEY-----"
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_password() -> None:
    redactor = Redactor()
    text = 'password = "supersecret123"'
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_github_token() -> None:
    redactor = Redactor()
    text = "token = ghp_123456789012345678901234567890123456"
    result, count = redactor.redact(text)
    assert count >= 1
    assert "[REDACTED]" in result


def test_redact_connection_string() -> None:
    redactor = Redactor()
    text = "postgres://user:password123@localhost:5432/db"
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_no_secrets() -> None:
    redactor = Redactor()
    text = "def hello(): return 'world'"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_empty_string() -> None:
    redactor = Redactor()
    result, count = redactor.redact("")
    assert count == 0
    assert result == ""


def test_redact_multiple_secrets() -> None:
    redactor = Redactor()
    text = 'API_KEY = "sk-12345"\npassword = "hunter2"\ndef normal(): pass'
    result, count = redactor.redact(text)
    assert count >= 2
    assert "[REDACTED]" in result
    assert "normal" in result


def test_redact_results_list() -> None:
    redactor = Redactor()
    results = [
        {"content": 'api_key = "sk_abcdefghij"', "redacted_count": 0},
        {"content": "def safe(): pass", "redacted_count": 0},
    ]
    redacted = redactor.redact_results(results)
    assert redacted[0]["redacted_count"] == 1
    assert redacted[1]["redacted_count"] == 0
    assert "[REDACTED]" in redacted[0]["content"]


def test_false_positive_avoidance() -> None:
    redactor = Redactor()
    text = "The variable `api_key` is used for authentication"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_slack_token() -> None:
    redactor = Redactor()
    text = "xoxb-1234567890-1234567890123-abc123def456"
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_npm_token() -> None:
    redactor = Redactor()
    text = "npm_npmpUBLISHtoken1234567890abcdefghijk"
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result


def test_redact_already_redacted() -> None:
    redactor = Redactor()
    text = "key = [REDACTED]"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_overlapping_patterns() -> None:
    redactor = Redactor()
    text = 'api_key="sk-abcdefghijklmnop"'
    result, count = redactor.redact(text)
    assert count == 1
    assert "[REDACTED]" in result
    assert "sk-abcdefghijklmnop" not in result


def test_redact_adjacent_patterns_merged() -> None:
    redactor = Redactor()
    text = 'password="secret123"api_key="sk-abcdefghij"'
    result, count = redactor.redact(text)
    assert count >= 1
    assert "[REDACTED]" in result


def test_redact_nested_overlapping_matches() -> None:
    redactor = Redactor()
    text = 'export API_KEY="sk-abcdefghijklmnop" and password="secret123"'
    result, count = redactor.redact(text)
    assert count >= 1
    assert "[REDACTED]" in result


def test_redact_no_interference_between_patterns() -> None:
    redactor = Redactor()
    text = "prefix_with_sk_abcdefghijklmnop_123"
    _, count = redactor.redact(text)
    assert count == 0


def test_redact_does_not_mangle_code_expression() -> None:
    redactor = Redactor()
    text = "String token = authHeader.substring(6);"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_does_not_mangle_method_call_assignment() -> None:
    redactor = Redactor()
    text = "jwt.secret = myService.getSecret()"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_keeps_assignment_code() -> None:
    redactor = Redactor()
    text = "token = authHeader.substring(6);\nsecret = loadSecret(env);"
    result, count = redactor.redact(text)
    assert count == 0
    assert result == text


def test_redact_genuine_quoted_secrets_stay_masked() -> None:
    redactor = Redactor()
    text = 'String token = "Bearer sk-abcdefghijklmnop";'
    result, count = redactor.redact(text)
    assert count >= 1
    assert "sk-abcdefghijklmnop" not in result


def test_redact_quoted_jwt_secret_stays_masked() -> None:
    redactor = Redactor()
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    result, count = redactor.redact(f'jwt.secret = "{jwt}"')
    assert count >= 1
    assert jwt not in result


def test_redact_connection_string_stays_masked() -> None:
    redactor = Redactor()
    text = "jdbc_url = postgres://admin:secretpass123@db.internal:5432/app"
    result, count = redactor.redact(text)
    assert count >= 1
    assert "secretpass123" not in result


def test_air_gap_exemption() -> None:
    import socket

    from src.engine.redactor import air_gap_enforcement, allow_downloads

    with air_gap_enforcement(), pytest.raises(RuntimeError, match="Air-gap violation"):
        socket.socket().connect(("example.com", 80))

    with air_gap_enforcement(), allow_downloads():
        result = socket.socket().connect_ex(("127.0.0.1", 1))
        assert result != 0

    with air_gap_enforcement(), pytest.raises(RuntimeError, match="Air-gap violation"):
        socket.socket().connect(("example.com", 80))
