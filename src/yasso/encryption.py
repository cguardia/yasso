
from Crypto.Cipher import AES
from base64 import urlsafe_b64decode
from base64 import urlsafe_b64encode
import hashlib
import hmac
import os
import tempfile
import time

try:
    import simplejson as json
except ImportError:
    import json


class KeyWriter(object):
    """Generate and automatically expire keys.

    The keys are stored in a filesystem directory.  They are removed
    automatically from the directory when they expire.
    """

    def __init__(self, dirpath, length=64, freshness=300, timeout=3600):
        self.dirpath = dirpath
        self.length = length
        self.freshness = freshness
        self.timeout = timeout
        self.current_key_created = 0
        self.current_key_id = None
        self.current_key = None

    def get_fresh_key(self):
        """Return a fresh (key_id, key) tuple."""
        now = time.time()
        if (not self.current_key_created
                or now >= self.current_key_created + self.freshness):
            self._prune()
            f = tempfile.NamedTemporaryFile(
                prefix='', dir=self.dirpath, delete=False)
            key_id = bytes(os.path.basename(f.name))
            key = os.urandom(self.length)
            f.write(key)
            f.close()
            self.current_key_id = key_id
            self.current_key = key
            self.current_key_created = now
        return self.current_key_id, self.current_key

    def _prune(self):
        now = time.time()
        for name in os.listdir(self.dirpath):
            if name.startswith('.'):
                continue
            fn = os.path.join(self.dirpath, name)
            ctime = os.path.getctime(fn)
            if now >= ctime + self.timeout:
                # Too old.
                os.remove(fn)


class KeyReader(object):
    """Read keys generated by a KeyWriter."""

    def __init__(self, dirpath, timeout=3600):
        self.dirpath = dirpath
        self.timeout = timeout
        self.keys = {}  # bytes(key_id): (create_time, key)

    def get_key(self, key_id):
        if not isinstance(key_id, bytes):
            raise TypeError("key_id must be a bytes object")
        now = time.time()
        try:
            ctime, key = self.keys[key_id]
        except KeyError:
            if key_id.startswith(b'.') or b'/' in key_id or b'\\' in key_id:
                raise
            fn = os.path.join(self.dirpath, key_id.decode('ascii'))
            if not os.path.exists(fn):
                raise
            ctime = os.path.getctime(fn)
            if now >= ctime + self.timeout:
                # The file is too old.
                raise
            f = open(fn)
            key = f.read()
            f.close()
            self.keys[key_id] = (ctime, key)
        else:
            if now >= ctime + self.timeout:
                # The key in self.keys is too old.
                self._prune()
                raise KeyError(key_id)
        return key

    def _prune(self):
        now = time.time()
        for key_id, (ctime, _key) in self.keys.items():
            if now >= ctime + self.timeout:
                del self.keys[key_id]


class Encryptor(object):
    """Encrypt, sign, and base-64 encode objects.

    yasso.authz uses this to prepare auth codes and access tokens.
    """

    def __init__(self, key_writer):
        self.key_writer = key_writer

    def b64encode(self, s):
        """Convert bytes to an URL-safe base64 encoded string."""
        return urlsafe_b64encode(s).split('=', 1)[0].decode('ascii')

    def __call__(self, data):
        """Encrypt, sign, and base64 encode JSON compatible objects."""
        to_encrypt = json.dumps(data, separators=(',', ':'))
        iv = os.urandom(16)
        key_id, key = self.key_writer.get_fresh_key()
        hmac_key = key[:32]
        aes_key = key[32:]
        aes = AES.new(aes_key, AES.MODE_CFB, iv)  # @UndefinedVariable
        encrypted = aes.encrypt(to_encrypt)
        to_sign = iv + encrypted
        signature = hmac.new(hmac_key, to_sign, hashlib.sha256).digest()
        to_encode = b''.join([b'\0', key_id, b'\0', signature, to_sign])
        return self.b64encode(to_encode)


class DecryptionError(Exception):
    """Decryption failed."""


class Decryptor(object):
    """Decrypt objects encrypted by Encryptor.

    yasso.resource uses this to read and verify access tokens.
    """

    def __init__(self, key_reader):
        self.key_reader = key_reader

    def b64decode(self, s):
        """Convert an URL-safe base64 encoded string to bytes."""
        if not isinstance(s, bytes):
            s = s.encode('ascii')
        pad_chars = (4 - len(s)) % 4
        return urlsafe_b64decode(s + b'=' * pad_chars)

    def __call__(self, s):
        data = self.b64decode(s)
        if data[0] != b'\0':
            raise DecryptionError("Unknown format")
        pos = data.find(b'\0', 1)
        if pos < 1:
            raise DecryptionError("key_id missing from input")
        key_id = data[1:pos]
        # get_key may raise KeyError.
        key = self.key_reader.get_key(key_id)

        hmac_key = key[:32]
        aes_key = key[32:]
        signature = data[pos + 1:pos + 33]
        signed = data[pos + 33:]
        h = hmac.new(hmac_key, signed, hashlib.sha256).digest()
        if h != signature:
            raise DecryptionError("Signature mismatch")

        iv = signed[:16]
        encrypted = signed[16:]
        aes = AES.new(aes_key, AES.MODE_CFB, iv)  # @UndefinedVariable
        data = aes.decrypt(encrypted)
        return json.loads(data)
