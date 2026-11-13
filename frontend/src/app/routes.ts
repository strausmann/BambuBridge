/**
 * The pages of the signed-in shell, as plain data: the navigation test (e2e/navigation.spec.ts)
 * walks every one of them by tapping, and a unit test (src/app/routes.test.tsx) keeps the list
 * equal to the routes the router really has.
 */
export const SHELL_PAGES = ["/", "/providers", "/protocol", "/settings", "/device"] as const;

/** Pages shown without a sign-in. */
export const PUBLIC_PAGES = ["/sign-in", "/bootstrap"] as const;

/** Routes with a parameter; the navigation test reaches them through a page that links to them. */
export const PARAMETER_ROUTES = ["/settings/$section"] as const;
