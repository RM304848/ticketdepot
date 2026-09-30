import truststore

from ticketdepot import delays


def test_https_uses_the_os_certificate_store():
    # the packaged app has no CA bundle of its own; the OS store must be used
    assert isinstance(delays._tls(), truststore.SSLContext)
