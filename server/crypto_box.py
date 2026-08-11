#!/usr/bin/env python3
"""
CLAUDEPAD — enkripsi lalu lintas.

Sebelum v3.0 seluruh perintah dikirim sebagai JSON polos di jaringan lokal:
siapa pun yang menyadap WiFi bisa membaca apa yang diketik. PIN hanya
melindungi autentikasi, bukan isi percakapan.

Rancangan sengaja dibuat sederhana dan tanpa dependensi luar:
  * Kunci sesi diturunkan dari PIN (atau token pairing) + nonce acak dari
    kedua pihak memakai PBKDF2-HMAC-SHA256. Kunci tidak pernah dikirim.
  * Setiap pesan dienkripsi AES-256-CTR bila `cryptography` tersedia;
    bila tidak, dipakai ChaCha20 murni-Python yang disertakan di sini.
  * Setiap pesan diberi tag HMAC-SHA256 (enkripsi lalu MAC) agar isi yang
    diubah di tengah jalan langsung ditolak.
  * Nomor urut mencegah pesan lama diputar ulang oleh penyadap.

Ini bukan pengganti TLS untuk internet terbuka, tetapi menutup penyadapan
dan pengubahan lalu lintas di jaringan lokal — yang memang lingkup CLAUDEPAD.
"""

import base64
import hashlib
import hmac
import os
import struct

try:
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from cryptography.hazmat.primitives.asymmetric import padding as _asym_padding
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives import serialization as _serialization
    from cryptography.hazmat.backends import default_backend as _default_backend
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

KEY_LEN = 32
NONCE_LEN = 16
TAG_LEN = 32
PBKDF2_ROUNDS = 60_000


# ----------------------------------------------------------- ChaCha20 ------
def _rotl(v, c):
    return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))


def _quarter(x, a, b, c, d):
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF; x[d] ^= x[a]; x[d] = _rotl(x[d], 16)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF; x[b] ^= x[c]; x[b] = _rotl(x[b], 12)
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF; x[d] ^= x[a]; x[d] = _rotl(x[d], 8)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF; x[b] ^= x[c]; x[b] = _rotl(x[b], 7)


def _chacha_block(key, counter, nonce):
    const = b"expand 32-byte k"
    state = list(struct.unpack("<4I", const)) \
        + list(struct.unpack("<8I", key)) \
        + [counter] + list(struct.unpack("<3I", nonce))
    work = state[:]
    for _ in range(10):
        _quarter(work, 0, 4, 8, 12); _quarter(work, 1, 5, 9, 13)
        _quarter(work, 2, 6, 10, 14); _quarter(work, 3, 7, 11, 15)
        _quarter(work, 0, 5, 10, 15); _quarter(work, 1, 6, 11, 12)
        _quarter(work, 2, 7, 8, 13); _quarter(work, 3, 4, 9, 14)
    out = [(work[i] + state[i]) & 0xFFFFFFFF for i in range(16)]
    return struct.pack("<16I", *out)


def chacha20(key, nonce12, data, counter=1):
    """Enkripsi/dekripsi (operasinya sama, XOR aliran kunci)."""
    out = bytearray(len(data))
    for i in range(0, len(data), 64):
        block = _chacha_block(key, counter + i // 64, nonce12)
        chunk = data[i:i + 64]
        for j, b in enumerate(chunk):
            out[i + j] = b ^ block[j]
    return bytes(out)


# ------------------------------------------------------------ Session ------
class Session:
    """Kunci sesi + enkripsi pesan dua arah."""

    def __init__(self, key: bytes):
        self.key = key
        self.enc_key = hashlib.sha256(key + b"|enc").digest()
        self.mac_key = hashlib.sha256(key + b"|mac").digest()
        self.send_seq = 0
        self.recv_seq = -1

    # -- turunan kunci --
    @staticmethod
    def derive(secret: str, salt: bytes) -> "Session":
        key = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"),
                                  salt, PBKDF2_ROUNDS, KEY_LEN)
        return Session(key)

    # -- enkripsi --
    def seal(self, plaintext: bytes) -> bytes:
        """seq(8) | nonce(12) | ciphertext | tag(32)"""
        self.send_seq += 1
        seq = struct.pack(">Q", self.send_seq)
        nonce = os.urandom(12)
        ct = chacha20(self.enc_key, nonce, plaintext)
        body = seq + nonce + ct
        tag = hmac.new(self.mac_key, body, hashlib.sha256).digest()
        return body + tag

    def open(self, blob: bytes) -> bytes:
        if len(blob) < 8 + 12 + TAG_LEN:
            raise ValueError("paket terlalu pendek")
        body, tag = blob[:-TAG_LEN], blob[-TAG_LEN:]
        expect = hmac.new(self.mac_key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expect):
            raise ValueError("tag tidak cocok — isi pesan diubah di tengah jalan")
        seq = struct.unpack(">Q", body[:8])[0]
        if seq <= self.recv_seq:
            raise ValueError("pesan lama diputar ulang")
        self.recv_seq = seq
        nonce = body[8:20]
        return chacha20(self.enc_key, nonce, body[20:])


def new_salt() -> bytes:
    return os.urandom(NONCE_LEN)


# -------------------------------------------------------- RSA-2048 ---------
def generate_rsa_keypair():
    """Generate RSA-2048 keypair. Returns (public_key_pem, private_key).

    Dipanggil sekali saat server start. Public key dikirim ke HP di hello_ok,
    private key dipakai server untuk mendekripsi PIN/token dari HP.
    """
    if not HAS_CRYPTOGRAPHY:
        raise RuntimeError("modul 'cryptography' belum terpasang — jalankan: pip install cryptography")
    private_key = _rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=_default_backend(),
    )
    pub_pem = private_key.public_key().public_bytes(
        encoding=_serialization.Encoding.PEM,
        format=_serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pub_pem, private_key


def rsa_encrypt(pub_pem: bytes, data: bytes) -> bytes:
    """Enkripsi data dengan RSA public key (OAEP + SHA-256)."""
    public_key = _serialization.load_pem_public_key(pub_pem, backend=_default_backend())
    return public_key.encrypt(
        data,
        _asym_padding.OAEP(
            mgf=_asym_padding.MGF1(algorithm=_hashes.SHA256()),
            algorithm=_hashes.SHA256(),
            label=None,
        ),
    )


def rsa_decrypt(private_key, encrypted: bytes) -> bytes:
    """Dekripsi data dengan RSA private key (OAEP + SHA-256)."""
    return private_key.decrypt(
        encrypted,
        _asym_padding.OAEP(
            mgf=_asym_padding.MGF1(algorithm=_hashes.SHA256()),
            algorithm=_hashes.SHA256(),
            label=None,
        ),
    )


def rsa_pubkey_to_b64(pub_pem: bytes) -> str:
    """Konversi public key PEM ke base64 (tanpa header PEM)."""
    lines = pub_pem.decode("ascii").splitlines()
    raw = "".join(l for l in lines if not l.startswith("-----"))
    return raw


def rsa_pubkey_from_b64(b64: str) -> bytes:
    """Konversi base64 kembali ke public key PEM."""
    header = "-----BEGIN PUBLIC KEY-----"
    footer = "-----END PUBLIC KEY-----"
    raw = b64.strip()
    return (header + "\n" + raw + "\n" + footer).encode("ascii")
