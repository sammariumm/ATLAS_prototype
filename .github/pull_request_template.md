## Summary

<!-- 2-3 sentences explaining the main objective. -->

This pull request introduces a new feature implemented with the assistance of Claude Code to streamline user authentication. It securely integrates OAuth2 login flows and updates the corresponding frontend components to handle session states.

## What Changed

- **`src/auth/oauth.ts`**: Added the core OAuth2 authentication handler and token exchange logic.
- **`src/components/LoginButton.tsx`**: Updated the UI component to trigger the new auth flow and handle loading/error states.
- **`tests/auth.test.ts`**: Added comprehensive unit tests covering successful logins and edge-case error handling.

## Why

<!-- The motivation or problem being solved. -->

Users previously lacked a streamlined single sign-on (SSO) option, leading to higher friction during onboarding and increased password-reset support tickets. This change modernizes our auth stack and improves overall user retention.

## Testing Done

<!-- How these changes were verified or tested. -->

- [ ] Ran unit and integration tests via `npm test` (all passing).
- [ ] Performed manual testing of the OAuth flow in a local staging environment.
- [ ] **Claude Code Verification:** Thoroughly reviewed all generated code for security vulnerabilities (e.g., proper token storage and state validation) and cleaned up extraneous boilerplate.

## Breaking Changes / Risks

None. The legacy password-authentication flow remains intact as a fallback while the new OAuth implementation rolls out.
