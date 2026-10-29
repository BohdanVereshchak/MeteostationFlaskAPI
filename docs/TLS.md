# Certificates in this project

Checked against the server and firmware source on October 29, 2026.

## The current connection

The ESP32 sends readings to `https://meteo.vereshchak.online:443`. Its HTTP client
uses `esp_crt_bundle_attach`. The firmware's
`sdkconfig.esp32doit-devkit-v1` enables the common public certificate bundle and
does not enable a custom bundle. The build files do not embed certificates from
the server directory.

During the HTTPS handshake, the public endpoint presents its server certificate.
The ESP32 verifies that certificate using the roots bundled into its firmware.
It does not upload `cert.pem` or a CA file with every measurement. Device
authorization and the payload's HMAC signature are separate from TLS.

The current `app.py` starts Waitress on an HTTP port. Waitress does not terminate
TLS itself. HTTPS must be handled by the hosting layer or a reverse proxy in
front of it. The app does not open the local `cert.pem`, `key.pem`, or `rootCA.*`
files. MongoDB's separate outbound TLS connection uses the installed `certifi`
trust store via `certifi.where()`.

```text
ESP32, with a public CA bundle
          |
        HTTPS
          |
Public HTTPS endpoint / reverse proxy
          |
         HTTP
          |
Waitress -> Flask -> MongoDB (its own TLS connection)
```

This describes the current application startup and checked firmware build.
An independently configured proxy or service could still reference local
certificate paths; check its configuration before deleting files it may use.

## What the local files do

| File | Purpose | Needed by the checked application/firmware startup? |
| --- | --- | --- |
| `cert.pem` | The server certificate issued for the earlier local-IP setup | No; needed if a separate TLS listener is configured to present it |
| `key.pem` | The corresponding server private key | No; needed by a TLS listener using that certificate |
| `rootCA.pem` | Public certificate of the custom local certificate authority | No; needed by clients configured to trust that custom CA |
| `rootCA.key` | Private CA signing key, used to issue certificates | No; not required to serve an already-issued certificate; keep offline and private if retained |
| `cert.csr` | Certificate signing request | No runtime role |
| `rootCA.srl` | Serial-number state used when issuing certificates | No runtime role |
| `san.cnf` | OpenSSL certificate-extension/SAN configuration | No runtime role |

The `commands` file records an earlier workflow that generated a local-IP key
and CSR, then signed the certificate using `rootCA.pem` and `rootCA.key`.
That workflow is distinct from the current public-domain HTTPS connection.

The Git history cleanup removed these files from tracking/history, while keeping
their local copies on disk. It did not change your firmware's certificate bundle
or remove files needed by a running service.

If a private key was exposed in Git, removing its history does not make that key
secret again. Replace any exposed key that is still used. If an exposed CA key
is still trusted, replace that CA and the certificates issued under it as part
of the trust-store update. Do not disable TLS verification to work around a
certificate problem.

## References

- [Espressif certificate-bundle example](https://github.com/espressif/esp-idf/tree/master/examples/protocols/https_x509_bundle)
- [Waitress behind a reverse proxy](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html)
