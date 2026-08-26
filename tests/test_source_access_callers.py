from ghost_protocol.application import worker_contracts


def test_batch_worker_keeps_auto_refresh_off_by_default() -> None:
    payload = worker_contracts.build_batch_gen_worker_kwargs(
        {},
        log_q=object(),
        stop_ev=object(),
    )

    assert payload["auto_refresh"] is False


def test_batch_worker_allows_explicit_auto_refresh_for_infinite_mode() -> None:
    payload = worker_contracts.build_batch_gen_worker_kwargs(
        {},
        log_q=object(),
        stop_ev=object(),
        auto_refresh=True,
    )

    assert payload["auto_refresh"] is True
