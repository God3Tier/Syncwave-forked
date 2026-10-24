mod controller;
mod db;
mod models;
mod schema;
mod store;

use actix_web::{App, HttpServer, web};
use aws_sdk_s3::Client;
use aws_smithy_types::timeout::TimeoutConfig;
use std::{env, io, time::Duration};
use store::audio::AudioStore;

// pub type Error = Box<dyn std::error::Error + Send + Sync>;

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    let database_url = env::var("DATABASE_URL").unwrap_or_else(|_| {
        // TODO: Set this to panic if not available
        "postgres://orchestrator:orchestrator_dev_password@localhost:5432/orchestrator".to_owned()
    });

    // TODO: This should panic upon failure as well
    let pool = db::create_pool(&database_url)
        .map_err(|error| io::Error::other(format!("failed to create database pool: {error}")))?;
    db::initialize_schema(&pool).map_err(|error| {
        io::Error::other(format!("failed to initialize database schema: {error}"))
    })?;
    let pool = web::Data::new(pool);

    let config = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .timeout_config(
            TimeoutConfig::builder()
                .operation_timeout(Duration::from_secs(5))
                .operation_attempt_timeout(Duration::from_millis(1500))
                .build(),
        )
        .load()
        .await;
    let s3_client = Client::new(&config);
    let bucket_name = "TEMP".to_string();

    // TODO: Set the cache to be configurable
    let store = web::Data::new(AudioStore::new(10_000, s3_client, bucket_name));

    HttpServer::new(move || {
        App::new()
            .app_data(store.clone())
            .app_data(pool.clone())
            .configure(controller::configure_routes)
    })
    .bind(("0.0.0.0", 8081))?
    .run()
    .await
}
