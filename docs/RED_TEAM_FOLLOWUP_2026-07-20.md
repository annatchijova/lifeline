# Red-Team Follow-up — HTTP Recovery

**Author:** ChatGPT 5.6 Terra

**Method:** Abduction → deduction → induction

**Vulnerable base:** `b2a1ba5`
**Scope:** Local loopback HTTP parsing only. This is not an audit of remote
deployment, authentication strength, or report truth.

## Threat model

- The caller can reach the local loopback server and holds a valid coordinator
  bearer token.
- The caller can send a syntactically malformed HTTP header.
- The caller cannot alter LIFELINE code, seals, or the operator database.

## RT-06 — Non-numeric `Content-Length` drops an authenticated request

**Severity:** Low

**Epistemic level:** CONFIRMED BY INDUCTION
**Bucket:** Software vulnerability (local availability)

### Surprise

Every malformed API request is expected to produce a JSON `4xx` response. A
local administrative tool cannot reliably distinguish a bad request from a
disconnected server if malformed input instead terminates the connection.

### Code fact

At the vulnerable base, `RoomHandler._json_body()` evaluated
`int(self.headers.get("Content-Length") or 0)` outside a `ValueError` handler.

### Deduction

If an authenticated request supplies `Content-Length:
definitely-not-a-number`, parsing will raise `ValueError` in the handler. The
server thread will close the socket without an HTTP response, and no approval
will be recorded.

### Induction

An actual loopback socket request with a valid coordinator token and that
header produced the server traceback and `NO_RESPONSE`. This confirmed the
prediction on the approval endpoint. It did not create an approval and did not
cross the dispatch-authority boundary.

### Fix and regression

`_json_body()` now converts that `ValueError` into `ApiError(400,
"Content-Length must be an integer")`. The socket-level regression asserts an
`HTTP/1.0 400` response containing that message.

## Falsified adjacent vector

| Vector | Prediction | Result |
| --- | --- | --- |
| Re-sealed but structurally empty `verification.json` | Offline verification crashes after the hash passes. | **FALSIFIED** — the semantic verifier returns `FAIL (unsupported verification_version)` without a traceback. |

## Boundary note

This finding requires an already authenticated local coordinator. It is not a
remote unauthenticated denial of service claim. Slow-client resource limits are
separate hardening work and were not exercised in this focused pass.
