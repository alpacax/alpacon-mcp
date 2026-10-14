"""Step-up links remembered per person, client instance and origin."""

import jwt

from utils.step_up import StepUpLinks, step_up_key

NAMESPACE = 'https://alpacon.io/'
ORIGIN = 'https://alpacax.dev.alpacon.io'


def make_jwt(sub='auth0|alice', instance='mfa_c_device-1'):
    claims = {'sub': sub}
    if instance is not None:
        claims[f'{NAMESPACE}client_instance'] = instance
    return jwt.encode(claims, 'test-secret-for-step-up-claims-only', algorithm='HS256')


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_key_is_sub_client_instance_and_origin():
    # Given a token naming alice on device-1
    token = make_jwt()
    # When the key is derived
    key = step_up_key(token, ORIGIN)
    # Then it pairs the two with the origin
    assert key == ('auth0|alice', 'mfa_c_device-1', ORIGIN)


def test_token_without_client_instance_has_no_key():
    # Given a token with no client instance claim
    token = make_jwt(instance=None)
    # When the key is derived
    key = step_up_key(token, ORIGIN)
    # Then there is none, so nothing is remembered for it
    assert key is None


def test_remembered_link_is_returned_within_its_lifetime():
    # Given a link remembered 599 seconds ago
    clock = FakeClock()
    links = StepUpLinks(clock=clock)
    links.remember(('auth0|alice', 'mfa_c_device-1', ORIGIN), 'https://auth/link-1')
    clock.now += 599
    # When it is looked up
    result = links.get(('auth0|alice', 'mfa_c_device-1', ORIGIN))
    # Then it is still there
    assert result == 'https://auth/link-1'


def test_link_expires_after_its_lifetime():
    # Given a link remembered exactly 600 seconds ago
    clock = FakeClock()
    links = StepUpLinks(clock=clock)
    links.remember(('auth0|alice', 'mfa_c_device-1', ORIGIN), 'https://auth/link-1')
    clock.now += 600
    # When it is looked up
    result = links.get(('auth0|alice', 'mfa_c_device-1', ORIGIN))
    # Then it is gone
    assert result is None


def test_links_are_kept_apart_per_user_client_instance_and_origin():
    # Given a link remembered for alice on device-1
    links = StepUpLinks(clock=FakeClock())
    links.remember(('auth0|alice', 'mfa_c_device-1', ORIGIN), 'https://auth/link-1')
    # When bob, alice on another device, and alice on another origin look up
    bob = links.get(('auth0|bob', 'mfa_c_device-1', ORIGIN))
    other_device = links.get(('auth0|alice', 'mfa_c_device-2', ORIGIN))
    other_origin = links.get(('auth0|alice', 'mfa_c_device-1', 'https://b.example'))
    # Then none receives alice's link
    assert bob is None
    assert other_device is None
    assert other_origin is None


def test_forget_removes_the_link():
    # Given a remembered link
    links = StepUpLinks(clock=FakeClock())
    links.remember(('auth0|alice', 'mfa_c_device-1', ORIGIN), 'https://auth/link-1')
    # When it is forgotten
    links.forget(('auth0|alice', 'mfa_c_device-1', ORIGIN))
    # Then it is no longer returned
    assert links.get(('auth0|alice', 'mfa_c_device-1', ORIGIN)) is None


def test_store_drops_the_oldest_link_past_its_capacity():
    # Given a store that holds two links, already full
    clock = FakeClock()
    links = StepUpLinks(max_entries=2, clock=clock)
    links.remember(('auth0|a', 'i', ORIGIN), 'https://auth/a')
    clock.now += 1
    links.remember(('auth0|b', 'i', ORIGIN), 'https://auth/b')
    clock.now += 1
    # When a third is remembered
    links.remember(('auth0|c', 'i', ORIGIN), 'https://auth/c')
    # Then the oldest is dropped and the newer two remain
    assert links.get(('auth0|a', 'i', ORIGIN)) is None
    assert links.get(('auth0|b', 'i', ORIGIN)) == 'https://auth/b'
    assert links.get(('auth0|c', 'i', ORIGIN)) == 'https://auth/c'
