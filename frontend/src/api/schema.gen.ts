/**
 * Generated from openapi.json by `pnpm gen:api` (openapi-typescript). Do not edit by hand.
 */

export interface paths {
    "/api/v1/admin/api-keys": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List API tokens
         * @description Metadata of all tokens; the token itself and its hash are never included.
         */
        get: operations["list_api_keys_api_v1_admin_api_keys_get"];
        put?: never;
        /**
         * Create an API token
         * @description Create a token. The response's ``token`` is the only time the plaintext is shown.
         */
        post: operations["create_api_key_api_v1_admin_api_keys_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/admin/api-keys/{key_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete an API token
         * @description Delete a token; it is rejected from the next request on.
         */
        delete: operations["delete_api_key_api_v1_admin_api_keys__key_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update an API token
         * @description Change name, note, enabled or expiry. Scope and token value cannot change.
         */
        patch: operations["update_api_key_api_v1_admin_api_keys__key_id__patch"];
        trace?: never;
    };
    "/api/v1/auth/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Current sign-in
         * @description The caller's own sign-in: a session (with its CSRF token) or the API token.
         */
        get: operations["get_sign_in_api_v1_auth_session_get"];
        put?: never;
        /**
         * Sign in to the web UI
         * @description Opens a browser session and sets the session and CSRF cookies. With a body ``{token}`` the API token is checked; without a body the active identity providers are asked (trusted SSO headers). Needs an ``Origin`` of the public URL; rate limited per client address.
         */
        post: operations["sign_in_api_v1_auth_session_post"];
        /**
         * Sign out
         * @description Revoke the current browser session and clear its cookies.
         */
        delete: operations["sign_out_api_v1_auth_session_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/communication": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List communication log entries */
        get: operations["list_communication_api_v1_communication_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/communication/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get a communication log entry */
        get: operations["get_communication_api_v1_communication__entry_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List events */
        get: operations["list_events_api_v1_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Stream events (server-sent events) */
        get: operations["stream_events_api_v1_events_stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events/{event_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get an event with its deliveries */
        get: operations["get_event_api_v1_events__event_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/info": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Name, version and build of this server */
        get: operations["info_api_v1_info_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/provider-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List provider types */
        get: operations["list_provider_types_api_v1_provider_types_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/provider-types/{kind}/{type_name}/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test unsaved values of a new instance */
        post: operations["test_provider_type_api_v1_provider_types__kind___type_name__test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List provider instances */
        get: operations["list_providers_api_v1_providers_get"];
        put?: never;
        /** Create a provider instance */
        post: operations["create_provider_api_v1_providers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/{instance_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get a provider instance */
        get: operations["get_provider_api_v1_providers__instance_id__get"];
        put?: never;
        post?: never;
        /** Delete a provider instance */
        delete: operations["delete_provider_api_v1_providers__instance_id__delete"];
        options?: never;
        head?: never;
        /** Change a provider instance */
        patch: operations["update_provider_api_v1_providers__instance_id__patch"];
        trace?: never;
    };
    "/api/v1/providers/{instance_id}/actions/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Run an action of a running instance */
        post: operations["run_provider_action_api_v1_providers__instance_id__actions__name__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/providers/{instance_id}/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Test a stored instance, optionally with unsaved values */
        post: operations["test_provider_api_v1_providers__instance_id__test_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List settings */
        get: operations["list_settings_api_v1_settings_get"];
        /** Update settings */
        put: operations["update_settings_api_v1_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/continue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Continue to the web UI after sign-in */
        get: operations["auth_continue_auth_continue_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Liveness probe
         * @description Report that the process is up. No auth, no version, no dependencies.
         */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Readiness probe */
        get: operations["readiness_readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ActionRequest */
        ActionRequest: {
            /** Params */
            params?: {
                [key: string]: unknown;
            };
        };
        /** ActionResult */
        ActionResult: {
            /** Result */
            result: {
                [key: string]: unknown;
            };
        };
        /** ActionView */
        ActionView: {
            /** Name */
            name: string;
            /** Params Schema */
            params_schema: {
                [key: string]: unknown;
            };
        };
        /** ApiKeyCreate */
        ApiKeyCreate: {
            /** Expires At */
            expires_at?: string | null;
            /** Name */
            name: string;
            /** Note */
            note?: string | null;
            /**
             * Rate Limit Per Minute
             * @default 60
             */
            rate_limit_per_minute: number;
            /**
             * Scope
             * @enum {string}
             */
            scope: "read" | "operate" | "admin";
        };
        /** ApiKeyCreated */
        ApiKeyCreated: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Enabled */
            enabled: boolean;
            /** Expires At */
            expires_at: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Name */
            name: string;
            /** Note */
            note: string | null;
            /**
             * Owner User Id
             * Format: uuid
             */
            owner_user_id: string;
            /** Prefix */
            prefix: string;
            /** Rate Limit Per Minute */
            rate_limit_per_minute: number;
            /**
             * Scope
             * @enum {string}
             */
            scope: "read" | "operate" | "admin";
            /**
             * Token
             * @description The full token. Shown once, never again.
             */
            token: string;
        };
        /** ApiKeyRead */
        ApiKeyRead: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Enabled */
            enabled: boolean;
            /** Expires At */
            expires_at: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Last Used At */
            last_used_at: string | null;
            /** Name */
            name: string;
            /** Note */
            note: string | null;
            /**
             * Owner User Id
             * Format: uuid
             */
            owner_user_id: string;
            /** Prefix */
            prefix: string;
            /** Rate Limit Per Minute */
            rate_limit_per_minute: number;
            /**
             * Scope
             * @enum {string}
             */
            scope: "read" | "operate" | "admin";
        };
        /**
         * ApiKeyUpdate
         * @description Only the fields that are sent change; ``null`` clears ``note`` and ``expires_at``.
         */
        ApiKeyUpdate: {
            /** Enabled */
            enabled?: boolean | null;
            /** Expires At */
            expires_at?: string | null;
            /** Name */
            name?: string | null;
            /** Note */
            note?: string | null;
        };
        /** CommunicationDetail */
        CommunicationDetail: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "outbound" | "inbound";
            /** Duration Ms */
            duration_ms: number;
            /** Error */
            error: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Instance Id
             * Format: uuid
             */
            instance_id: string;
            /** Method */
            method: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Request Body */
            request_body: string | null;
            /** Request Headers */
            request_headers: {
                [key: string]: unknown;
            };
            /** Response Body */
            response_body: string | null;
            /** Response Headers */
            response_headers: {
                [key: string]: unknown;
            };
            /**
             * Status
             * @description Status code of the answer; null without an answer
             */
            status: number | null;
            /** Target */
            target: string;
            /** Truncated */
            truncated: boolean;
        };
        /** CommunicationPage */
        CommunicationPage: {
            /**
             * Items
             * @description Newest first
             */
            items: components["schemas"]["CommunicationSummary"][];
            /**
             * Next Cursor
             * @description Pass as ``cursor`` for the next (older) page; null on the last page
             */
            next_cursor: string | null;
        };
        /** CommunicationSummary */
        CommunicationSummary: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "outbound" | "inbound";
            /** Duration Ms */
            duration_ms: number;
            /** Error */
            error: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Instance Id
             * Format: uuid
             */
            instance_id: string;
            /** Method */
            method: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /**
             * Status
             * @description Status code of the answer; null without an answer
             */
            status: number | null;
            /** Target */
            target: string;
            /** Truncated */
            truncated: boolean;
        };
        /** DeliveryView */
        DeliveryView: {
            /** Attempts */
            attempts: number;
            /** Last Error */
            last_error: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "done" | "failed";
            /** Subscriber */
            subscriber: string;
        };
        /** EventDetail */
        EventDetail: {
            /** Correlation Id */
            correlation_id: string | null;
            /** Deliveries */
            deliveries: components["schemas"]["DeliveryView"][];
            /**
             * Delivery Status
             * @description Delivery state over all subscribers: failed = at least one delivery failed, pending = at least one is pending and none failed, done = all are done
             * @enum {string}
             */
            delivery_status: "pending" | "done" | "failed";
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Schema Version */
            schema_version: number;
            /**
             * Source Instance Id
             * @description The provider instance the event came from; null for the bridge itself
             */
            source_instance_id: string | null;
            /** Type */
            type: string;
        };
        /** EventPage */
        EventPage: {
            /**
             * Items
             * @description Newest first
             */
            items: components["schemas"]["EventView"][];
            /**
             * Next Cursor
             * @description Pass as ``cursor`` for the next (older) page; null on the last page
             */
            next_cursor: string | null;
        };
        /** EventTypeView */
        EventTypeView: {
            /** Name */
            name: string;
            /** Payload Schema */
            payload_schema: {
                [key: string]: unknown;
            };
            /** Schema Version */
            schema_version: number;
        };
        /** EventView */
        EventView: {
            /** Correlation Id */
            correlation_id: string | null;
            /**
             * Delivery Status
             * @description Delivery state over all subscribers: failed = at least one delivery failed, pending = at least one is pending and none failed, done = all are done
             * @enum {string}
             */
            delivery_status: "pending" | "done" | "failed";
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Schema Version */
            schema_version: number;
            /**
             * Source Instance Id
             * @description The provider instance the event came from; null for the bridge itself
             */
            source_instance_id: string | null;
            /** Type */
            type: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** Info */
        Info: {
            /** Build */
            build: string;
            /**
             * Name
             * @default BambuBridge
             * @constant
             */
            name: "BambuBridge";
            /** Version */
            version: string;
        };
        /** ProbeResultView */
        ProbeResultView: {
            /** Duration Ms */
            duration_ms: number;
            /** Message */
            message: string;
            /** Ok */
            ok: boolean;
        };
        /**
         * ProblemDetail
         * @description Problem details object returned with ``application/problem+json``.
         */
        ProblemDetail: {
            /**
             * Detail
             * @description Explanation specific to this occurrence
             */
            detail?: string | null;
            /**
             * Error Code
             * @description Stable machine-readable error code (snake_case), e.g. ``invalid_token``
             */
            error_code?: string | null;
            /**
             * Extensions
             * @description Problem-type-specific fields
             */
            extensions?: {
                [key: string]: unknown;
            };
            /**
             * Instance
             * @description URI reference of this occurrence
             */
            instance?: string | null;
            /**
             * Status
             * @description HTTP status code
             */
            status: number;
            /**
             * Title
             * @description Short human-readable summary
             */
            title: string;
            /**
             * Type
             * @description URI reference identifying the problem
             * @default about:blank
             */
            type: string;
        };
        /** ProviderCreate */
        ProviderCreate: {
            /** Config */
            config?: {
                [key: string]: unknown;
            };
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /**
             * Kind
             * @enum {string}
             */
            kind: "account" | "inventory" | "integration" | "display";
            /** Name */
            name: string;
            /** Type Name */
            type_name: string;
        };
        /** ProviderInstanceView */
        ProviderInstanceView: {
            /**
             * Config
             * @description Plain configuration; never holds a secret
             */
            config: {
                [key: string]: unknown;
            };
            /** Created By */
            created_by: string | null;
            /** Enabled */
            enabled: boolean;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "account" | "inventory" | "integration" | "display";
            /** Name */
            name: string;
            /** Secrets */
            secrets: {
                [key: string]: components["schemas"]["SecretState"];
            };
            status: components["schemas"]["StatusView"];
            /** Type Name */
            type_name: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Updated By */
            updated_by: string | null;
        };
        /**
         * ProviderTest
         * @description Unsaved form values; for a stored instance merged over what is stored.
         */
        ProviderTest: {
            /** Config */
            config?: {
                [key: string]: unknown;
            };
        };
        /** ProviderTypeView */
        ProviderTypeView: {
            /** Actions */
            actions: components["schemas"]["ActionView"][];
            /**
             * Config Schema
             * @description JSON schema of the configuration; secret fields carry "x-secret": true
             */
            config_schema: {
                [key: string]: unknown;
            };
            /** Event Types */
            event_types: components["schemas"]["EventTypeView"][];
            /**
             * Kind
             * @enum {string}
             */
            kind: "account" | "inventory" | "integration" | "display";
            /** Type Name */
            type_name: string;
        };
        /**
         * ProviderUpdate
         * @description Fields left out stay as they are; ``config`` is merged field by field.
         */
        ProviderUpdate: {
            /** Config */
            config?: {
                [key: string]: unknown;
            };
            /** Enabled */
            enabled?: boolean | null;
            /** Name */
            name?: string | null;
        };
        /** Readiness */
        Readiness: {
            /**
             * Database
             * @enum {string}
             */
            database: "ok" | "unavailable";
            /**
             * Listener
             * @enum {string}
             */
            listener: "ok" | "unavailable";
        };
        /** SecretState */
        SecretState: {
            /**
             * Set
             * @description A value is stored
             */
            set: boolean;
        };
        /** SessionInfo */
        SessionInfo: {
            /**
             * Csrf Token
             * @description Send in X-BambuBridge-CSRF with every state-changing request
             */
            csrf_token?: string | null;
            /** Expires At */
            expires_at?: string | null;
            /**
             * Identity Provider
             * @description Provider that opened the session; null for a token sign-in
             */
            identity_provider?: string | null;
            /**
             * Identity Subject
             * @description Subject the identity provider reported; null for a token sign-in
             */
            identity_subject?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "session" | "token";
            /**
             * Scope
             * @enum {string}
             */
            scope: "read" | "operate" | "admin";
            /**
             * User
             * @description Display name of the signed-in user
             */
            user?: string | null;
        };
        /** SettingView */
        SettingView: {
            /**
             * Choices
             * @description Allowed values, if fixed
             */
            choices?: string[] | null;
            /**
             * Default
             * @description Default value; always null for secrets
             */
            default: unknown;
            /** Key */
            key: string;
            /** Max */
            max?: number | null;
            /** Min */
            min?: number | null;
            /** Section */
            section: string;
            /**
             * Set
             * @description A value is stored (otherwise the default applies)
             */
            set: boolean;
            /**
             * Type
             * @enum {string}
             */
            type: "str" | "int" | "bool" | "url" | "secret" | "choice" | "choices";
            /**
             * Undecryptable
             * @description A stored secret cannot be decrypted
             */
            undecryptable: boolean;
            /**
             * Value
             * @description Effective value; always null for secrets
             */
            value: unknown;
        };
        /**
         * SettingsUpdate
         * @description ``null`` resets a setting to its default; ``null`` or ``""`` clears a secret.
         */
        SettingsUpdate: {
            /** Values */
            values: {
                [key: string]: unknown;
            };
        };
        /**
         * SignInRequest
         * @description Sign in with an API token. Without a body the identity providers are asked.
         */
        SignInRequest: {
            /** Token */
            token: string;
        };
        /** StatusView */
        StatusView: {
            /** Message */
            message: string | null;
            /**
             * Since
             * Format: date-time
             */
            since: string;
            /**
             * State
             * @enum {string}
             */
            state: "stopped" | "starting" | "connected" | "disconnected" | "error" | "needs_secret";
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_api_keys_api_v1_admin_api_keys_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKeyRead"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    create_api_key_api_v1_admin_api_keys_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApiKeyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKeyCreated"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    delete_api_key_api_v1_admin_api_keys__key_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    update_api_key_api_v1_admin_api_keys__key_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                key_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApiKeyUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiKeyRead"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    get_sign_in_api_v1_auth_session_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionInfo"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    sign_in_api_v1_auth_session_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["SignInRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionInfo"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    sign_out_api_v1_auth_session_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    list_communication_api_v1_communication_get: {
        parameters: {
            query?: {
                /** @description Earliest time (inclusive), ISO 8601 with a zone */
                from?: string | null;
                /** @description Latest time (exclusive), ISO 8601 with a zone */
                to?: string | null;
                /** @description Provider instance */
                instance?: string | null;
                /** @description Status code, class (4xx) or 'none' */
                status?: string | null;
                /** @description ``next_cursor`` of the previous page */
                cursor?: string | null;
                /** @description Page size */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommunicationPage"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    get_communication_api_v1_communication__entry_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommunicationDetail"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    list_events_api_v1_events_get: {
        parameters: {
            query?: {
                /** @description Earliest time (inclusive), ISO 8601 with a zone */
                from?: string | null;
                /** @description Latest time (exclusive), ISO 8601 with a zone */
                to?: string | null;
                /** @description Source provider instance */
                source?: string | null;
                /** @description Exact event type */
                type?: string | null;
                /** @description Delivery state over all subscribers (see EventView) */
                status?: ("pending" | "done" | "failed") | null;
                /** @description ``next_cursor`` of the previous page */
                cursor?: string | null;
                /** @description Page size */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventPage"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    stream_events_api_v1_events_stream_get: {
        parameters: {
            query?: never;
            header?: {
                /** @description Resume after this event id (sent by the browser on reconnect) */
                "Last-Event-ID"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description A ``text/event-stream`` of events */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": string;
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    get_event_api_v1_events__event_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                event_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventDetail"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    info_api_v1_info_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Info"];
                };
            };
        };
    };
    list_provider_types_api_v1_provider_types_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderTypeView"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    test_provider_type_api_v1_provider_types__kind___type_name__test_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                kind: string;
                type_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProviderTest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProbeResultView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    list_providers_api_v1_providers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderInstanceView"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    create_provider_api_v1_providers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProviderCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderInstanceView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    get_provider_api_v1_providers__instance_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderInstanceView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    delete_provider_api_v1_providers__instance_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    update_provider_api_v1_providers__instance_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProviderUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderInstanceView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    run_provider_action_api_v1_providers__instance_id__actions__name__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
                name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActionResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Bad Gateway */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    test_provider_api_v1_providers__instance_id__test_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ProviderTest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProbeResultView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    list_settings_api_v1_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingView"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    update_settings_api_v1_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    auth_continue_auth_continue_get: {
        parameters: {
            query?: {
                next?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Signed in; redirect to ``next`` */
            303: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not signed in; a browser navigation gets a page that moves on to the sign-in (text/html) */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Too many sign-in attempts; a browser navigation gets a page that moves on to the sign-in once Retry-After has passed (text/html) */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
        };
    };
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    readiness_readiness_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProblemDetail"];
                };
            };
            /** @description Database or settings listener unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
        };
    };
}
