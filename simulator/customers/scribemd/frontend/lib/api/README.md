# `lib/api/` — ScribeMD backend client

Thin TypeScript layer over the FastAPI service at
`simulator/customers/scribemd/backend/`. The wire shapes here mirror
[`backend/contract.md`](../../backend/contract.md) — edit the contract
first, then update `types.ts` to match.

## Base URL

Set with the env var `NEXT_PUBLIC_SCRIBEMD_API_URL`. Defaults to
`http://localhost:8001` (the value baked into the dev backend).

```bash
# .env.local
NEXT_PUBLIC_SCRIBEMD_API_URL=https://scribemd-api.dev.example.com
```

The variable is read once at module load in `client.ts`. Trailing
slashes are trimmed.

## Cookies

The backend issues an HTTP-only `scribemd_session` cookie. We can't read
it from JS — every request goes out with `credentials: 'include'` and
the server decides whether the caller is authenticated. The "am I
signed in?" probe is `GET /api/auth/me` (wrapped by `auth.me()`,
returning `null` on 401 instead of throwing).

For the SSE stream, `EventSource` is constructed with
`{ withCredentials: true }` for the same reason.

## Error model

`request()` throws `ApiError` on any non-2xx response and on network
failures (status `0`). The error carries:

- `status` — the HTTP status, or `0` for network errors.
- `detail` — the parsed body. Usually FastAPI's `{ "detail": "..." }`
  envelope; can also be a string or `null` for empty bodies.
- `message` — a human-readable message, derived from `detail` when it
  is a string, otherwise `"Request failed with status N"`.

Hooks surface errors as `error: Error | null`. Components should treat
`error` as opaque for display; if you need to branch on `status`,
narrow with `instanceof ApiError`.

## File layout

| File             | Exports                                                    |
| ---------------- | ---------------------------------------------------------- |
| `types.ts`       | All wire types + `isTerminalStatus`, `isTerminalEvent`     |
| `client.ts`      | `request<T>()`, `apiUrl()`, `ApiError`, `API_BASE_URL`     |
| `auth.ts`        | `login(passkey)`, `logout()`, `me()`                       |
| `encounters.ts`  | `createEncounter()`, `getEncounter()`, `listEncounters()`  |
| `approvals.ts`   | `decideApproval()`                                         |

Hooks live in `hooks/` (one level up) and import from this module via
the `@/lib/api/...` path alias.
