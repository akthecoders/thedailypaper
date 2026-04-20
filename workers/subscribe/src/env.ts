export interface Env {
  // Secrets
  RESEND_API_KEY: string;
  RESEND_AUDIENCE_ID: string;
  SUBSCRIPTION_SECRET: string;
  TURNSTILE_SECRET_KEY: string;
  // Vars
  SITE_URL: string;
  FROM_ADDRESS: string;
  REPLY_TO: string;
  // Bindings
  SUBSCRIBE_CACHE: KVNamespace;
}
