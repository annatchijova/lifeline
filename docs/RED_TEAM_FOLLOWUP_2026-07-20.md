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

## RT-07 — Incident subroutes read the body before authorization

**Severity:** Low

**Epistemic level:** CONFIRMED BY INDUCTION

**Bucket:** Software vulnerability (local availability)

### Surprise

An unauthenticated caller should be rejected before the server waits for an
untrusted request body. Otherwise a local process can hold handler threads by
declaring a small body and never sending it.

### Code fact

At the vulnerable base `51cdef4`, `_post_incident()` called `_json_body()`
before its action-specific `_operator(...)` check. The top-level
`POST /api/incidents` path already used the safer order, but the nested
`/api/incidents/{id}/...` paths did not.

### Deduction and induction

An unauthenticated `POST /api/incidents/not-disclosed/reports` declaring
`Content-Length: 2` with no body should not receive a response while the server
waits for those bytes. A real loopback socket test timed out after 0.5 seconds,
confirming the prediction. Once the client disconnected, the old handler also
attempted to send its eventual 400 response to a closed socket.

### Fix and regression

Each nested incident action now authenticates and authorizes before calling
`_json_body()`. The same incomplete unauthenticated request receives `401`
immediately; the regression is socket-level and asserts the bearer-token
message as well as the status code.

## Scope note after RT-07

The fix prevents unauthenticated callers from occupying a handler while the
body is read. A caller that already has a valid role token can still be a slow
client, because this stdlib prototype intentionally has no global connection
quota or request-read deadline. That is a separate local hardening question,
not evidence that RT-07 remains bypassable.

## RT-08 — Static web serving follows symlinks outside the web root

**Severity:** Medium, conditional

**Epistemic level:** CONFIRMED BY INDUCTION

**Bucket:** Software vulnerability

### Threat-model precondition

The attacker can introduce a symlink into the static `web/` tree but cannot
directly read its target. This can arise from a less-trusted static-asset write
path or an unreviewed checkout artifact. It is not a claim that an attacker
who can arbitrarily modify Python source needs this vector.

### Code fact, deduction, and induction

At the vulnerable base, `/web/...` delegated to
`SimpleHTTPRequestHandler`, which follows filesystem symlinks. A temporary
web tree containing `linked.txt -> server-readable-synthetic-secret.txt` was
served through the real loopback endpoint. The observed response was `HTTP
200` with the synthetic secret bytes.

### Fix and regression

Static web files now open component-by-component relative to a descriptor for
the trusted `web/` directory. Every directory component and the final file use
`O_NOFOLLOW`; the final descriptor must also be a regular file. GET and HEAD
of the synthetic symlink now return `404`, while normal bundled static assets
continue to load.

## RT-09 — Authenticated incomplete bodies have no read deadline

**Severity:** Low

**Epistemic level:** CONFIRMED BY INDUCTION

**Bucket:** Software vulnerability (local availability)

### Threat-model precondition

The caller holds a valid local role token. This is not an unauthenticated
remote slow-client claim; RT-07 already closes the pre-auth variant for
incident subroutes.

### Code fact, deduction, and induction

The stdlib `ThreadingHTTPServer` had no socket read timeout. After a valid
token passed authorization, `_json_body()` could block in `rfile.read(length)`
for a declared but never delivered body. A real coordinator-token socket test
with `Content-Length: 2` and no body timed out at the client, confirming that
the handler had no deadline.

### Fix and regression

Each handler connection now receives a five-second read timeout. A timed-out
body becomes an explicit `408 request body timed out`. The regression lowers
that timeout to 0.1 seconds and verifies the response on the actual server.

## Scope note after RT-09

A per-connection deadline bounds how long one incomplete request holds one
handler. It does not impose a global connection quota, rate limit, or
production reverse-proxy policy. Those are deployment hardening concerns
outside this local prototype's current authority model.

## Discarded capacity vector — full-ledger verification on each write

**Epistemic level:** FALSIFIED as an immediate capacity finding

`IncidentStore.add_report()` verifies the current event chain before it writes
the next revision, so cumulative cost is expected to rise with history length.
The discriminating question was whether that cost is already a practical
fracture for the local prototype.

On Python 3.12 with a fresh SQLite database and the bundled flood scenario,
the following synthetic verified-request additions completed successfully:

| Additions | Total time | Mean per write |
| ---: | ---: | ---: |
| 10 | 0.033 s | 0.0033 s |
| 20 | 0.069 s | 0.0035 s |
| 40 | 0.152 s | 0.0038 s |
| 100 | 0.446 s | 0.0045 s |
| 200 | 1.127 s | 0.0056 s |
| 400 | 3.260 s | 0.0081 s |

The data corroborate cumulative growth but do not demonstrate an operational
failure at this scale. They are not a production throughput benchmark and do
not establish behavior at thousands of events; a checkpoint/index design would
need a stated scale requirement and a separate benchmark before changing the
ledger verification model.
