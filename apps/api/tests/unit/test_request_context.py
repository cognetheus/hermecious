import pytest

from app.core.request_context import accept_request_id, bound_request_id, current_request_id, new_request_id


def test_new_ids_are_prefixed_and_unique() -> None:
    ids = {new_request_id() for _ in range(1_000)}
    assert len(ids) == 1_000
    assert all(i.startswith("req_") and len(i) == 36 for i in ids)


@pytest.mark.parametrize("candidate", ["abcdefgh", "req_0123456789abcdef", "trace-1.2_3", "A" * 64])
def test_safe_client_ids_are_kept(candidate: str) -> None:
    assert accept_request_id(candidate) == candidate


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        "",
        "short",
        "A" * 65,
        "x" * 10_000,
        "abc\ndefghij",
        'abcdefgh"},"level":"critical',
        "abcdefgh ijkl",
        "../../../etc/passwd",
        "-leadingdash",
        "unicodé-ñame",
    ],
)
def test_unsafe_client_ids_are_replaced(candidate: str | None) -> None:
    replaced = accept_request_id(candidate)
    assert replaced != candidate
    assert replaced.startswith("req_")


def test_binding_is_scoped_and_nested() -> None:
    assert current_request_id() is None
    with bound_request_id("req_outer_0001"):
        with bound_request_id("req_inner_0001"):
            assert current_request_id() == "req_inner_0001"
        assert current_request_id() == "req_outer_0001"
    assert current_request_id() is None


def test_binding_is_cleared_after_an_exception() -> None:
    with pytest.raises(RuntimeError), bound_request_id("req_failing_01"):
        raise RuntimeError("job failed")
    assert current_request_id() is None
