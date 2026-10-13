## ADDED Requirements

### Requirement: User routes
The frontend SHALL provide the product-book routes `/`, `/login`, `/register`, `/profile`, `/eligibility`, `/pathways`, `/pathways/:id`, `/qa`, `/plan`, `/schools`, `/schools/:id`, `/majors`, `/majors/:id`, `/compare`, and `/favorites`, plus a QA history view reachable from the QA area.

#### Scenario: Visitor explores the product
- **WHEN** a visitor opens the app
- **THEN** they can reach home, eligibility, QA, schools, login, and register without authentication.

#### Scenario: Authenticated user opens protected pages
- **WHEN** an unauthenticated visitor opens profile, plan, favorites, or history
- **THEN** the router redirects to login and preserves the intended destination.

### Requirement: Admin routes
The frontend SHALL provide `/admin/login`, `/admin/docs`, `/admin/index`, `/admin/review`, `/admin/pathways`, and `/admin/stats` within an admin layout, with `/admin` redirecting to the dashboard or first permitted workspace. Navigation SHALL reflect the current role, while backend authorization remains authoritative.

#### Scenario: Admin opens workspace
- **WHEN** an authenticated admin opens `/admin`
- **THEN** the admin layout displays navigation and the selected workspace view.

### Requirement: Shared evidence components
The frontend SHALL provide DisclaimerBar, SourceCard, CitationList, ConfidenceBadge, EligibilityList, TierCard, StrategyTabs, SourceTag, DataStatusTag, EmptyState, and LoadingSkeleton components. Components SHALL expose typed props and be reusable across user and admin views.

#### Scenario: Factual result is rendered
- **WHEN** a result has citations and source metadata
- **THEN** the UI renders its evidence and confidence state through shared components.

#### Scenario: Factual result lacks citations
- **WHEN** a result has no citations
- **THEN** the UI does not render it as a confirmed conclusion and shows an unavailable or verification state.

### Requirement: Core user flows
The frontend SHALL support mock-driven flows for authentication, profile editing, eligibility checking, cited multi-turn QA, recommendation and plan generation, risk check, plan CRUD, school/major search and detail, school profile/life information, comparison, favorites, and QA history.

#### Scenario: Mock mode is enabled
- **WHEN** `VITE_USE_MOCK=true`
- **THEN** every core page can render success, loading, empty, and error states without the backend.

### Requirement: Visual system and responsive behavior
The frontend SHALL use the Editorial visual system and remain usable on desktop and mobile widths.

#### Scenario: Viewport changes
- **WHEN** the viewport is narrower than the desktop grid
- **THEN** navigation, cards, forms, tables, and source details reflow without horizontal overflow.

### Requirement: Frontend quality gates
The frontend SHALL pass TypeScript checking, production build, route smoke checks, and the documented core-flow checklist. API DTOs and Mock payloads SHALL follow the product book's Chapter 6 field names and the shared response envelope; pagination SHALL use `items`, `total`, `page`, and `page_size`.

#### Scenario: Build verification runs
- **WHEN** a member runs the documented validation commands
- **THEN** typecheck, build, and route checks complete without errors.

### Requirement: API integration and error handling
The frontend SHALL route all network access through `src/api` and a shared request utility that applies the configured base URL, attaches bearer tokens, unwraps successful `data`, and handles business error codes consistently.

#### Scenario: Protected API returns unauthenticated
- **WHEN** an API response has code `1002`
- **THEN** the client clears the stored token and redirects to `/login` while preserving the intended destination.

#### Scenario: QA returns no data or degraded output
- **WHEN** QA returns code `2001` or `2002`, or `degraded=true`
- **THEN** the UI shows the documented fallback/degraded state rather than a generic failure dialog.

### Requirement: Admin workflows
The admin frontend SHALL support document filtering and upload/delete, index rebuild and progress, pathway/rule maintenance with source validation feedback, review task list/detail/actions, and statistics summaries using the documented admin DTOs.

#### Scenario: Admin reviews a low-confidence answer
- **WHEN** an authorized admin opens a pending review task
- **THEN** the UI shows the question, answer, confidence, trigger reason, citations, and approve/correct/reject actions.

