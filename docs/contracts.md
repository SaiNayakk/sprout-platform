# Contracts

Every API and event is defined in [sprout-contracts](https://github.com/SaiNayakk/sprout-contracts)
before any code implements it.

- **APIs**: OpenAPI 3.0, one file per service and major version (`identity-v1.yaml`).
- **Events**: JSON Schema 2020-12, one file per event and version (`identity/user-registered.v1`),
  each with an example that CI validates against it.

## Contracts are enforced, not documented

| Where | What is checked |
|---|---|
| Contracts CI | Every spec parses, every event example matches its schema, and **no breaking change** against the last release (`openapi-diff`). A breaking change needs a new major version. |
| Service tests | Every response the service returns in its tests is validated against the contract it claims to implement. A field renamed in code but not in the contract fails the build. |
| Pre-prod | The end-to-end suite exercises the released services through the gateway. |

## Versioning

Contracts are released as git tags and published as a Maven artifact. A service depends on an exact
contract version. Additive changes (a new optional field, a new response) are minor versions; anything
that could break an existing client is a new major version served side by side.

Example: identity `v0.2.1` started returning `503` with `Retry-After` when its database is unreachable
(see [CHAOS-01](testing/chaos.md#chaos-01)). That was added to the contract first, as `v0.2.0`, and the
breaking-change check confirmed it was compatible.
