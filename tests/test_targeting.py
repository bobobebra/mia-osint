from pathlib import Path

import pytest

from mia.exceptions import TargetError
from mia.models import TargetType
from mia.targeting import classify_and_validate, detect_target_type


def test_detect_common_targets(tmp_path: Path) -> None:
    file_path = tmp_path / "photo.jpg"
    file_path.write_bytes(b"x")
    assert detect_target_type("person@example.com") == TargetType.EMAIL
    assert detect_target_type("example.com") == TargetType.DOMAIN
    assert detect_target_type("192.0.2.1") == TargetType.IP
    assert detect_target_type("+46701234567") == TargetType.PHONE
    assert detect_target_type("d41d8cd98f00b204e9800998ecf8427e") == TargetType.HASH
    assert detect_target_type(str(file_path)) == TargetType.FILE
    assert detect_target_type("octocat") == TargetType.USERNAME


def test_validate_domain_and_phone() -> None:
    target, kind = classify_and_validate("EXAMPLE.COM.", TargetType.DOMAIN)
    assert target == "example.com"
    assert kind == TargetType.DOMAIN
    phone, _ = classify_and_validate("+46 70-123 45 67", TargetType.PHONE)
    assert phone == "+46701234567"


def test_username_rejects_whitespace() -> None:
    with pytest.raises(TargetError):
        classify_and_validate("Jane Doe", TargetType.USERNAME)
