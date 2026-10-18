mod controller;
mod db;
mod ringbuffer;
mod security;
mod webhook;

use actix_web::{App, HttpServer, web};
use std::{env, io, sync::Arc};

use security::{CognitoAuth, CognitoClient, CognitoConfig};

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = env::var("DATABASE_URL").unwrap_or_else(|_| {
        "postgres://orchestrator:orchestrator_dev_password@localhost:5432/orchestrator".to_owned()
    });
    let pool = db::create_pool(&database_url)
        .map_err(|error| io::Error::other(format!("failed to create database pool: {error}")))?;
    let pool = web::Data::new(pool);

    // --- Cognito JWT authentication (opt-in via environment variables) ---
    // When COGNITO_REGION/AWS_REGION, COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID
    // are set, every route except public health checks requires a valid Cognito
    // JWT. Otherwise the middleware is skipped and the service runs unauthenticated
    // (suitable for local development).
    let cognito_client: Option<Arc<CognitoClient>> = match CognitoConfig::from_env() {
        Ok(config) => {
            let client = Arc::new(
                CognitoClient::new(config)
                    .map_err(|error| io::Error::other(format!("cognito client: {error}")))?,
            );
            // Load the JWKS at startup so tokens can be verified. If Cognito is
            // unreachable this is non-fatal; requests fail with 401 until the
            // keys are loaded.
            if let Err(error) = client.refresh_jwks().await {
                eprintln!("warning: failed to load Cognito JWKS: {error}");
            }

            // Refresh periodically so rotated signing keys are picked up.
            let refresh_client = client.clone();
            let refresh_interval = client.config().jwks_ttl;
            tokio::spawn(async move {
                let mut ticker = tokio::time::interval(refresh_interval);
                ticker.tick().await; // the first tick completes immediately
                loop {
                    ticker.tick().await;
                    if let Err(error) = refresh_client.refresh_jwks().await {
                        eprintln!("warning: failed to refresh Cognito JWKS: {error}");
                    }
                }
            });

            Some(client)
        }
        Err(error) => {
            eprintln!("warning: Cognito authentication disabled ({error})");
            None
        }
    };

    HttpServer::new(move || {
        App::new()
            .app_data(pool.clone())
            .app_data(web::Data::new(cognito_client.clone()))
            // Protect every route except public health checks. When Cognito is
            // not configured the middleware passes requests through unauthenticated.
            .wrap(CognitoAuth::new(cognito_client.clone()).exclude("/health"))
            .configure(controller::configure_routes)
    })
    .bind(("0.0.0.0", 8080))?
    .run()
    .await
}
