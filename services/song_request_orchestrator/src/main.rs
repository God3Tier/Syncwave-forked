mod controller;
mod db;
mod models;
mod ringbuffer;
mod security;
mod webhook;

use actix_web::{App, HttpServer, web};
use std::{env, io, sync::Arc};

use security::{AuthClient, AuthConfig, SessionAuth};

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = env::var("DATABASE_URL").unwrap_or_else(|_| {
        "postgres://orchestrator:orchestrator_dev_password@localhost:5432/orchestrator".to_owned()
    });
    let pool = db::create_pool(&database_url)
        .map_err(|error| io::Error::other(format!("failed to create database pool: {error}")))?;
    let pool = web::Data::new(pool);
    let webhook = web::Data::new(webhook::client::WebHookClient::from_env());
    let playback_sessions: web::Data<controller::orchestrator::PlaybackSessions> = web::Data::new(
        Arc::new(tokio::sync::Mutex::new(std::collections::HashMap::new())),
    );

    // SyncWave account authentication is enabled when AUTH_JWKS_URL is set.
    let auth_client: Option<Arc<AuthClient>> = match AuthConfig::from_env() {
        Ok(config) => {
            let client = Arc::new(
                AuthClient::new(config)
                    .map_err(|error| io::Error::other(format!("auth client: {error}")))?,
            );
            client.refresh_jwks().await.map_err(|error| {
                io::Error::other(format!("failed to load SyncWave Auth JWKS: {error}"))
            })?;

            // Refresh periodically so rotated signing keys are picked up.
            let refresh_client = client.clone();
            let refresh_interval = client.config().jwks_ttl;
            tokio::spawn(async move {
                let mut ticker = tokio::time::interval(refresh_interval);
                ticker.tick().await; // the first tick completes immediately
                loop {
                    ticker.tick().await;
                    if let Err(error) = refresh_client.refresh_jwks().await {
                        eprintln!("warning: failed to refresh SyncWave Auth JWKS: {error}");
                    }
                }
            });

            Some(client)
        }
        Err(error) => {
            eprintln!("warning: SyncWave authentication disabled ({error})");
            None
        }
    };

    HttpServer::new(move || {
        App::new()
            .app_data(pool.clone())
            .app_data(webhook.clone())
            .app_data(playback_sessions.clone())
            .app_data(web::Data::new(auth_client.clone()))
            // Protect every route except public health checks. When Auth is
            // not configured the middleware passes requests through unauthenticated.
            .wrap(SessionAuth::new(auth_client.clone()).exclude("/health"))
            .configure(controller::configure_routes)
    })
    .bind(("0.0.0.0", 8080))?
    .run()
    .await
}
