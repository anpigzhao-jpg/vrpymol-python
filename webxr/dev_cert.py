"""Self-signed HTTPS cert for local WebXR testing.

WebXR (`navigator.xr`) is only available in a "secure context" -- HTTPS, or
the special-cased `localhost` origin. A headset opening this server over the
LAN by IP needs a real (if self-signed) HTTPS connection to get a secure
context at all; plain HTTP silently leaves `VRButton` reporting "VR NOT
SUPPORTED" even on a headset whose browser fully supports WebXR -- not an
error, just a context the API refuses to expose itself in.

Regenerated fresh on every server start (cheap, well under a second) and
scoped to whatever LAN IP this machine currently has, since that changes
across Wi-Fi networks/DHCP leases. The headset's browser will still show a
"connection is not private" interstitial on first visit (self-signed, no
real CA) -- that's expected for local dev HTTPS with no cert authority
involved; proceeding through it once is enough for the session.
"""

import datetime
import ipaddress
import os
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

HERE = os.path.dirname(__file__)
CERT_DIR = os.path.join(HERE, "certs")
CERT_PATH = os.path.join(CERT_DIR, "dev-cert.pem")
KEY_PATH = os.path.join(CERT_DIR, "dev-key.pem")


def lan_ip():
    """Best-effort LAN IP via a UDP "connect" that never sends a packet --
    just asks the OS which local interface/address it would route through."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_dev_cert():
    """Write a fresh self-signed cert/key covering this machine's current LAN
    IP + localhost. Returns (cert_path, key_path, ip)."""
    ip = lan_ip()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "vrpymol-dev")])
    san = x509.SubjectAlternativeName(
        [
            x509.IPAddress(ipaddress.ip_address(ip)),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost"),
        ]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )

    os.makedirs(CERT_DIR, exist_ok=True)
    with open(KEY_PATH, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return CERT_PATH, KEY_PATH, ip
