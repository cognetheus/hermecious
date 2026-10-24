# ADR-012: Source adapters fetch by provider-scoped key, never by URL; P2.1 is offline-only

- **Status:** Accepted. A contract clarification directed by Batch 03 §P2.1.1, "Important URI boundary".
- **Date:** 2026-10-24
- **Source:** blueprint §4 P2.1 (`fetch(url) -> SourceObservation`), Batch 03 §P2.1

## Context

The blueprint sketches `fetch(url)`. A URL-taking fetch is a general-purpose egress primitive, and an SSRF risk the moment a URL comes from a provider response, an operator form or a model. Batch 03 states that `fetch(url)` is an interface *intent*, not authorization for arbitrary egress.

## Decision

1. **`SourceAdapter.fetch(*, source_key)`** takes a provider-scoped key returned by that provider's own `search`. There is **no operation that accepts an arbitrary URL**, and none is exposed to operators or language models.
2. **Adapters return raw mappings; the framework validates everything** (`SourcePage`, `SourceCandidate`, `SourceObservation`). Adapters are untrusted, and one bad record is rejected individually without poisoning the page.
3. **Every provider has a reviewed `SourceDescriptor`:** terms reference, rights policy version, review date, permitted operations, storage ceiling, retention TTL, quotas, page size, allowed hostnames, credentials flag, enabled flag and environments. Anything missing or disabled fails closed **before** the adapter is called.
4. **P2.1 enables only `source_kind = fixture`**, in development and test. Any non-fixture descriptor is refused (`live_sources_not_enabled`) until P2.2 adds a reviewed real source.
5. **Source URLs carried in candidates or observations are provenance strings, never fetched.** They are screened by the P1.2 URL policy plus the descriptor's hostname allowlist.

## Consequences for P2.2

A real adapter that needs network access must:
- implement a fetch client bound to the descriptor's `allowed_hostnames`, with DNS-resolution and redirect checks that reject private, loopback, link-local and metadata addresses after resolution;
- enforce rate limits and quotas from the descriptor;
- never accept URLs from responses as fetch targets without passing the same allowlist;
- record its rights review in the descriptor;
- relax `live_sources_not_enabled` only for that reviewed provider.

## Rollback

Disable a provider by setting `enabled=False` in its descriptor, which fails closed. Already-stored provenance rows remain.
