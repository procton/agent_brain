"""Auth throttle on POST /api/auth/browser-session (P0 hardening).

Repeated wrong access codes close a short guard (429 + Retry-After) instead
of allowing an unthrottled guessing loop. A correct code always succeeds once
the guard lapses; success resets the failure counter.
"""

from __future__ import annotations

from backend.app.security import AuthThrottle


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


async def test_guard_closes_after_repeated_failures_then_reopens(client):
    from backend.app.security import AuthThrottle

    clock = FakeClock()
    client.harness.app.state.auth_throttle = AuthThrottle(now=clock)
    code = client.harness.dashboard_code

    for _ in range(4):
        response = await client.login(code="wrong-code")
        assert response.status_code == 403
    # Guards normalize: 4th wrong attempt is still 403, and no lock yet.
    assert (await client.login(code="wrong-code")).status_code == 403

    # Guard is closed: even the CORRECT code is refused with 429 + Retry-After.
    locked = await client.login(code=code)
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers

    # Once the lock lapses, the correct code works and resets the counter.
    clock.value += 60
    unlocked = await client.login(code=code)
    assert unlocked.status_code == 200, unlocked.text

    # A successful reset means failures restart from zero.
    wrong = await client.login(code="wrong-code")
    assert wrong.status_code == 403


def test_throttle_lock_steps_exponentially_and_never_beyond_max():
    clock = FakeClock()
    throttle = AuthThrottle(now=clock, max_failures=3, base_lock_seconds=10, max_lock_seconds=25)

    for _ in range(3):
        throttle.record_failure()
    assert throttle.locked_for() == 10.0

    clock.value += 10  # first lock lapses; failures keep accumulating
    throttle.record_failure()
    assert throttle.locked_for() == 20.0

    clock.value += 20
    throttle.record_failure()
    assert throttle.locked_for() == 25.0  # capped

    throttle.reset()
    assert throttle.locked_for() == 0.0
